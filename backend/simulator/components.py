from dataclasses import dataclass


@dataclass
class MetricProfile:
    name: str
    unit: str
    normal_min: float
    normal_max: float
    warning_threshold: float
    critical_threshold: float


RACKS = ["rack-12", "rack-14", "rack-16", "rack-18"]

RACK_HOSTS: dict[str, list[str]] = {
    "rack-12": [f"node-gpu-rack12-0{i}" for i in range(1, 6)],
    "rack-14": [f"node-gpu-rack14-0{i}" for i in range(1, 6)],
    "rack-16": [
        "node-storage-rack16-01", "node-storage-rack16-02",
        "node-inference-rack16-01", "node-inference-rack16-02",
    ],
    "rack-18": [f"node-gpu-rack18-0{i}" for i in range(1, 5)],
}

GPU_COMPONENTS = [f"GPU-{i}" for i in range(8)]

CRAC_UNITS = ["CRAC-Unit-1", "CRAC-Unit-2", "CRAC-Unit-3", "CRAC-Unit-4"]
PDU_UNITS = ["PDU-A1", "PDU-A2", "PDU-B1", "PDU-B2"]

THERMAL_METRICS = [
    MetricProfile("temperature_celsius", "°C", 20.0, 45.0, 75.0, 90.0),
    MetricProfile("inlet_temperature_celsius", "°C", 18.0, 28.0, 35.0, 42.0),
    MetricProfile("coolant_flow_rate_lpm", "L/min", 40.0, 80.0, 30.0, 20.0),  # Lower is worse
]

GPU_METRICS = [
    MetricProfile("gpu_temperature_celsius", "°C", 30.0, 70.0, 85.0, 95.0),
    MetricProfile("gpu_utilization_percent", "%", 0.0, 100.0, 0.0, 0.0),  # Not threshold-based
    MetricProfile("gpu_memory_used_gb", "GB", 0.0, 80.0, 76.0, 79.0),
    MetricProfile("gpu_ecc_errors_total", "count", 0.0, 0.0, 10.0, 100.0),
    MetricProfile("gpu_power_draw_watts", "W", 50.0, 300.0, 350.0, 400.0),
]

NETWORK_METRICS = [
    MetricProfile("packet_loss_percent", "%", 0.0, 0.1, 1.0, 5.0),
    MetricProfile("port_flap_count", "count", 0.0, 0.0, 3.0, 10.0),
    MetricProfile("link_speed_gbps", "Gbps", 100.0, 100.0, 50.0, 25.0),  # Lower is worse
    MetricProfile("latency_ms", "ms", 0.1, 1.0, 10.0, 50.0),
]

STORAGE_METRICS = [
    MetricProfile("disk_smart_errors", "count", 0.0, 0.0, 5.0, 20.0),
    MetricProfile("io_latency_ms", "ms", 0.5, 5.0, 50.0, 200.0),
    MetricProfile("disk_usage_percent", "%", 10.0, 70.0, 85.0, 95.0),
    MetricProfile("iops", "ops/s", 1000.0, 50000.0, 100.0, 50.0),  # Lower is worse
]

POWER_METRICS = [
    MetricProfile("voltage_v", "V", 208.0, 212.0, 200.0, 190.0),  # Lower is worse
    MetricProfile("current_a", "A", 10.0, 40.0, 45.0, 50.0),
    MetricProfile("power_draw_kw", "kW", 5.0, 25.0, 30.0, 35.0),
    MetricProfile("ups_battery_percent", "%", 95.0, 100.0, 50.0, 20.0),  # Lower is worse
]

MEMORY_METRICS = [
    MetricProfile("memory_correctable_errors", "count", 0.0, 0.0, 100.0, 1000.0),
    MetricProfile("memory_uncorrectable_errors", "count", 0.0, 0.0, 1.0, 5.0),
    MetricProfile("memory_usage_percent", "%", 10.0, 80.0, 90.0, 97.0),
]

CATEGORY_METRICS = {
    "thermal": THERMAL_METRICS,
    "gpu": GPU_METRICS,
    "network": NETWORK_METRICS,
    "storage": STORAGE_METRICS,
    "power": POWER_METRICS,
    "memory": MEMORY_METRICS,
}
