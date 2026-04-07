"""Pydantic models and string enums shared across the application.

These types describe the canonical shape of alerts, incidents, escalations,
and host inventory rows. They are used by route handlers and the triage
agent for validation and serialization. Database access functions in
:mod:`backend.db.database` return raw dicts rather than these models for
historical reasons.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Alert severity levels emitted by the simulator."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    """High-level subsystem an alert belongs to."""

    THERMAL = "thermal"
    GPU = "gpu"
    NETWORK = "network"
    STORAGE = "storage"
    POWER = "power"
    MEMORY = "memory"


class TriageStatus(str, Enum):
    """Lifecycle states tracked on the ``alerts`` row during triage."""

    PENDING = "pending"
    TRIAGING = "triaging"
    TRIAGED = "triaged"
    ERROR = "error"


class Classification(str, Enum):
    """Final classification produced by the triage agent."""

    NOISE = "noise"
    ACKNOWLEDGED = "acknowledged"
    INCIDENT = "incident"
    CRITICAL_ESCALATION = "critical_escalation"


class IncidentSeverity(str, Enum):
    """Incident priority levels (PagerDuty-style P1..P4)."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IncidentStatus(str, Enum):
    """Lifecycle states for an incident record."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class HostStatus(str, Enum):
    """Operational status of a physical host."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


class Urgency(str, Enum):
    """Escalation urgency tied to on-call response SLAs."""

    IMMEDIATE = "immediate"
    WITHIN_1H = "within_1h"
    NEXT_BUSINESS_DAY = "next_business_day"


class Alert(BaseModel):
    """A single observability alert as produced by the simulator.

    Attributes:
        id: Unique alert id (UUID4 string).
        timestamp: When the alert was generated.
        severity: Alert severity level.
        category: Subsystem the alert belongs to.
        component: Specific component (e.g., ``GPU-3``, ``CRAC-Unit-2``).
        host: Hostname the alert was raised on.
        rack: Rack identifier (e.g., ``rack-12``).
        datacenter: Datacenter identifier. Defaults to ``dc-tokyo-01``.
        metric_name: Metric whose threshold was crossed.
        metric_value: Observed metric value.
        threshold: The threshold that triggered the alert.
        message: Human-readable description of the condition.
        raw_data: Free-form additional context attached by the producer.
        triage_status: Current position in the triage lifecycle.
    """

    id: str
    timestamp: datetime
    severity: Severity
    category: AlertCategory
    component: str
    host: str
    rack: str
    datacenter: str = "dc-tokyo-01"
    metric_name: str
    metric_value: float
    threshold: float
    message: str
    raw_data: dict[str, Any] = Field(default_factory=dict)
    triage_status: TriageStatus = TriageStatus.PENDING


class Incident(BaseModel):
    """A tracked operational incident, possibly correlating many alerts.

    Attributes:
        id: ``INC-XXXXXXXXXXXX`` style identifier.
        title: Short human-readable title.
        severity: Incident priority.
        summary: One-paragraph summary.
        root_cause: Free-form root-cause analysis.
        remediation_steps: Ordered list of remediation steps.
        correlated_alert_ids: All alert ids attached to this incident.
        assigned_team: Owning team name.
        status: Incident lifecycle state.
        created_at: Creation timestamp (set by the database).
        updated_at: Last-update timestamp (set by the database trigger).
    """

    id: str
    title: str
    severity: IncidentSeverity
    summary: str
    root_cause: str | None = None
    remediation_steps: list[str] = Field(default_factory=list)
    correlated_alert_ids: list[str] = Field(default_factory=list)
    assigned_team: str | None = None
    status: IncidentStatus = IncidentStatus.OPEN
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Escalation(BaseModel):
    """A page sent to the on-call team for an incident.

    Attributes:
        id: ``ESC-XXXXXXXXXXXX`` style identifier.
        incident_id: The incident this escalation is for.
        reason: Human-readable justification.
        urgency: Required response urgency.
        notification_channels: Channels used (e.g. ``slack``, ``pager``).
        created_at: Creation timestamp.
    """

    id: str
    incident_id: str
    reason: str
    urgency: Urgency
    notification_channels: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class Host(BaseModel):
    """A row from the host inventory.

    Attributes:
        hostname: Canonical hostname.
        rack: Rack the host is mounted in.
        datacenter: Datacenter identifier.
        gpu_type: GPU model string, or ``None`` for non-GPU hosts.
        gpu_count: Number of installed GPUs.
        cpu_type: CPU model string.
        memory_gb: Installed RAM in gigabytes.
        os: Operating system identifier.
        status: Current operational status.
        uptime_hours: Uptime in hours.
        last_incident_id: Most recent incident touching this host.
        metadata: Free-form metadata (kernel, drivers, IPMI IP, ...).
    """

    hostname: str
    rack: str
    datacenter: str = "dc-tokyo-01"
    gpu_type: str | None = None
    gpu_count: int | None = None
    cpu_type: str | None = None
    memory_gb: int | None = None
    os: str | None = None
    status: HostStatus = HostStatus.HEALTHY
    uptime_hours: float | None = None
    last_incident_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TriageResult(BaseModel):
    """Final structured output from the triage agent.

    Attributes:
        classification: One of the four agent classifications.
        root_cause_hypothesis: One-line root cause guess.
        correlated_alert_ids: Alert ids the agent considers correlated.
        remediation_steps: Suggested next actions.
        escalation_required: Whether the agent paged on-call.
        escalation_reason: Justification when ``escalation_required``.
        summary: English summary of the incident.
        summary_ja: Japanese translation of the summary.
    """

    classification: Classification
    root_cause_hypothesis: str
    correlated_alert_ids: list[str] = Field(default_factory=list)
    remediation_steps: list[str] = Field(default_factory=list)
    escalation_required: bool = False
    escalation_reason: str | None = None
    summary: str
    summary_ja: str


class KnowledgeQuery(BaseModel):
    """Request body for the ``/api/knowledge/ask`` endpoint.

    Attributes:
        query: Free-form natural-language question for the runbook RAG.
    """

    query: str


class KnowledgeAnswer(BaseModel):
    """Response body for the knowledge-base Q&A endpoint.

    Attributes:
        answer: The natural-language answer composed by the LLM.
        sources: Per-runbook citations referenced in the answer.
    """

    answer: str
    sources: list[dict[str, str]]


class AgentStep(BaseModel):
    """A single SSE step emitted by the triage agent for a given alert.

    Attributes:
        alert_id: The alert this step belongs to.
        step: Monotonically increasing step counter for the alert.
        type: One of ``tool_call``, ``tool_result``, ``final_triage``.
        tool_name: Tool name when ``type`` is a tool event.
        tool_input: Parsed tool arguments.
        tool_output: Tool result body (already truncated for transport).
        triage_result: Populated only for ``final_triage`` events.
        timestamp: When the step was produced.
    """

    alert_id: str
    step: int
    type: str  # tool_call | tool_result | final_triage
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: Any | None = None
    triage_result: TriageResult | None = None
    timestamp: datetime


class DashboardStats(BaseModel):
    """Aggregate counters surfaced by the ``/api/stats`` endpoint.

    Attributes:
        total_alerts: All alerts ever recorded.
        alerts_last_hour: Alerts recorded in the most recent hour.
        total_incidents: All incidents ever created.
        open_incidents: Incidents in ``open`` or ``investigating`` state.
        p1_open: Open incidents at ``P1`` severity.
        total_escalations: All escalations ever sent.
        uptime_seconds: Process uptime in seconds.
    """

    total_alerts: int = 0
    alerts_last_hour: int = 0
    total_incidents: int = 0
    open_incidents: int = 0
    p1_open: int = 0
    total_escalations: int = 0
    uptime_seconds: float = 0
