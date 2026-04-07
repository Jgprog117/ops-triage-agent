"""Tool implementations exposed to the triage LLM.

Each public function in this module is registered in :data:`TOOL_REGISTRY`
and surfaced to the LLM via the schemas in :mod:`backend.agent.prompts`.
Tools return JSON-serialized strings — the LLM treats them as opaque text,
but the structure matters because the model is prompted to look for fields
like ``open_incident_id`` and ``already_escalated``.

A deliberate dedupe contract is enforced across these tools: alerts already
attached to an open incident must be re-attached rather than duplicated, and
escalations refuse to fire twice on the same incident.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import random
import uuid
from typing import Any

import aiosqlite
import httpx

from backend.config import settings
from backend.db.database import (
    attach_alert_to_incident,
    find_open_incidents_for_alert,
    get_host,
    get_recent_alerts,
    insert_escalation,
    insert_incident,
    insert_audit_log,
    insert_webhook_dlq,
    mark_incident_escalated,
)
from backend.knowledge.rag import search_runbooks as kb_search

logger = logging.getLogger(__name__)


async def query_recent_alerts(
    minutes_ago: int = 15,
    rack: str | None = None,
    host: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    exclude_id: str | None = None,
) -> str:
    """Returns recent alerts matching the given filters as a JSON string.

    The returned payload includes a ``count`` and an ``alerts`` array; each
    alert carries an ``open_incident_id`` field. When any alert is already
    attached to an open incident, the response also includes
    ``distinct_open_incidents`` and a ``dedupe_hint`` instructing the agent
    to attach instead of duplicating.

    Args:
        minutes_ago: Lookback window in minutes.
        rack: Optional rack filter (e.g., ``rack-12``).
        host: Optional hostname filter.
        category: Optional alert category filter.
        severity: Optional severity filter (``info``, ``warning``,
            ``critical``).
        exclude_id: Optional alert id to omit from results, typically the
            id of the alert currently being triaged.

    Returns:
        A JSON-encoded string with the query results, suitable for direct
        inclusion in a tool-result message.
    """
    alerts = await get_recent_alerts(
        minutes_ago=minutes_ago,
        rack=rack,
        host=host,
        category=category,
        severity=severity,
        limit=settings.ALERT_QUERY_LIMIT,
        exclude_id=exclude_id,
    )

    if not alerts:
        return json.dumps({"count": 0, "alerts": [], "message": "No matching alerts found"})

    summary = []
    open_incident_ids: set[str] = set()
    for a in alerts:
        open_inc = a.get("open_incident_id")
        if open_inc:
            open_incident_ids.add(open_inc)
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
            "open_incident_id": open_inc,
        })

    payload = {"count": len(summary), "alerts": summary}
    if open_incident_ids:
        payload["distinct_open_incidents"] = sorted(open_incident_ids)
        payload["dedupe_hint"] = (
            "One or more of these alerts is already attached to an open incident. "
            "Call find_open_incidents to inspect, then attach_to_incident instead "
            "of creating a duplicate."
        )
    return json.dumps(payload, indent=2)


async def search_runbooks_tool(query: str) -> str:
    """Performs a semantic search over the runbook knowledge base.

    Runs the synchronous Chroma query inside a default executor so the
    event loop is not blocked.

    Args:
        query: Free-form natural-language query describing the issue.

    Returns:
        A JSON-encoded string containing the top 3 chunks (each with
        ``source``, ``section``, ``content``, and ``relevance``), or a
        message payload when no chunks are returned.
    """
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
    """Returns hardware and operational metadata for a host.

    Args:
        host: Hostname to look up in the host inventory.

    Returns:
        A JSON-encoded string with hardware specs (CPU, GPU, memory),
        rack/datacenter location, current status, uptime, and the most
        recent incident id. When the host is unknown, returns a JSON
        payload with an ``error`` field instead.
    """
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


async def find_open_incidents(
    rack: str | None = None,
    host: str | None = None,
    category: str | None = None,
    minutes_ago: int = 60,
) -> str:
    """Looks up open incidents whose primary alert matches the filters.

    The agent must call this before :func:`create_incident_tool` to avoid
    creating duplicate incidents for the same scenario.

    Args:
        rack: Optional rack filter.
        host: Optional hostname filter.
        category: Optional alert category filter.
        minutes_ago: How far back to search, in minutes.

    Returns:
        A JSON-encoded string with a ``count`` and an ``incidents`` array.
        When matches exist, the response includes a directive to use
        :func:`attach_to_incident_tool` instead of creating a duplicate.
    """
    incidents = await find_open_incidents_for_alert(
        rack=rack, host=host, category=category, minutes_ago=minutes_ago,
    )
    if not incidents:
        return json.dumps({
            "count": 0,
            "incidents": [],
            "message": (
                "No open incidents match. Safe to create_incident if "
                "this alert warrants tracking."
            ),
        })

    summary = []
    for inc in incidents:
        summary.append({
            "incident_id": inc["id"],
            "title": inc["title"],
            "severity": inc["severity"],
            "status": inc["status"],
            "primary_alert_id": inc.get("primary_alert_id"),
            "correlated_alert_ids": inc.get("correlated_alert_ids", []),
            "escalated": bool(inc.get("escalated")),
            "created_at": inc.get("created_at"),
            "assigned_team": inc.get("assigned_team"),
        })
    return json.dumps({
        "count": len(summary),
        "incidents": summary,
        "message": (
            "One or more open incidents already cover this scenario. "
            "Call attach_to_incident with the matching incident_id rather than "
            "creating a duplicate. Reuse the existing severity and escalation "
            "status — do NOT re-escalate an already-escalated incident."
        ),
    }, indent=2)


async def attach_to_incident_tool(incident_id: str, alert_id: str) -> str:
    """Attaches an alert to an existing open incident.

    Persists the relationship in the database and writes an audit-log
    entry. Reuses the incident's existing escalation status — the agent
    must NOT call :func:`escalate_tool` after attaching.

    Args:
        incident_id: The id of the open incident to attach to.
        alert_id: The id of the alert being triaged.

    Returns:
        A JSON-encoded string confirming the attachment, including the
        updated correlated alert list and the incident's escalation flag,
        or an ``error`` payload when the incident cannot be found or is
        not in an open state.
    """
    updated = await attach_alert_to_incident(incident_id, alert_id)
    if updated is None:
        return json.dumps({
            "error": (
                f"Incident '{incident_id}' not found or not open. "
                "Either the id is wrong or the incident has been closed — "
                "fall back to create_incident if appropriate."
            ),
        })
    await insert_audit_log("alert_attached_to_incident", alert_id, {
        "incident_id": incident_id,
    })
    logger.info("Alert %s attached to incident %s", alert_id, incident_id)
    return json.dumps({
        "incident_id": incident_id,
        "alert_id": alert_id,
        "correlated_alert_ids": updated.get("correlated_alert_ids", []),
        "already_escalated": bool(updated.get("escalated")),
        "message": (
            f"Alert attached to {incident_id}. Do NOT create a new incident "
            "or re-escalate this alert."
        ),
    })


async def create_incident_tool(
    title: str,
    severity: str,
    summary: str,
    root_cause: str | None = None,
    remediation_steps: list[str] | None = None,
    correlated_alert_ids: list[str] | None = None,
    assigned_team: str | None = None,
    primary_alert_id: str | None = None,
) -> str:
    """Creates a new incident record and writes an audit-log entry.

    Generates a fresh ``INC-XXXXXXXXXXXX`` id, persists the incident, and
    returns the canonical metadata to the agent. The caller must have
    confirmed via :func:`find_open_incidents` that no matching open
    incident already exists; this tool does not check for duplicates.

    Args:
        title: Short human-readable incident title.
        severity: Incident severity (``P1``..``P4``).
        summary: One-paragraph incident summary.
        root_cause: Optional root-cause analysis text.
        remediation_steps: Optional list of remediation steps in order.
        correlated_alert_ids: Optional list of correlated alert ids.
        assigned_team: Optional team name. Defaults to
            :attr:`Settings.DEFAULT_TEAM`.
        primary_alert_id: The id of the alert being triaged. Becomes the
            canonical link for future dedupe lookups. If omitted, falls
            back to the first entry in ``correlated_alert_ids``.

    Returns:
        A JSON-encoded string with the new ``incident_id``, ``severity``,
        ``status``, ``assigned_team``, and a confirmation message.
    """
    incident_id = f"INC-{uuid.uuid4().hex[:12].upper()}"
    correlated = correlated_alert_ids or []
    primary = primary_alert_id or (correlated[0] if correlated else None)

    incident = {
        "id": incident_id,
        "title": title,
        "severity": severity,
        "summary": summary,
        "root_cause": root_cause,
        "remediation_steps": remediation_steps or [],
        "correlated_alert_ids": correlated,
        "assigned_team": assigned_team or settings.DEFAULT_TEAM,
        "status": "open",
        "primary_alert_id": primary,
        "escalated": False,
    }

    await insert_incident(incident)
    await insert_audit_log("incident_created", incident_id, {
        "title": title,
        "severity": severity,
        "assigned_team": incident["assigned_team"],
        "primary_alert_id": primary,
    })

    logger.info("Incident created: %s — %s (%s)", incident_id, title, severity)

    return json.dumps({
        "incident_id": incident_id,
        "title": title,
        "severity": severity,
        "status": "open",
        "assigned_team": incident["assigned_team"],
        "primary_alert_id": primary,
        "message": f"Incident {incident_id} created successfully",
    })


async def escalate_tool(
    incident_id: str,
    reason: str,
    urgency: str,
    notification_channels: list[str] | None = None,
) -> str:
    """Pages the on-call team for an incident.

    Refuses to escalate twice on the same incident — if the incident's
    ``escalated`` flag is already set, this returns an
    ``already_escalated`` payload without contacting any channel. On a
    fresh escalation, an escalation row is inserted, the incident is
    marked escalated, an audit log is written, and the configured webhook
    is invoked with HMAC-signed payload and retry/DLQ semantics.

    Args:
        incident_id: The id of the incident to escalate.
        reason: Human-readable justification for paging.
        urgency: One of ``immediate``, ``within_1h``, or
            ``next_business_day``.
        notification_channels: Optional list of channel names. Defaults
            to ``["slack", "pager"]``.

    Returns:
        A JSON-encoded string with the new ``escalation_id``,
        ``incident_id``, the requested ``urgency`` and channels, and the
        webhook delivery status. When the incident was already escalated,
        the response carries ``already_escalated: true`` instead.
    """
    # Refuse to double-escalate. The agent should reuse the existing escalation.
    from backend.db.database import get_incident_by_id
    inc = await get_incident_by_id(incident_id)
    if inc is None:
        return json.dumps({
            "error": f"Incident '{incident_id}' not found — cannot escalate.",
        })
    if inc.get("escalated"):
        return json.dumps({
            "incident_id": incident_id,
            "already_escalated": True,
            "message": (
                f"Incident {incident_id} is already escalated. "
                "Do NOT call escalate again — the on-call team has been notified."
            ),
        })

    escalation_id = f"ESC-{uuid.uuid4().hex[:12].upper()}"
    channels = notification_channels or ["slack", "pager"]

    escalation = {
        "id": escalation_id,
        "incident_id": incident_id,
        "reason": reason,
        "urgency": urgency,
        "notification_channels": channels,
    }

    await insert_escalation(escalation)
    await mark_incident_escalated(incident_id)
    await insert_audit_log("escalation_sent", escalation_id, {
        "incident_id": incident_id,
        "urgency": urgency,
        "channels": channels,
    })

    logger.info("Escalation %s sent for incident %s (urgency: %s)",
                escalation_id, incident_id, urgency)

    webhook_status = "no_webhook_configured"
    if settings.WEBHOOK_URL:
        webhook_status = await _send_webhook_with_retry(escalation)

    return json.dumps({
        "escalation_id": escalation_id,
        "incident_id": incident_id,
        "urgency": urgency,
        "notification_channels": channels,
        "webhook_status": webhook_status,
        "message": f"Escalation {escalation_id} sent via {', '.join(channels)}",
    })


async def _send_webhook_with_retry(payload: dict) -> str:
    """Sends an escalation payload to the configured webhook.

    Signs the body with HMAC-SHA256 when ``WEBHOOK_SECRET`` is set, retries
    failures with exponential backoff up to ``WEBHOOK_MAX_RETRIES`` attempts,
    and persists the payload to the ``webhook_dlq`` table when all attempts
    are exhausted.

    Args:
        payload: A JSON-serializable dict describing the escalation.

    Returns:
        ``"delivered"`` on success, ``"failed"`` after exhausting retries.
    """
    body = json.dumps(payload)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.WEBHOOK_SECRET:
        sig = hmac.new(settings.WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        headers["X-Signature-SHA256"] = sig

    max_retries = settings.WEBHOOK_MAX_RETRIES
    last_error = ""

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(settings.WEBHOOK_URL, content=body, headers=headers)
                resp.raise_for_status()
                logger.info("Webhook delivered: %d", resp.status_code)
                return "delivered"
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                delay = min(2 ** attempt, 10) + random.uniform(0, 1)
                logger.warning("Webhook attempt %d/%d failed: %s, retrying in %.1fs",
                               attempt + 1, max_retries, last_error, delay)
                await asyncio.sleep(delay)

    # All retries exhausted — write to dead-letter queue
    logger.error("Webhook delivery failed after %d attempts: %s", max_retries, last_error)
    try:
        await insert_webhook_dlq(body, last_error, max_retries)
    except Exception:
        logger.exception("Failed to write to webhook DLQ")

    return "failed"


TOOL_REGISTRY: dict[str, Any] = {
    "query_recent_alerts": query_recent_alerts,
    "search_runbooks": search_runbooks_tool,
    "get_host_info": get_host_info,
    "find_open_incidents": find_open_incidents,
    "create_incident": create_incident_tool,
    "attach_to_incident": attach_to_incident_tool,
    "escalate": escalate_tool,
}


async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Dispatches an LLM tool call to its registered handler.

    Centralizes exception handling so each tool function can throw
    naturally and let this wrapper produce a consistent JSON error
    payload. Errors are tagged with a ``severity`` field of either
    ``transient`` (worth retrying) or ``fatal`` (do not retry).

    Args:
        tool_name: The function name as referenced by the LLM. Must be
            present in :data:`TOOL_REGISTRY`.
        arguments: Already-parsed keyword arguments for the tool.

    Returns:
        The tool's JSON-encoded result string, or a JSON ``error`` payload
        when the tool raises an unhandled exception.
    """
    func = TOOL_REGISTRY.get(tool_name)
    if func is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    try:
        return await func(**arguments)
    except aiosqlite.Error as e:
        logger.exception("Database error in tool %s", tool_name)
        return json.dumps({"error": f"Database error: {e}", "severity": "fatal"})
    except httpx.HTTPStatusError as e:
        logger.exception("HTTP error in tool %s", tool_name)
        severity = "transient" if e.response.status_code >= 500 else "fatal"
        return json.dumps({"error": f"HTTP error {e.response.status_code}", "severity": severity})
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.exception("Data error in tool %s", tool_name)
        return json.dumps({"error": f"Data error: {e}", "severity": "fatal"})
    except Exception as e:
        logger.exception("Tool execution failed: %s", tool_name)
        return json.dumps({"error": f"Tool execution failed: {str(e)}", "severity": "transient"})
