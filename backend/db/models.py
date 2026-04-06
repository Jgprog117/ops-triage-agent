from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    THERMAL = "thermal"
    GPU = "gpu"
    NETWORK = "network"
    STORAGE = "storage"
    POWER = "power"
    MEMORY = "memory"


class TriageStatus(str, Enum):
    PENDING = "pending"
    TRIAGING = "triaging"
    TRIAGED = "triaged"
    ERROR = "error"


class Classification(str, Enum):
    NOISE = "noise"
    ACKNOWLEDGED = "acknowledged"
    INCIDENT = "incident"
    CRITICAL_ESCALATION = "critical_escalation"


class IncidentSeverity(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class HostStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


class Urgency(str, Enum):
    IMMEDIATE = "immediate"
    WITHIN_1H = "within_1h"
    NEXT_BUSINESS_DAY = "next_business_day"


class Alert(BaseModel):
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
    id: str
    incident_id: str
    reason: str
    urgency: Urgency
    notification_channels: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class Host(BaseModel):
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
    classification: Classification
    root_cause_hypothesis: str
    correlated_alert_ids: list[str] = Field(default_factory=list)
    remediation_steps: list[str] = Field(default_factory=list)
    escalation_required: bool = False
    escalation_reason: str | None = None
    summary: str
    summary_ja: str


class KnowledgeQuery(BaseModel):
    query: str


class KnowledgeAnswer(BaseModel):
    answer: str
    sources: list[dict[str, str]]


class AgentStep(BaseModel):
    alert_id: str
    step: int
    type: str  # tool_call | tool_result | final_triage
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: Any | None = None
    triage_result: TriageResult | None = None
    timestamp: datetime


class DashboardStats(BaseModel):
    total_alerts: int = 0
    alerts_last_hour: int = 0
    total_incidents: int = 0
    open_incidents: int = 0
    p1_open: int = 0
    total_escalations: int = 0
    uptime_seconds: float = 0
