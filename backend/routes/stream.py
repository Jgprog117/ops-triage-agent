"""Server-Sent Events routes for the live dashboard.

Two streams are exposed:

* ``GET /api/stream/alerts`` — every event from the global alert feed.
* ``GET /api/stream/triage/{alert_id}`` — the per-alert triage step
  feed, which closes itself once the agent emits its final triage
  result.

Both endpoints send periodic ping comments to keep idle connections
from being reaped by intermediate proxies.
"""

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.sse.broadcaster import (
    subscribe_alerts,
    subscribe_triage,
    unsubscribe_alerts,
    unsubscribe_triage,
)

router = APIRouter(prefix="/api/stream", tags=["streaming"])


@router.get("/alerts")
async def stream_alerts(request: Request) -> EventSourceResponse:
    """Streams the global alert feed as Server-Sent Events.

    Subscribes the caller to the broadcaster, forwards every event as a
    ``message`` SSE event, and emits a ``ping`` event every 30 seconds
    of idle time so proxies do not close the connection. Disconnects
    are detected on each iteration via :meth:`Request.is_disconnected`.

    Args:
        request: The incoming SSE request.

    Returns:
        An :class:`EventSourceResponse` that drains the broadcaster
        until the client disconnects.
    """
    queue = subscribe_alerts()

    async def event_generator() -> AsyncIterator[dict]:
        """Yields broadcaster events as SSE message dicts."""
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"event": "message", "data": json.dumps(data)}
                except asyncio.TimeoutError:
                    # Send keepalive to prevent connection timeout
                    yield {"event": "ping", "data": ""}
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_alerts(queue)

    return EventSourceResponse(event_generator())


@router.get("/triage/{alert_id}")
async def stream_triage(alert_id: str, request: Request) -> EventSourceResponse:
    """Streams the per-alert triage step feed for one alert.

    The stream replays any retained history (or just the final result if
    triage already completed) and then forwards new steps as they
    arrive. Closes automatically once a ``final_triage`` event is sent.

    Args:
        alert_id: The id of the alert to stream.
        request: The incoming SSE request.

    Returns:
        An :class:`EventSourceResponse` that closes when triage finishes
        or the client disconnects.
    """
    queue = subscribe_triage(alert_id)

    async def event_generator() -> AsyncIterator[dict]:
        """Yields triage steps as SSE message dicts; stops on final_triage."""
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"event": "message", "data": json.dumps(data)}
                    # If this was a final triage result, close the stream
                    if data.get("type") == "final_triage":
                        break
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_triage(alert_id, queue)

    return EventSourceResponse(event_generator())
