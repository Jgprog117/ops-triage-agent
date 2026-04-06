"""Alert listing and detail endpoints."""

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
    """List alerts with pagination and optional filtering."""
    alerts = await get_alerts_paginated(
        offset=offset, limit=limit,
        severity=severity, category=category,
    )
    # Parse raw_data JSON for each alert
    for a in alerts:
        if isinstance(a.get("raw_data"), str):
            a["raw_data"] = json.loads(a["raw_data"])
    return {"alerts": alerts, "offset": offset, "limit": limit}


@router.get("/{alert_id}")
async def get_alert(alert_id: str) -> dict:
    """Get a single alert with its triage history."""
    alert = await get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if isinstance(alert.get("raw_data"), str):
        alert["raw_data"] = json.loads(alert["raw_data"])

    triage_steps = get_triage_history(alert_id)
    return {"alert": alert, "triage_steps": triage_steps}
