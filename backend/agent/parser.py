import json
import logging
import re
from typing import Any

from backend.db.models import TriageResult
from backend.exceptions import ParseError

logger = logging.getLogger(__name__)


def parse_tool_arguments(raw: str) -> dict[str, Any] | None:
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
    """Walk the string and extract the first balanced {...} substring."""
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
    """Parse LLM output into a TriageResult. Raises ParseError on failure."""
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
