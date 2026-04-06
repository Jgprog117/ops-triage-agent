import asyncio
import logging
import time
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

_alert_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
_triage_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

_triage_history: dict[str, list[dict[str, Any]]] = {}
_triage_timestamps: dict[str, float] = {}  # alert_id -> first insertion time


def _evict_old_history() -> None:
    """Remove old triage histories by TTL and max size."""
    now = time.monotonic()
    ttl = settings.SSE_HISTORY_TTL_SECONDS
    max_alerts = settings.SSE_HISTORY_MAX_ALERTS

    # Evict by TTL
    expired = [
        aid for aid, ts in _triage_timestamps.items()
        if now - ts > ttl
    ]
    for aid in expired:
        _triage_history.pop(aid, None)
        _triage_timestamps.pop(aid, None)

    # Evict by size (oldest first — dict preserves insertion order)
    while len(_triage_history) > max_alerts:
        oldest_id = next(iter(_triage_history))
        del _triage_history[oldest_id]
        _triage_timestamps.pop(oldest_id, None)


def subscribe_alerts() -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
    _alert_subscribers.add(queue)
    logger.debug("Alert subscriber added (total: %d)", len(_alert_subscribers))
    return queue


def unsubscribe_alerts(queue: asyncio.Queue[dict[str, Any]]) -> None:
    _alert_subscribers.discard(queue)
    logger.debug("Alert subscriber removed (total: %d)", len(_alert_subscribers))


async def broadcast_alert(alert_data: dict[str, Any]) -> None:
    for queue in _alert_subscribers.copy():
        try:
            queue.put_nowait(alert_data)
        except asyncio.QueueFull:
            logger.warning("Alert subscriber queue full — evicting slow client (total: %d)", len(_alert_subscribers))
            _alert_subscribers.discard(queue)


def subscribe_triage(alert_id: str) -> asyncio.Queue[dict[str, Any]]:
    """Replays history for late-joining clients, then streams new steps."""
    if alert_id not in _triage_subscribers:
        _triage_subscribers[alert_id] = set()

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
    _triage_subscribers[alert_id].add(queue)

    # Replay history — cap to last 20 steps, or just final if complete
    history = _triage_history.get(alert_id, [])
    if history and history[-1].get("type") == "final_triage":
        # Triage is done — just send the final result
        queue.put_nowait(history[-1])
    else:
        for step in history[-20:]:
            queue.put_nowait(step)

    logger.debug("Triage subscriber added for alert %s", alert_id)
    return queue


def unsubscribe_triage(alert_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
    if alert_id in _triage_subscribers:
        _triage_subscribers[alert_id].discard(queue)
        if not _triage_subscribers[alert_id]:
            del _triage_subscribers[alert_id]


async def broadcast_triage_step(alert_id: str, step_data: dict[str, Any]) -> None:
    # Evict old entries before adding new ones
    _evict_old_history()

    if alert_id not in _triage_history:
        _triage_history[alert_id] = []
        _triage_timestamps[alert_id] = time.monotonic()
    _triage_history[alert_id].append(step_data)

    triage_update = {
        "type": "triage_update",
        "alert_id": alert_id,
        "step": step_data,
    }
    await broadcast_alert(triage_update)

    subscribers = _triage_subscribers.get(alert_id, set())
    for queue in subscribers.copy():
        try:
            queue.put_nowait(step_data)
        except asyncio.QueueFull:
            logger.warning("Triage subscriber queue full for alert %s — evicting", alert_id)
            subscribers.discard(queue)


def get_triage_history(alert_id: str) -> list[dict[str, Any]]:
    return _triage_history.get(alert_id, [])
