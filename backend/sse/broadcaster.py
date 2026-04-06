"""Server-Sent Events pub/sub broadcaster for alerts and agent steps.

Manages subscriber queues for two event channels:
- Alert stream: all new alerts broadcast to every connected client
- Triage stream: per-alert agent reasoning steps for live trace display
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Global subscriber sets
_alert_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
_triage_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

# Store completed triage steps so late-joining clients can catch up
_triage_history: dict[str, list[dict[str, Any]]] = {}


def subscribe_alerts() -> asyncio.Queue[dict[str, Any]]:
    """Register a new subscriber for the alert event stream."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _alert_subscribers.add(queue)
    logger.debug("Alert subscriber added (total: %d)", len(_alert_subscribers))
    return queue


def unsubscribe_alerts(queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Remove a subscriber from the alert event stream."""
    _alert_subscribers.discard(queue)
    logger.debug("Alert subscriber removed (total: %d)", len(_alert_subscribers))


async def broadcast_alert(alert_data: dict[str, Any]) -> None:
    """Send an alert event to all connected subscribers."""
    for queue in _alert_subscribers.copy():
        try:
            queue.put_nowait(alert_data)
        except asyncio.QueueFull:
            logger.warning("Alert subscriber queue full, dropping event")


def subscribe_triage(alert_id: str) -> asyncio.Queue[dict[str, Any]]:
    """Register a subscriber for triage steps of a specific alert.

    Returns existing history as initial events so the client sees
    steps that already completed before they connected.
    """
    if alert_id not in _triage_subscribers:
        _triage_subscribers[alert_id] = set()

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _triage_subscribers[alert_id].add(queue)

    # Replay history for this alert
    for step in _triage_history.get(alert_id, []):
        queue.put_nowait(step)

    logger.debug("Triage subscriber added for alert %s", alert_id)
    return queue


def unsubscribe_triage(alert_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Remove a subscriber from a specific alert's triage stream."""
    if alert_id in _triage_subscribers:
        _triage_subscribers[alert_id].discard(queue)
        if not _triage_subscribers[alert_id]:
            del _triage_subscribers[alert_id]


async def broadcast_triage_step(alert_id: str, step_data: dict[str, Any]) -> None:
    """Send a triage step event to subscribers watching a specific alert.

    Also stores the step in history for late-joining clients.
    """
    if alert_id not in _triage_history:
        _triage_history[alert_id] = []
    _triage_history[alert_id].append(step_data)

    # Also broadcast to alert stream as a triage update
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
    """Get all recorded triage steps for an alert."""
    return _triage_history.get(alert_id, [])


def cleanup_triage_history(max_alerts: int = 200) -> None:
    """Remove oldest triage history entries to prevent unbounded growth."""
    if len(_triage_history) > max_alerts:
        oldest_keys = sorted(_triage_history.keys())[:len(_triage_history) - max_alerts]
        for key in oldest_keys:
            del _triage_history[key]
