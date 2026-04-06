"""SSE streaming endpoints for live alert feed and triage traces."""

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.sse.broadcaster import (
    subscribe_alerts,
    subscribe_triage,
    unsubscribe_alerts,
    unsubscribe_triage,
    get_triage_history,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stream", tags=["streaming"])


@router.get("/alerts")
async def stream_alerts(request: Request) -> EventSourceResponse:
    """SSE endpoint for the live alert feed.

    Streams new alerts and triage updates to connected frontend clients.
    """
    queue = subscribe_alerts()

    async def event_generator():
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
    """SSE endpoint for agent triage steps of a specific alert.

    Replays historical steps for late-joining clients, then streams
    new steps as they arrive.
    """
    queue = subscribe_triage(alert_id)

    async def event_generator():
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
