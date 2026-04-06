import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from typing import Any

import httpx

from backend.config import settings
from backend.db.database import (
    get_host,
    get_recent_alerts,
    insert_escalation,
    insert_incident,
    insert_audit_log,
)
from backend.knowledge.rag import search_runbooks as kb_search

logger = logging.getLogger(__name__)


async def query_recent_alerts(
    minutes_ago: int = 15,
    rack: str | None = None,
    host: str | None = None,
    category: str | None = None,
    severity: str | None = None,
) -> str:
    alerts = await get_recent_alerts(
        minutes_ago=minutes_ago,
        rack=rack,
        host=host,
        category=category,
        severity=severity,
        limit=20,
    )

    if not alerts:
        return json.dumps({"count": 0, "alerts": [], "message": "No matching alerts found"})

    summary = []
    for a in alerts:
        summary.append({
            "id": a["id"],
            "timestamp": a["timestamp"],
            "severity": a["severity"],
            "category": a["category"],
            "component": a["component"],
            "host": a["host"],
            "rack": a["rack"],
            "message": a["message"],
            "metric_name": a["metric_name"],
            "metric_value": a["metric_value"],
        })

    return json.dumps({"count": len(summary), "alerts": summary}, indent=2)


async def search_runbooks_tool(query: str) -> str:
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, lambda: kb_search(query, n_results=3))

    if not results:
        return json.dumps({"message": "No relevant runbook entries found"})

    formatted = []
    for r in results:
        formatted.append({
            "source": r["source"],
            "section": r["section"],
            "content": r["text"],
            "relevance": r["relevance_score"],
        })

    return json.dumps({"results": formatted}, indent=2)


async def get_host_info(host: str) -> str:
    host_data = await get_host(host)

    if not host_data:
        return json.dumps({"error": f"Host '{host}' not found in inventory"})

    return json.dumps({
        "hostname": host_data["hostname"],
        "rack": host_data["rack"],
        "datacenter": host_data["datacenter"],
        "gpu_type": host_data["gpu_type"],
        "gpu_count": host_data["gpu_count"],
        "cpu_type": host_data["cpu_type"],
        "memory_gb": host_data["memory_gb"],
        "os": host_data["os"],
        "status": host_data["status"],
        "uptime_hours": host_data["uptime_hours"],
        "last_incident_id": host_data["last_incident_id"],
        "metadata": host_data["metadata"],
    }, indent=2)


async def create_incident_tool(
    title: str,
    severity: str,
    summary: str,
    root_cause: str | None = None,
    remediation_steps: list[str] | None = None,
    correlated_alert_ids: list[str] | None = None,
    assigned_team: str | None = None,
) -> str:
    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"

    incident = {
        "id": incident_id,
        "title": title,
        "severity": severity,
        "summary": summary,
        "root_cause": root_cause,
        "remediation_steps": remediation_steps or [],
        "correlated_alert_ids": correlated_alert_ids or [],
        "assigned_team": assigned_team or "dc-ops-tokyo",
        "status": "open",
    }

    await insert_incident(incident)
    await insert_audit_log("incident_created", incident_id, {
        "title": title,
        "severity": severity,
        "assigned_team": incident["assigned_team"],
    })

    logger.info("Incident created: %s — %s (%s)", incident_id, title, severity)

    return json.dumps({
        "incident_id": incident_id,
        "title": title,
        "severity": severity,
        "status": "open",
        "assigned_team": incident["assigned_team"],
        "message": f"Incident {incident_id} created successfully",
    })


async def escalate_tool(
    incident_id: str,
    reason: str,
    urgency: str,
    notification_channels: list[str] | None = None,
) -> str:
    escalation_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
    channels = notification_channels or ["slack", "pager"]

    escalation = {
        "id": escalation_id,
        "incident_id": incident_id,
        "reason": reason,
        "urgency": urgency,
        "notification_channels": channels,
    }

    await insert_escalation(escalation)
    await insert_audit_log("escalation_sent", escalation_id, {
        "incident_id": incident_id,
        "urgency": urgency,
        "channels": channels,
    })

    logger.info("Escalation %s sent for incident %s (urgency: %s)",
                escalation_id, incident_id, urgency)

    if settings.WEBHOOK_URL:
        task = asyncio.create_task(_send_webhook(escalation))
        _webhook_tasks.add(task)
        task.add_done_callback(_webhook_tasks.discard)

    return json.dumps({
        "escalation_id": escalation_id,
        "incident_id": incident_id,
        "urgency": urgency,
        "notification_channels": channels,
        "message": f"Escalation {escalation_id} sent via {', '.join(channels)}",
    })


_webhook_tasks: set[asyncio.Task] = set()


async def _send_webhook(payload: dict) -> None:
    try:
        body = json.dumps(payload)
        headers = {"Content-Type": "application/json"}
        if settings.WEBHOOK_SECRET:
            sig = hmac.new(settings.WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-Signature-SHA256"] = sig
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.WEBHOOK_URL, content=body, headers=headers)
            logger.info("Webhook sent: %d", resp.status_code)
    except Exception:
        logger.exception("Webhook delivery failed")


TOOL_REGISTRY: dict[str, Any] = {
    "query_recent_alerts": query_recent_alerts,
    "search_runbooks": search_runbooks_tool,
    "get_host_info": get_host_info,
    "create_incident": create_incident_tool,
    "escalate": escalate_tool,
}


async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    func = TOOL_REGISTRY.get(tool_name)
    if func is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    try:
        return await func(**arguments)
    except Exception as e:
        logger.exception("Tool execution failed: %s", tool_name)
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})
