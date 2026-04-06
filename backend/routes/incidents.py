from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.db.database import get_incidents, get_incident_by_id, get_escalations

router = APIRouter(prefix="/api", tags=["incidents"])


@router.get("/incidents")
async def list_incidents(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    incidents = await get_incidents(status=status, limit=limit)
    return {"incidents": incidents}


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str) -> dict:
    incident = await get_incident_by_id(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"incident": incident}


@router.get("/escalations")
async def list_escalations(
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    escalations = await get_escalations(limit=limit)
    return {"escalations": escalations}
