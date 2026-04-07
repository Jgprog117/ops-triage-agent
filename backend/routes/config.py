"""HTTP routes for reading and updating the runtime-mutable settings."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import Settings, settings

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdate(BaseModel):
    """Request body for ``POST /api/config``.

    All fields are optional; only fields present in the request body are
    applied. The set of allowed fields mirrors
    :attr:`Settings.UPDATABLE_FIELDS`.

    Attributes:
        ALERT_INTERVAL_MIN: Minimum seconds between simulated alerts.
        ALERT_INTERVAL_MAX: Maximum seconds between simulated alerts.
        SCENARIO_PROBABILITY: Probability (0-1) of running a scenario.
        WEBHOOK_URL: Outbound escalation webhook URL.
        WEBHOOK_SECRET: HMAC-SHA256 secret used to sign webhook bodies.
    """

    ALERT_INTERVAL_MIN: Optional[int] = None
    ALERT_INTERVAL_MAX: Optional[int] = None
    SCENARIO_PROBABILITY: Optional[float] = None
    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None


@router.get("")
async def get_config() -> dict:
    """Returns the subset of settings exposed to the dashboard.

    Returns:
        A dict with the LLM model and base URL plus the simulator
        pacing/probability values.
    """
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
    """Applies a subset of runtime-mutable settings.

    Iterates over the whitelist in :attr:`Settings.UPDATABLE_FIELDS`,
    type-checks each provided value against the declared expected type,
    and writes accepted values onto the global :data:`settings` instance
    so subsequent reads see the new value.

    Args:
        updates: A :class:`ConfigUpdate` body. Fields left as ``None``
            are ignored.

    Returns:
        A dict with the ``applied`` map and a human-readable ``message``.

    Raises:
        HTTPException: 422 when a provided value has the wrong type.
    """
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
