"""Response parsing utilities for the triage agent.

Handles extraction of tool calls and final triage results from
LLM responses, with robust JSON parsing that handles markdown
code fences and partial outputs.
"""

import json
import logging
import re
from typing import Any

from backend.db.models import TriageResult

logger = logging.getLogger(__name__)


def parse_tool_arguments(raw: str) -> dict[str, Any]:
    """Parse tool call arguments from a JSON string.

    Handles cases where the LLM might return slightly malformed JSON.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse tool arguments: %s", raw[:200])
        return {}


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from text that may contain markdown code fences."""
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try extracting from code fence
    patterns = [
        r"```json\s*\n(.*?)\n\s*```",
        r"```\s*\n(.*?)\n\s*```",
        r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            candidate = match.group(1) if match.lastindex else match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    return None


def parse_triage_result(content: str) -> TriageResult | None:
    """Parse the final triage result from the agent's response.

    Args:
        content: The text content of the LLM's final response.

    Returns:
        A TriageResult if parsing succeeds, None otherwise.
    """
    data = extract_json_from_text(content)
    if data is None:
        logger.warning("Could not extract triage JSON from response")
        return None

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
    except Exception:
        logger.exception("Failed to construct TriageResult from parsed data")
        return None
