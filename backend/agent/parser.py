import json
import logging
import re
from typing import Any

from backend.db.models import TriageResult

logger = logging.getLogger(__name__)


def parse_tool_arguments(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse tool arguments: %s", str(raw)[:200])
        return None


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

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
