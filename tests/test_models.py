import pytest
from datetime import datetime
from pydantic import ValidationError
from backend.db.models import (
    Alert,
    AlertCategory,
    Classification,
    Host,
    Incident,
    IncidentStatus,
    Severity,
    TriageResult,
    TriageStatus,
)


def _make_alert(**overrides):
    defaults = dict(
        id="test-1",
        timestamp=datetime.now(),
        severity="warning",
        category="gpu",
        component="GPU-0",
        host="gpu-node-01",
        rack="rack-12",
        metric_name="gpu_temperature_celsius",
        metric_value=91.0,
        threshold=85.0,
        message="GPU hot",
    )
    defaults.update(overrides)
    return Alert(**defaults)


class TestAlert:
    def test_valid(self):
        alert = _make_alert()
        assert alert.severity == Severity.WARNING
        assert alert.category == AlertCategory.GPU
        assert alert.triage_status == TriageStatus.PENDING

    def test_invalid_severity(self):
        with pytest.raises(ValidationError):
            _make_alert(severity="bogus")

    def test_invalid_category(self):
        with pytest.raises(ValidationError):
            _make_alert(category="bogus")


class TestTriageResult:
    def test_valid(self):
        tr = TriageResult(
            classification="incident",
            root_cause_hypothesis="overheating",
            summary="GPU failure",
            summary_ja="GPU障害",
        )
        assert tr.classification == Classification.INCIDENT
        assert tr.escalation_required is False
        assert tr.correlated_alert_ids == []

    def test_invalid_classification(self):
        with pytest.raises(ValidationError):
            TriageResult(
                classification="bogus",
                root_cause_hypothesis="x",
                summary="s",
                summary_ja="s",
            )


class TestIncident:
    def test_valid_with_defaults(self):
        inc = Incident(
            id="INC-001",
            title="GPU failure",
            severity="P2",
            summary="GPU went down",
        )
        assert inc.status == IncidentStatus.OPEN
        assert inc.remediation_steps == []
        assert inc.correlated_alert_ids == []

    def test_invalid_severity(self):
        with pytest.raises(ValidationError):
            Incident(id="INC-001", title="x", severity="P9", summary="x")

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            Incident(id="INC-001", title="x", severity="P1", summary="x", status="bogus")


class TestHost:
    def test_defaults(self):
        host = Host(hostname="gpu-node-01", rack="rack-12")
        assert host.status == "healthy"
        assert host.datacenter == "dc-tokyo-01"
        assert host.metadata == {}
