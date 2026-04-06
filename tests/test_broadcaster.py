import asyncio
import time
from unittest.mock import patch

import pytest

from backend.sse.broadcaster import (
    _triage_history,
    _triage_timestamps,
    _alert_subscribers,
    subscribe_alerts,
    unsubscribe_alerts,
    broadcast_alert,
    subscribe_triage,
    unsubscribe_triage,
    broadcast_triage_step,
    get_triage_history,
    _evict_old_history,
)


@pytest.fixture(autouse=True)
def _clear_broadcaster_state():
    """Reset global broadcaster state between tests."""
    _triage_history.clear()
    _triage_timestamps.clear()
    _alert_subscribers.clear()
    yield
    _triage_history.clear()
    _triage_timestamps.clear()
    _alert_subscribers.clear()


class TestAlertSubscription:
    def test_subscribe_unsubscribe(self):
        q = subscribe_alerts()
        assert q in _alert_subscribers
        unsubscribe_alerts(q)
        assert q not in _alert_subscribers

    @pytest.mark.asyncio
    async def test_broadcast_reaches_subscriber(self):
        q = subscribe_alerts()
        await broadcast_alert({"type": "test"})
        msg = q.get_nowait()
        assert msg["type"] == "test"
        unsubscribe_alerts(q)

    @pytest.mark.asyncio
    async def test_queue_full_evicts_subscriber(self):
        q = asyncio.Queue(maxsize=1)
        _alert_subscribers.add(q)
        q.put_nowait({"type": "filler"})  # fill the queue

        await broadcast_alert({"type": "overflow"})
        # Slow subscriber should be evicted
        assert q not in _alert_subscribers


class TestTriageHistory:
    @pytest.mark.asyncio
    async def test_history_recorded(self):
        await broadcast_triage_step("alert-1", {"step": 1, "type": "tool_call"})
        history = get_triage_history("alert-1")
        assert len(history) == 1
        assert history[0]["step"] == 1

    @pytest.mark.asyncio
    async def test_ttl_eviction(self):
        _triage_history["old-alert"] = [{"step": 1}]
        _triage_timestamps["old-alert"] = time.monotonic() - 99999  # very old

        with patch("backend.sse.broadcaster.settings") as mock_settings:
            mock_settings.SSE_HISTORY_TTL_SECONDS = 3600
            mock_settings.SSE_HISTORY_MAX_ALERTS = 500
            _evict_old_history()

        assert "old-alert" not in _triage_history
        assert "old-alert" not in _triage_timestamps

    @pytest.mark.asyncio
    async def test_max_size_eviction(self):
        # Fill with more than max
        for i in range(10):
            _triage_history[f"alert-{i}"] = [{"step": 1}]
            _triage_timestamps[f"alert-{i}"] = time.monotonic()

        with patch("backend.sse.broadcaster.settings") as mock_settings:
            mock_settings.SSE_HISTORY_TTL_SECONDS = 99999
            mock_settings.SSE_HISTORY_MAX_ALERTS = 5
            _evict_old_history()

        assert len(_triage_history) <= 5


class TestTriageSubscription:
    @pytest.mark.asyncio
    async def test_late_subscriber_gets_replay(self):
        # Add history first
        _triage_history["alert-1"] = [
            {"step": i, "type": "tool_call"} for i in range(5)
        ]

        q = subscribe_triage("alert-1")
        # Should get all 5 steps (under replay cap of 20)
        count = 0
        while not q.empty():
            q.get_nowait()
            count += 1
        assert count == 5
        unsubscribe_triage("alert-1", q)

    @pytest.mark.asyncio
    async def test_completed_triage_replays_only_final(self):
        _triage_history["alert-2"] = [
            {"step": 1, "type": "tool_call"},
            {"step": 2, "type": "tool_result"},
            {"step": 3, "type": "final_triage"},
        ]

        q = subscribe_triage("alert-2")
        count = 0
        last = None
        while not q.empty():
            last = q.get_nowait()
            count += 1
        assert count == 1
        assert last["type"] == "final_triage"
        unsubscribe_triage("alert-2", q)

    @pytest.mark.asyncio
    async def test_replay_capped_at_20(self):
        _triage_history["alert-3"] = [
            {"step": i, "type": "tool_call"} for i in range(30)
        ]

        q = subscribe_triage("alert-3")
        count = 0
        while not q.empty():
            q.get_nowait()
            count += 1
        assert count == 20
        unsubscribe_triage("alert-3", q)
