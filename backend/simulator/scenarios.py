"""Multi-step failure scenarios used by the alert simulator.

Each scenario function returns a fresh :class:`Scenario` describing a
realistic correlated failure pattern (thermal cascade, GPU hardware
failure, network partition, storage degradation, power anomaly). The
simulator picks one at random with probability
:attr:`Settings.SCENARIO_PROBABILITY` and emits its alerts on the
configured per-step delays.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from backend.simulator.components import RACK_HOSTS, RACKS


@dataclass
class ScenarioAlert:
    """A single alert step within a multi-step scenario.

    Attributes:
        delay_seconds: How long to wait after the previous step before
            emitting this alert. Ignored for the first step.
        severity: Alert severity (``info``, ``warning``, ``critical``).
        category: Alert category (e.g., ``thermal``).
        component: Specific component name.
        host: Hostname the alert is raised on.
        rack: Rack identifier.
        metric_name: Metric whose threshold was crossed.
        metric_value: The observed value to report.
        threshold: The threshold the value crossed.
        message: Human-readable alert message.
        raw_data: Free-form additional context.
    """

    delay_seconds: float
    severity: str
    category: str
    component: str
    host: str
    rack: str
    metric_name: str
    metric_value: float
    threshold: float
    message: str
    raw_data: dict = field(default_factory=dict)


@dataclass
class Scenario:
    """A named multi-step failure pattern.

    Attributes:
        name: Stable identifier (used in audit logs and scenario stats).
        description: Human-readable summary of the pattern.
        alerts: Ordered list of alert steps to emit.
    """

    name: str
    description: str
    alerts: list[ScenarioAlert]


def thermal_cascade() -> Scenario:
    """Builds a CRAC-failure thermal cascade scenario.

    Picks a random GPU rack and emits a CRAC inlet warning, GPU thermal
    throttling on a host in that rack, throttling on a second host, and
    finally a critical rack ambient temperature alert.

    Returns:
        A freshly randomized :class:`Scenario`.
    """
    rack = random.choice(["rack-12", "rack-14", "rack-18"])
    hosts = RACK_HOSTS[rack]
    crac_unit = f"CRAC-Unit-{random.randint(1, 4)}"
    affected_host = random.choice(hosts)
    second_host = random.choice([h for h in hosts if h != affected_host])

    return Scenario(
        name="thermal_cascade",
        description=f"CRAC unit failure causing thermal cascade in {rack}",
        alerts=[
            ScenarioAlert(
                delay_seconds=0,
                severity="warning",
                category="thermal",
                component=crac_unit,
                host=affected_host,
                rack=rack,
                metric_name="inlet_temperature_celsius",
                metric_value=round(random.uniform(36.0, 40.0), 1),
                threshold=35.0,
                message=f"{crac_unit} inlet temperature rising above threshold in {rack}",
                raw_data={"trend": "increasing", "rate_per_min": round(random.uniform(0.5, 1.5), 2)},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(8, 15),
                severity="warning",
                category="gpu",
                component=f"GPU-{random.randint(0, 7)}",
                host=affected_host,
                rack=rack,
                metric_name="gpu_temperature_celsius",
                metric_value=round(random.uniform(86.0, 92.0), 1),
                threshold=85.0,
                message=f"GPU thermal throttling detected on {affected_host}",
                raw_data={"clock_reduction_percent": random.randint(20, 50), "workload": "llm-training-v3"},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(5, 10),
                severity="critical",
                category="gpu",
                component=f"GPU-{random.randint(0, 7)}",
                host=second_host,
                rack=rack,
                metric_name="gpu_temperature_celsius",
                metric_value=round(random.uniform(91.0, 96.0), 1),
                threshold=85.0,
                message=f"Multiple GPUs thermal throttling on {second_host}, training throughput degraded",
                raw_data={"affected_gpus": random.randint(3, 8), "workload": "llm-training-v3"},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(5, 10),
                severity="critical",
                category="thermal",
                component=crac_unit,
                host=affected_host,
                rack=rack,
                metric_name="temperature_celsius",
                metric_value=round(random.uniform(78.0, 88.0), 1),
                threshold=75.0,
                message=f"Rack ambient temperature critical in {rack} — {crac_unit} potential failure",
                raw_data={"action_required": "immediate", "redundant_cooling": True},
            ),
        ],
    )


def gpu_hardware_failure() -> Scenario:
    """Builds a GPU hardware failure cascade scenario.

    Starts with rising ECC errors on a single GPU, escalates to an
    uncorrectable ``GPU fallen off bus`` event, then NVLink errors on a
    peer GPU, and finally a node-drain notice.

    Returns:
        A freshly randomized :class:`Scenario`.
    """
    rack = random.choice(["rack-12", "rack-14", "rack-18"])
    hosts = RACK_HOSTS[rack]
    host = random.choice(hosts)
    gpu_id = random.randint(0, 7)
    peer_gpu = (gpu_id + 1) % 8

    return Scenario(
        name="gpu_hardware_failure",
        description=f"GPU hardware failure cascade on {host}",
        alerts=[
            ScenarioAlert(
                delay_seconds=0,
                severity="warning",
                category="gpu",
                component=f"GPU-{gpu_id}",
                host=host,
                rack=rack,
                metric_name="gpu_ecc_errors_total",
                metric_value=float(random.randint(15, 50)),
                threshold=10.0,
                message=f"ECC error count increasing on GPU-{gpu_id} ({host})",
                raw_data={"error_type": "SRAM", "rate_per_hour": random.randint(5, 20)},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(10, 20),
                severity="critical",
                category="gpu",
                component=f"GPU-{gpu_id}",
                host=host,
                rack=rack,
                metric_name="gpu_ecc_errors_total",
                metric_value=float(random.randint(100, 500)),
                threshold=100.0,
                message=f"GPU-{gpu_id} fallen off bus on {host} — uncorrectable ECC errors",
                raw_data={"error_type": "DRAM_uncorrectable", "gpu_state": "lost", "xid_error": 79},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(3, 8),
                severity="warning",
                category="gpu",
                component=f"NVSwitch-{rack}",
                host=host,
                rack=rack,
                metric_name="gpu_ecc_errors_total",
                metric_value=float(random.randint(5, 20)),
                threshold=10.0,
                message=f"NVLink errors on GPU-{peer_gpu} (peer of failed GPU-{gpu_id}) on {host}",
                raw_data={"nvlink_lane_errors": random.randint(10, 100), "affected_peer": f"GPU-{gpu_id}"},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(5, 10),
                severity="critical",
                category="gpu",
                component=host,
                host=host,
                rack=rack,
                metric_name="gpu_utilization_percent",
                metric_value=0.0,
                threshold=0.0,
                message=f"Node {host} marked unhealthy — GPU topology degraded, draining workloads",
                raw_data={"healthy_gpus": 8 - random.randint(1, 3), "action": "drain_and_cordon"},
            ),
        ],
    )


def network_partition() -> Scenario:
    """Builds a top-of-rack switch failure scenario.

    Sequence: port flapping warning, packet loss critical, multi-node
    latency spike, then a NCCL training-job stall.

    Returns:
        A freshly randomized :class:`Scenario`.
    """
    rack = random.choice(RACKS)
    hosts = RACK_HOSTS[rack]
    switch = f"TOR-Switch-{rack}"

    return Scenario(
        name="network_partition",
        description=f"Network partition in {rack} due to switch issues",
        alerts=[
            ScenarioAlert(
                delay_seconds=0,
                severity="warning",
                category="network",
                component=switch,
                host=hosts[0],
                rack=rack,
                metric_name="port_flap_count",
                metric_value=float(random.randint(4, 8)),
                threshold=3.0,
                message=f"Port flapping detected on {switch} — STP reconvergence in progress",
                raw_data={"affected_ports": random.randint(2, 6), "flap_interval_sec": random.randint(5, 30)},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(8, 15),
                severity="critical",
                category="network",
                component=switch,
                host=hosts[0],
                rack=rack,
                metric_name="packet_loss_percent",
                metric_value=round(random.uniform(5.0, 25.0), 1),
                threshold=5.0,
                message=f"Significant packet loss on {rack} — {switch} degraded",
                raw_data={"affected_hosts": len(hosts), "fabric_impact": "partial"},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(5, 10),
                severity="critical",
                category="network",
                component=switch,
                host=random.choice(hosts),
                rack=rack,
                metric_name="latency_ms",
                metric_value=round(random.uniform(50.0, 200.0), 1),
                threshold=50.0,
                message=f"Multiple nodes unreachable in {rack} — NCCL all-reduce timeout imminent",
                raw_data={"unreachable_hosts": random.sample(hosts, min(3, len(hosts))), "impact": "distributed_training"},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(5, 12),
                severity="critical",
                category="gpu",
                component="training-cluster",
                host=random.choice(hosts),
                rack=rack,
                metric_name="gpu_utilization_percent",
                metric_value=0.0,
                threshold=0.0,
                message=f"Distributed training job stalled — NCCL timeout on {rack} nodes",
                raw_data={"job_id": f"train-llm-{random.randint(1000, 9999)}", "duration_min": random.randint(2, 10)},
            ),
        ],
    )


def storage_degradation() -> Scenario:
    """Builds a storage degradation scenario impacting training checkpoints.

    Starts with SMART warnings on a storage host, escalates to I/O
    latency, then to checkpoint write failures on a downstream GPU host
    and finally a potential data loss alert.

    Returns:
        A freshly randomized :class:`Scenario`.
    """
    rack = "rack-16"
    hosts = RACK_HOSTS[rack]
    storage_host = random.choice([h for h in hosts if "storage" in h])
    gpu_rack = random.choice(["rack-12", "rack-14", "rack-18"])
    gpu_host = random.choice(RACK_HOSTS[gpu_rack])

    return Scenario(
        name="storage_degradation",
        description=f"Storage degradation on {storage_host} affecting training checkpoints",
        alerts=[
            ScenarioAlert(
                delay_seconds=0,
                severity="warning",
                category="storage",
                component=f"disk-sda",
                host=storage_host,
                rack=rack,
                metric_name="disk_smart_errors",
                metric_value=float(random.randint(6, 15)),
                threshold=5.0,
                message=f"SMART warnings on {storage_host} disk sda — predictive failure alert",
                raw_data={"smart_attribute": "Reallocated_Sector_Ct", "raw_value": random.randint(50, 200)},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(10, 20),
                severity="warning",
                category="storage",
                component=f"disk-sda",
                host=storage_host,
                rack=rack,
                metric_name="io_latency_ms",
                metric_value=round(random.uniform(60.0, 150.0), 1),
                threshold=50.0,
                message=f"I/O latency spike on {storage_host} — degraded disk performance",
                raw_data={"read_latency_ms": round(random.uniform(30.0, 80.0), 1), "write_latency_ms": round(random.uniform(80.0, 200.0), 1)},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(8, 15),
                severity="critical",
                category="storage",
                component="checkpoint-volume",
                host=gpu_host,
                rack=gpu_rack,
                metric_name="io_latency_ms",
                metric_value=round(random.uniform(200.0, 500.0), 1),
                threshold=200.0,
                message=f"Checkpoint write failure on {gpu_host} — storage backend timeout",
                raw_data={"checkpoint_path": "/mnt/checkpoints/llm-v3/", "retry_count": random.randint(3, 5)},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(5, 10),
                severity="critical",
                category="storage",
                component="model-storage",
                host=gpu_host,
                rack=gpu_rack,
                metric_name="disk_smart_errors",
                metric_value=float(random.randint(20, 50)),
                threshold=20.0,
                message=f"Model checkpoint save failed — potential data loss risk for training run",
                raw_data={"job_id": f"train-llm-{random.randint(1000, 9999)}", "last_successful_checkpoint": "epoch-47"},
            ),
        ],
    )


def power_anomaly() -> Scenario:
    """Builds a recoverable PDU/UPS power anomaly scenario.

    Sequence: voltage fluctuation warning, UPS battery engagement, load
    shed warning, and finally an ``info``-level power-restored event.
    Used to exercise the agent's classification of recoverable
    incidents that should NOT escalate.

    Returns:
        A freshly randomized :class:`Scenario`.
    """
    rack = random.choice(RACKS)
    pdu = f"PDU-{'AB'[random.randint(0, 1)]}{random.randint(1, 2)}"
    hosts = RACK_HOSTS[rack]

    return Scenario(
        name="power_anomaly",
        description=f"Power anomaly on {pdu} affecting {rack}",
        alerts=[
            ScenarioAlert(
                delay_seconds=0,
                severity="warning",
                category="power",
                component=pdu,
                host=hosts[0],
                rack=rack,
                metric_name="voltage_v",
                metric_value=round(random.uniform(195.0, 202.0), 1),
                threshold=200.0,
                message=f"Voltage fluctuation detected on {pdu} in {rack}",
                raw_data={"phase": random.choice(["A", "B", "C"]), "fluctuation_range_v": round(random.uniform(8.0, 18.0), 1)},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(5, 10),
                severity="critical",
                category="power",
                component="UPS-1",
                host=hosts[0],
                rack=rack,
                metric_name="ups_battery_percent",
                metric_value=round(random.uniform(85.0, 95.0), 1),
                threshold=50.0,
                message=f"UPS battery engaged for {rack} — utility power quality degraded",
                raw_data={"ups_mode": "battery", "estimated_runtime_min": random.randint(15, 45)},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(8, 15),
                severity="warning",
                category="power",
                component=pdu,
                host=random.choice(hosts),
                rack=rack,
                metric_name="power_draw_kw",
                metric_value=round(random.uniform(10.0, 18.0), 1),
                threshold=30.0,
                message=f"Non-critical load shed initiated on {rack} to conserve UPS capacity",
                raw_data={"shed_loads": ["monitoring-agents", "log-collectors"], "priority_loads_maintained": True},
            ),
            ScenarioAlert(
                delay_seconds=random.uniform(10, 20),
                severity="info",
                category="power",
                component=pdu,
                host=random.choice(hosts),
                rack=rack,
                metric_name="voltage_v",
                metric_value=round(random.uniform(208.0, 212.0), 1),
                threshold=200.0,
                message=f"Power restored on {pdu} — UPS returning to standby mode",
                raw_data={"ups_mode": "standby", "battery_recharge_started": True},
            ),
        ],
    )


SCENARIOS = [
    thermal_cascade,
    gpu_hardware_failure,
    network_partition,
    storage_degradation,
    power_anomaly,
]


def pick_scenario() -> Scenario:
    """Returns a freshly randomized scenario selected uniformly at random.

    Returns:
        A new :class:`Scenario` produced by one of the registered
        scenario generators in :data:`SCENARIOS`.
    """
    generator = random.choice(SCENARIOS)
    return generator()
