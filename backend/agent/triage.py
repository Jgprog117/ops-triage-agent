import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from backend.agent.parser import parse_tool_arguments, parse_triage_result
from backend.agent.prompts import TRIAGE_SYSTEM_PROMPT, TOOL_DEFINITIONS
from backend.agent.tools import execute_tool
from backend.config import settings
from backend.db.database import update_alert_triage_status, insert_audit_log
from backend.db.models import TriageResult
from backend.exceptions import (
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
    LLMTimeoutError,
    ParseError,
)
from backend.llm.client import llm
from backend.sse.broadcaster import broadcast_triage_step

logger = logging.getLogger(__name__)

# Concurrency limiter — prevent overwhelming the LLM API
_semaphore = asyncio.Semaphore(settings.TRIAGE_CONCURRENCY)


def _build_user_message(alert: dict) -> str:
    return f"""A new alert has been received. Triage it.

Alert details:
- ID: {alert['id']}
- Timestamp: {alert['timestamp']}
- Severity: {alert['severity']}
- Category: {alert['category']}
- Component: {alert['component']}
- Host: {alert['host']}
- Rack: {alert['rack']}
- Datacenter: {alert['datacenter']}
- Metric: {alert['metric_name']} = {alert['metric_value']} (threshold: {alert['threshold']})
- Message: {alert['message']}
- Additional data: {json.dumps(alert.get('raw_data', {}))}

Investigate this alert: check for correlated alerts, consult runbooks, and provide your triage assessment."""


async def _broadcast_step(
    alert_id: str,
    step_num: int,
    step_type: str,
    tool_name: str | None = None,
    tool_input: dict | None = None,
    tool_output: Any = None,
    triage_result: TriageResult | None = None,
) -> None:
    step_data = {
        "alert_id": alert_id,
        "step": step_num,
        "type": step_type,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_output": tool_output,
        "triage_result": triage_result.model_dump() if triage_result else None,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    await broadcast_triage_step(alert_id, step_data)


async def _safe_update_status(alert_id: str, status: str) -> None:
    """Update alert status, swallowing DB errors to avoid masking the original exception."""
    try:
        await update_alert_triage_status(alert_id, status)
    except Exception:
        logger.warning("Failed to update triage status to '%s' for alert %s", status, alert_id)


async def triage_alert(alert: dict) -> TriageResult | None:
    async with _semaphore:
        alert_id = alert["id"]
        logger.info("Starting triage for alert %s (%s: %s)",
                     alert_id, alert["severity"], alert["message"][:80])

        await update_alert_triage_status(alert_id, "triaging")
        await insert_audit_log("triage_started", alert_id, {"severity": alert["severity"]})

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(alert)},
        ]

        step_num = 0

        try:
            for iteration in range(settings.TRIAGE_MAX_STEPS):
                response = await llm.chat_completion(messages, tools=TOOL_DEFINITIONS)
                message = llm.extract_message(response)

                if llm.has_tool_calls(message):
                    tool_calls = llm.get_tool_calls(message)
                    messages.append(message)

                    for tc in tool_calls:
                        step_num += 1
                        func_name = tc["function"]["name"]
                        raw_args = tc["function"]["arguments"]
                        arguments = parse_tool_arguments(raw_args)

                        await _broadcast_step(
                            alert_id, step_num, "tool_call",
                            tool_name=func_name, tool_input=arguments or {},
                        )

                        if arguments is None:
                            result = json.dumps({"error": f"Failed to parse arguments for {func_name}. Ensure valid JSON."})
                        else:
                            result = await execute_tool(func_name, arguments)

                        step_num += 1
                        display_result = result if len(result) < 2000 else result[:2000] + "...(truncated)"
                        await _broadcast_step(
                            alert_id, step_num, "tool_result",
                            tool_name=func_name, tool_output=display_result,
                        )

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })
                else:
                    content = llm.get_content(message)
                    try:
                        triage_result = parse_triage_result(content)
                    except ParseError:
                        # Retry once with explicit JSON instruction
                        logger.warning("Parse failed for alert %s, retrying with JSON prompt", alert_id)
                        messages.append(message)
                        messages.append({
                            "role": "user",
                            "content": "Your previous response could not be parsed as JSON. Please respond with ONLY the JSON triage report, no other text.",
                        })
                        retry_response = await llm.chat_completion(messages)
                        retry_message = llm.extract_message(retry_response)
                        retry_content = llm.get_content(retry_message)
                        try:
                            triage_result = parse_triage_result(retry_content)
                        except ParseError:
                            logger.error("Parse retry also failed for alert %s", alert_id)
                            triage_result = TriageResult(
                                classification="acknowledged",
                                root_cause_hypothesis="Unable to determine — triage response parsing failed",
                                summary=f"Alert {alert_id}: {alert['message']}",
                                summary_ja=f"アラート {alert_id}: 自動解析に失敗しました",
                            )
                            await _safe_update_status(alert_id, "parse_error")

                    step_num += 1
                    await _broadcast_step(
                        alert_id, step_num, "final_triage",
                        triage_result=triage_result,
                    )

                    await update_alert_triage_status(alert_id, "triaged")
                    await insert_audit_log("triage_completed", alert_id, {
                        "classification": triage_result.classification,
                        "escalation_required": triage_result.escalation_required,
                    })

                    logger.info("Triage complete for %s: %s", alert_id, triage_result.classification)
                    return triage_result

            logger.warning("Max steps reached for alert %s", alert_id)
            fallback = TriageResult(
                classification="acknowledged",
                root_cause_hypothesis="Triage reached maximum analysis steps",
                summary=f"Alert {alert_id}: {alert['message']} — requires manual review",
                summary_ja=f"アラート {alert_id}: {alert['message']} — 手動確認が必要です",
            )
            step_num += 1
            await _broadcast_step(alert_id, step_num, "final_triage", triage_result=fallback)
            await update_alert_triage_status(alert_id, "triaged")
            return fallback

        except LLMRateLimitError:
            logger.error("Rate limited during triage for alert %s", alert_id)
            await _safe_update_status(alert_id, "retry_pending")
            return _error_result(alert_id, alert, "LLM rate limited — retry pending")

        except LLMTimeoutError:
            logger.error("LLM timeout during triage for alert %s", alert_id)
            await _safe_update_status(alert_id, "error")
            return _error_result(alert_id, alert, "LLM request timed out")

        except LLMResponseError as e:
            logger.error("Malformed LLM response for alert %s: %s", alert_id, e)
            await _safe_update_status(alert_id, "error")
            return _error_result(alert_id, alert, "LLM returned malformed response")

        except (LLMServerError,) as e:
            logger.error("LLM server error during triage for alert %s: %s", alert_id, e)
            await _safe_update_status(alert_id, "error")
            return _error_result(alert_id, alert, "LLM server error")

        except aiosqlite.Error as e:
            logger.error("Database error during triage for alert %s: %s", alert_id, e)
            # Don't try further DB writes — DB may be down
            return _error_result(alert_id, alert, "Database error — manual review required")

        except Exception:
            logger.exception("Unexpected error during triage for alert %s", alert_id)
            await _safe_update_status(alert_id, "error")
            error_result = _error_result(alert_id, alert, "Triage agent error — manual review required")
            step_num += 1
            await _broadcast_step(alert_id, step_num, "final_triage", triage_result=error_result)
            return error_result


def _error_result(alert_id: str, alert: dict, reason: str) -> TriageResult:
    return TriageResult(
        classification="acknowledged",
        root_cause_hypothesis=reason,
        summary=f"Triage failed for alert {alert_id}: {alert['message']}",
        summary_ja=f"トリアージ失敗 アラート {alert_id} — 手動確認が必要です",
    )
