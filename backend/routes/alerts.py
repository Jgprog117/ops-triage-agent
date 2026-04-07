"""HTTP routes for listing and inspecting alerts."""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.db.database import get_alerts_paginated, get_alert_by_id
from backend.sse.broadcaster import get_triage_history

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    severity: Optional[str] = None,
    category: Optional[str] = None,
) -> dict:
    """Returns a paginated list of alerts.

    Args:
        offset: Number of rows to skip.
        limit: Maximum rows to return (1..200).
        severity: Optional severity filter.
        category: Optional category filter.

    Returns:
        A dict with ``alerts`` (the list, with parsed ``raw_data``),
        ``offset``, and ``limit``.
    """
    alerts = await get_alerts_paginated(
        offset=offset, limit=limit,
        severity=severity, category=category,
    )
    for a in alerts:
        if isinstance(a.get("raw_data"), str):
            a["raw_data"] = json.loads(a["raw_data"])
    return {"alerts": alerts, "offset": offset, "limit": limit}


@router.get("/{alert_id}")
async def get_alert(alert_id: str) -> dict:
    """Returns a single alert plus its retained triage step history.

    Args:
        alert_id: The id of the alert to fetch.

    Returns:
        A dict with ``alert`` (with parsed ``raw_data``) and
        ``triage_steps`` (the in-memory step history, possibly empty).

    Raises:
        HTTPException: 404 when no alert matches.
    """
    alert = await get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if isinstance(alert.get("raw_data"), str):
        alert["raw_data"] = json.loads(alert["raw_data"])

    triage_steps = get_triage_history(alert_id)
    return {"alert": alert, "triage_steps": triage_steps}
