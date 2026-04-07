"""Integration tests for the dedupe-related DB functions added for #1/#18.

Each test uses a fresh on-disk SQLite file (so the WAL pragma is happy) and
exercises insert_alert, insert_incident, attach_alert_to_incident,
find_open_incidents_for_alert, and the open_incident_id field on
get_recent_alerts."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from backend.config import settings
from backend.db import database as db_module
from backend.db.database import (
    attach_alert_to_incident,
    close_database,
    find_open_incidents_for_alert,
    get_incident_by_id,
    get_recent_alerts,
    init_database,
    insert_alert,
    insert_incident,
    mark_incident_escalated,
)


@pytest_asyncio.fixture
async def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_ops.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
    # Make sure the module-level handle is fresh.
    db_module._db = None
    await init_database()
    yield
    await close_database()


def _alert(
    alert_id: str | None = None,
    rack: str = "rack-12",
    host: str = "node-gpu-rack12-01",
    category: str = "gpu",
    severity: str = "warning",
    message: str = "test alert",
) -> dict:
    return {
        "id": alert_id or f"ALT-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "severity": severity,
        "category": category,
        "component": "GPU-0",
        "host": host,
        "rack": rack,
        "datacenter": "dc-tokyo-01",
        "metric_name": "gpu_temperature_celsius",
        "metric_value": 91.0,
        "threshold": 85.0,
        "message": message,
        "raw_data": {},
        "triage_status": "pending",
    }


def _incident(
    incident_id: str,
    primary_alert_id: str,
    correlated: list[str] | None = None,
    status: str = "open",
    escalated: bool = False,
) -> dict:
    return {
        "id": incident_id,
        "title": f"Test incident for {primary_alert_id}",
        "severity": "P2",
        "summary": "test",
        "remediation_steps": [],
        "correlated_alert_ids": correlated or [primary_alert_id],
        "assigned_team": "dc-ops-tokyo",
        "status": status,
        "primary_alert_id": primary_alert_id,
        "escalated": escalated,
    }


@pytest.mark.asyncio
class TestAttachAlertToIncident:
    async def test_appends_alert_to_open_incident(self, fresh_db):
        primary = _alert("ALT-A")
        follow_up = _alert("ALT-B")
        await insert_alert(primary)
        await insert_alert(follow_up)
        await insert_incident(_incident("INC-1", primary_alert_id="ALT-A"))

        result = await attach_alert_to_incident("INC-1", "ALT-B")

        assert result is not None
        assert "ALT-A" in result["correlated_alert_ids"]
        assert "ALT-B" in result["correlated_alert_ids"]

    async def test_dedupes_already_attached_alert(self, fresh_db):
        primary = _alert("ALT-A")
        await insert_alert(primary)
        await insert_incident(_incident("INC-1", primary_alert_id="ALT-A"))

        await attach_alert_to_incident("INC-1", "ALT-A")
        # Second attach should be a no-op (idempotent).
        result = await attach_alert_to_incident("INC-1", "ALT-A")

        assert result["correlated_alert_ids"].count("ALT-A") == 1

    async def test_returns_none_for_missing_incident(self, fresh_db):
        result = await attach_alert_to_incident("INC-DOES-NOT-EXIST", "ALT-X")
        assert result is None

    async def test_refuses_to_attach_to_closed_incident(self, fresh_db):
        primary = _alert("ALT-A")
        await insert_alert(primary)
        await insert_incident(
            _incident("INC-1", primary_alert_id="ALT-A", status="resolved")
        )

        result = await attach_alert_to_incident("INC-1", "ALT-B")

        assert result is None


@pytest.mark.asyncio
class TestFindOpenIncidentsForAlert:
    async def test_matches_by_host(self, fresh_db):
        primary = _alert("ALT-A", host="node-gpu-rack12-01")
        await insert_alert(primary)
        await insert_incident(_incident("INC-1", primary_alert_id="ALT-A"))

        results = await find_open_incidents_for_alert(host="node-gpu-rack12-01")

        assert len(results) == 1
        assert results[0]["id"] == "INC-1"

    async def test_matches_by_rack(self, fresh_db):
        primary = _alert("ALT-A", rack="rack-14")
        await insert_alert(primary)
        await insert_incident(_incident("INC-1", primary_alert_id="ALT-A"))

        results = await find_open_incidents_for_alert(rack="rack-14")
        assert len(results) == 1

    async def test_skips_resolved_incidents(self, fresh_db):
        primary = _alert("ALT-A")
        await insert_alert(primary)
        await insert_incident(
            _incident("INC-1", primary_alert_id="ALT-A", status="resolved")
        )

        results = await find_open_incidents_for_alert(host=primary["host"])
        assert results == []

    async def test_skips_incidents_with_null_primary(self, fresh_db):
        # Legacy incidents created before the migration have NULL primary_alert_id.
        # They must not show up in dedupe lookups.
        legacy = _incident("INC-LEGACY", primary_alert_id="ALT-MISSING")
        legacy["primary_alert_id"] = None
        await insert_incident(legacy)

        results = await find_open_incidents_for_alert(rack="rack-12")
        assert results == []

    async def test_returns_empty_when_no_filters_supplied(self, fresh_db):
        primary = _alert("ALT-A")
        await insert_alert(primary)
        await insert_incident(_incident("INC-1", primary_alert_id="ALT-A"))

        results = await find_open_incidents_for_alert()
        assert results == []

    async def test_mark_incident_escalated_persists(self, fresh_db):
        primary = _alert("ALT-A")
        await insert_alert(primary)
        await insert_incident(_incident("INC-1", primary_alert_id="ALT-A"))

        await mark_incident_escalated("INC-1")
        inc = await get_incident_by_id("INC-1")

        assert inc is not None
        assert bool(inc["escalated"]) is True


@pytest.mark.asyncio
class TestGetRecentAlertsOpenIncidentLink:
    async def test_open_incident_id_is_set_when_attached(self, fresh_db):
        primary = _alert("ALT-A")
        follow_up = _alert("ALT-B")
        await insert_alert(primary)
        await insert_alert(follow_up)
        await insert_incident(
            _incident("INC-1", primary_alert_id="ALT-A", correlated=["ALT-A", "ALT-B"])
        )

        rows = await get_recent_alerts(host=primary["host"])

        by_id = {r["id"]: r for r in rows}
        assert by_id["ALT-A"]["open_incident_id"] == "INC-1"
        assert by_id["ALT-B"]["open_incident_id"] == "INC-1"

    async def test_open_incident_id_is_null_when_unattached(self, fresh_db):
        unrelated = _alert("ALT-Z")
        await insert_alert(unrelated)

        rows = await get_recent_alerts(host=unrelated["host"])
        assert rows[0]["open_incident_id"] is None

    async def test_resolved_incidents_dont_link(self, fresh_db):
        primary = _alert("ALT-A")
        await insert_alert(primary)
        await insert_incident(
            _incident("INC-1", primary_alert_id="ALT-A", status="resolved")
        )

        rows = await get_recent_alerts(host=primary["host"])
        assert rows[0]["open_incident_id"] is None

    async def test_exclude_id_filter(self, fresh_db):
        a = _alert("ALT-A")
        b = _alert("ALT-B")
        await insert_alert(a)
        await insert_alert(b)

        rows = await get_recent_alerts(rack="rack-12", exclude_id="ALT-A")
        ids = {r["id"] for r in rows}
        assert "ALT-A" not in ids
        assert "ALT-B" in ids
