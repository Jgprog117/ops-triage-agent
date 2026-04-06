"""Configuration read/update endpoints."""

from fastapi import APIRouter, Depends

from backend.auth import verify_api_key
from backend.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict:
    """Get current system configuration (public)."""
    return {
        "llm_model": settings.LLM_MODEL,
        "llm_api_base": settings.LLM_API_BASE,
        "alert_interval_min": settings.ALERT_INTERVAL_MIN,
        "alert_interval_max": settings.ALERT_INTERVAL_MAX,
        "scenario_probability": settings.SCENARIO_PROBABILITY,
    }


@router.post("")
async def update_config(
    updates: dict,
    _: str = Depends(verify_api_key),
) -> dict:
    """Update runtime configuration (requires API key)."""
    allowed_keys = {"ALERT_INTERVAL_MIN", "ALERT_INTERVAL_MAX", "SCENARIO_PROBABILITY"}
    applied = {}

    for key, value in updates.items():
        upper_key = key.upper()
        if upper_key in allowed_keys:
            setattr(settings, upper_key, value)
            applied[upper_key] = value

    return {"applied": applied, "message": f"Updated {len(applied)} setting(s)"}
