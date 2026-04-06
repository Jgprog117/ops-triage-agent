import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.agent.parser import parse_tool_arguments, parse_triage_result
from backend.agent.prompts import TRIAGE_SYSTEM_PROMPT, TOOL_DEFINITIONS
from backend.agent.tools import execute_tool
from backend.db.database import update_alert_triage_status, insert_audit_log
from backend.db.models import TriageResult
from backend.llm.client import llm
from backend.sse.broadcaster import broadcast_triage_step

logger = logging.getLogger(__name__)

MAX_STEPS = 8

# Concurrency limiter — prevent overwhelming the LLM API
_semaphore = asyncio.Semaphore(2)


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
            for iteration in range(MAX_STEPS):
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
                    triage_result = parse_triage_result(content)

                    if triage_result is None:
                        logger.warning("Failed to parse triage result for alert %s, using default", alert_id)
                        triage_result = TriageResult(
                            classification="acknowledged",
                            root_cause_hypothesis="Unable to determine — triage response parsing failed",
                            summary=f"Alert {alert_id}: {alert['message']}",
                            summary_ja=f"アラート {alert_id}: 自動解析に失敗しました",
                        )

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

        except Exception:
            logger.exception("Triage failed for alert %s", alert_id)
            await update_alert_triage_status(alert_id, "error")
            error_result = TriageResult(
                classification="acknowledged",
                root_cause_hypothesis="Triage agent error — manual review required",
                summary=f"Triage failed for alert {alert_id}: {alert['message']}",
                summary_ja=f"トリアージ失敗 アラート {alert_id} — 手動確認が必要です",
            )
            step_num += 1
            await _broadcast_step(alert_id, step_num, "final_triage", triage_result=error_result)
            return error_result
