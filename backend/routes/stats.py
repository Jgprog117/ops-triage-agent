import time

from fastapi import APIRouter

from backend.db.database import get_dashboard_stats

router = APIRouter(prefix="/api", tags=["stats"])

_start_time: float = 0.0


def set_start_time(t: float) -> None:
    global _start_time
    _start_time = t


@router.get("/stats")
async def dashboard_stats() -> dict:
    stats = await get_dashboard_stats()
    stats["uptime_seconds"] = round(time.time() - _start_time, 1)
    return stats
