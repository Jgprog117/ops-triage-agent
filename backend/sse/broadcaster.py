import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_alert_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
_triage_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

_triage_history: dict[str, list[dict[str, Any]]] = {}


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
            logger.warning("Alert subscriber queue full, dropping event")


def subscribe_triage(alert_id: str) -> asyncio.Queue[dict[str, Any]]:
    """Replays history for late-joining clients, then streams new steps."""
    if alert_id not in _triage_subscribers:
        _triage_subscribers[alert_id] = set()

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
    _triage_subscribers[alert_id].add(queue)

    for step in _triage_history.get(alert_id, []):
        queue.put_nowait(step)

    logger.debug("Triage subscriber added for alert %s", alert_id)
    return queue


def unsubscribe_triage(alert_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
    if alert_id in _triage_subscribers:
        _triage_subscribers[alert_id].discard(queue)
        if not _triage_subscribers[alert_id]:
            del _triage_subscribers[alert_id]


async def broadcast_triage_step(alert_id: str, step_data: dict[str, Any]) -> None:
    if alert_id not in _triage_history:
        _triage_history[alert_id] = []
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
            logger.warning("Triage subscriber queue full for alert %s", alert_id)


def get_triage_history(alert_id: str) -> list[dict[str, Any]]:
    return _triage_history.get(alert_id, [])
