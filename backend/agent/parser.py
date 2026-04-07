"""Parsers for LLM tool arguments and final triage reports.

The triage agent receives free-form text from the model and must coerce it
into structured Python objects. This module is intentionally lenient: real
models occasionally wrap JSON in code fences or prose, and these helpers try
several extraction strategies before giving up.
"""

import json
import logging
import re
from typing import Any

from backend.db.models import TriageResult
from backend.exceptions import ParseError

logger = logging.getLogger(__name__)


def parse_tool_arguments(raw: str) -> dict[str, Any] | None:
    """Parses a tool-call ``arguments`` string into a Python dict.

    Tries a strict ``json.loads`` first. If that fails, falls back to
    :func:`extract_json_from_text` which handles fenced and embedded JSON.

    Args:
        raw: The raw arguments string emitted by the LLM. May be ``None``
            or non-JSON text in degenerate cases.

    Returns:
        The parsed dict on success, or ``None`` if no JSON object could be
        extracted from the input.
    """
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: try extracting JSON from wrapped text
    result = extract_json_from_text(raw or "")
    if result is not None:
        return result

    logger.warning("Failed to parse tool arguments: %s", str(raw)[:200])
    return None


def _extract_outermost_json(text: str) -> str | None:
    """Extracts the first balanced ``{...}`` substring from ``text``.

    Walks the string character-by-character tracking brace depth and string
    state so that braces inside JSON string literals do not confuse the
    matcher. Used as a last-resort extractor for nested JSON wrapped in
    arbitrary prose.

    Args:
        text: The source text to scan.

    Returns:
        The matched substring including its outer braces, or ``None`` when
        no balanced object is found.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue

        if ch == "\\":
            if in_string:
                escape = True
            continue

        if ch == '"' and not escape:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """Extracts a JSON object from arbitrary LLM text.

    Tries, in order: a direct ``json.loads`` of the trimmed text, fenced
    code blocks (\\`\\`\\`json ... \\`\\`\\` and unlabelled \\`\\`\\` ... \\`\\`\\`),
    and finally a balanced-brace walk via :func:`_extract_outermost_json`.

    Args:
        text: Free-form text that should contain a single JSON object.

    Returns:
        The parsed dict on success, or ``None`` if no candidate parsed.
    """
    text = text.strip()

    # Try direct parse first
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try fenced code blocks (newline-insensitive)
    fenced_patterns = [
        r"```json\s*([\s\S]*?)\s*```",
        r"```\s*([\s\S]*?)\s*```",
    ]
    for pattern in fenced_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue

    # Bracket-counting extraction for arbitrary nesting depth
    candidate = _extract_outermost_json(text)
    if candidate:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def parse_triage_result(content: str) -> TriageResult:
    """Parses an LLM final-message string into a :class:`TriageResult`.

    Extracts JSON via :func:`extract_json_from_text`, normalizes a few
    field-name variations (e.g., ``root_cause`` is accepted as an alias of
    ``root_cause_hypothesis``), and constructs the Pydantic model.

    Args:
        content: The raw LLM message body, expected to contain the triage
            JSON either standalone or in a fenced block.

    Returns:
        A populated :class:`TriageResult`.

    Raises:
        ParseError: If no JSON object can be extracted, or if extracted
            data fails to validate against :class:`TriageResult`. The raw
            input is attached to the exception for downstream logging.
    """
    data = extract_json_from_text(content)
    if data is None:
        raise ParseError("Could not extract triage JSON from response", raw_content=content)

    try:
        # Normalize field names (handle minor variations)
        normalized = {
            "classification": data.get("classification", "acknowledged"),
            "root_cause_hypothesis": data.get("root_cause_hypothesis", data.get("root_cause", "Unknown")),
            "correlated_alert_ids": data.get("correlated_alert_ids", []),
            "remediation_steps": data.get("remediation_steps", []),
            "escalation_required": data.get("escalation_required", False),
            "escalation_reason": data.get("escalation_reason"),
            "summary": data.get("summary", "Triage completed"),
            "summary_ja": data.get("summary_ja", "トリアージ完了"),
        }
        return TriageResult(**normalized)
    except Exception as e:
        raise ParseError(
            f"Failed to construct TriageResult from parsed data: {e}",
            raw_content=content,
        ) from e
