import os
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set env vars before any backend imports
os.environ.setdefault("LLM_API_KEY", "test-key-valid")
os.environ.setdefault("OPS_AGENT_API_KEY", "test-api-key")


@pytest.fixture
def sample_alert():
    """Factory for well-formed alert dicts."""
    def _make(**overrides):
        alert = {
            "id": f"ALT-{uuid.uuid4().hex[:8]}",
            "timestamp": "2026-04-06T12:00:00",
            "severity": "warning",
            "category": "gpu",
            "component": "gpu-0",
            "host": "gpu-node-01",
            "rack": "rack-12",
            "datacenter": "dc-tokyo-01",
            "metric_name": "gpu_temperature_celsius",
            "metric_value": 88.5,
            "threshold": 85.0,
            "message": "GPU temperature above warning threshold",
            "raw_data": {},
        }
        alert.update(overrides)
        return alert
    return _make


@pytest.fixture
def mock_llm_response():
    """Factory for mock LLM response dicts."""
    def _make(content="hello", tool_calls=None):
        message = {"role": "assistant", "content": content}
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        return {"choices": [{"message": message, "finish_reason": "stop"}]}
    return _make
