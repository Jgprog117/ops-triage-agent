from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import Settings, settings

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdate(BaseModel):
    ALERT_INTERVAL_MIN: Optional[int] = None
    ALERT_INTERVAL_MAX: Optional[int] = None
    SCENARIO_PROBABILITY: Optional[float] = None
    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None


@router.get("")
async def get_config() -> dict:
    return {
        "llm_model": settings.LLM_MODEL,
        "llm_api_base": settings.LLM_API_BASE,
        "alert_interval_min": settings.ALERT_INTERVAL_MIN,
        "alert_interval_max": settings.ALERT_INTERVAL_MAX,
        "scenario_probability": settings.SCENARIO_PROBABILITY,
    }


@router.post("")
async def update_config(
    updates: ConfigUpdate,
) -> dict:
    applied = {}
    for field_name, expected_type in Settings.UPDATABLE_FIELDS.items():
        value = getattr(updates, field_name, None)
        if value is not None:
            if not isinstance(value, expected_type):
                raise HTTPException(
                    status_code=422,
                    detail=f"{field_name} must be {expected_type.__name__}, got {type(value).__name__}",
                )
            setattr(settings, field_name, value)
            applied[field_name] = value

    return {"applied": applied, "message": f"Updated {len(applied)} setting(s)"}
