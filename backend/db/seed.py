import json
import logging
import random

from backend.db.database import get_db

logger = logging.getLogger(__name__)

HOSTS = [
    # Rack 12 — GPU training cluster (A100)
    {"hostname": "node-gpu-rack12-01", "rack": "rack-12", "gpu_type": "NVIDIA A100 80GB", "gpu_count": 8, "cpu_type": "AMD EPYC 7763", "memory_gb": 1024, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack12-02", "rack": "rack-12", "gpu_type": "NVIDIA A100 80GB", "gpu_count": 8, "cpu_type": "AMD EPYC 7763", "memory_gb": 1024, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack12-03", "rack": "rack-12", "gpu_type": "NVIDIA A100 80GB", "gpu_count": 8, "cpu_type": "AMD EPYC 7763", "memory_gb": 1024, "os": "Ubuntu 22.04 LTS", "status": "degraded"},
    {"hostname": "node-gpu-rack12-04", "rack": "rack-12", "gpu_type": "NVIDIA A100 80GB", "gpu_count": 8, "cpu_type": "AMD EPYC 7763", "memory_gb": 1024, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack12-05", "rack": "rack-12", "gpu_type": "NVIDIA A100 80GB", "gpu_count": 8, "cpu_type": "AMD EPYC 7763", "memory_gb": 1024, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    # Rack 14 — GPU training cluster (H100)
    {"hostname": "node-gpu-rack14-01", "rack": "rack-14", "gpu_type": "NVIDIA H100 80GB", "gpu_count": 8, "cpu_type": "Intel Xeon w9-3495X", "memory_gb": 2048, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack14-02", "rack": "rack-14", "gpu_type": "NVIDIA H100 80GB", "gpu_count": 8, "cpu_type": "Intel Xeon w9-3495X", "memory_gb": 2048, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack14-03", "rack": "rack-14", "gpu_type": "NVIDIA H100 80GB", "gpu_count": 8, "cpu_type": "Intel Xeon w9-3495X", "memory_gb": 2048, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack14-04", "rack": "rack-14", "gpu_type": "NVIDIA H100 80GB", "gpu_count": 8, "cpu_type": "Intel Xeon w9-3495X", "memory_gb": 2048, "os": "Ubuntu 22.04 LTS", "status": "degraded"},
    {"hostname": "node-gpu-rack14-05", "rack": "rack-14", "gpu_type": "NVIDIA H100 80GB", "gpu_count": 8, "cpu_type": "Intel Xeon w9-3495X", "memory_gb": 2048, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    # Rack 16 — Storage and inference nodes
    {"hostname": "node-storage-rack16-01", "rack": "rack-16", "gpu_type": None, "gpu_count": 0, "cpu_type": "AMD EPYC 9654", "memory_gb": 512, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-storage-rack16-02", "rack": "rack-16", "gpu_type": None, "gpu_count": 0, "cpu_type": "AMD EPYC 9654", "memory_gb": 512, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-inference-rack16-01", "rack": "rack-16", "gpu_type": "NVIDIA L40S", "gpu_count": 4, "cpu_type": "AMD EPYC 9654", "memory_gb": 512, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-inference-rack16-02", "rack": "rack-16", "gpu_type": "NVIDIA L40S", "gpu_count": 4, "cpu_type": "AMD EPYC 9654", "memory_gb": 512, "os": "Ubuntu 22.04 LTS", "status": "maintenance"},
    # Rack 18 — Mixed workload
    {"hostname": "node-gpu-rack18-01", "rack": "rack-18", "gpu_type": "NVIDIA A100 80GB", "gpu_count": 8, "cpu_type": "AMD EPYC 7763", "memory_gb": 1024, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack18-02", "rack": "rack-18", "gpu_type": "NVIDIA A100 80GB", "gpu_count": 8, "cpu_type": "AMD EPYC 7763", "memory_gb": 1024, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack18-03", "rack": "rack-18", "gpu_type": "NVIDIA H100 80GB", "gpu_count": 8, "cpu_type": "Intel Xeon w9-3495X", "memory_gb": 2048, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    {"hostname": "node-gpu-rack18-04", "rack": "rack-18", "gpu_type": "NVIDIA H100 80GB", "gpu_count": 8, "cpu_type": "Intel Xeon w9-3495X", "memory_gb": 2048, "os": "Ubuntu 22.04 LTS", "status": "healthy"},
    # Infrastructure nodes
    {"hostname": "node-mgmt-01", "rack": "rack-01", "gpu_type": None, "gpu_count": 0, "cpu_type": "Intel Xeon Gold 6348", "memory_gb": 256, "os": "Rocky Linux 9", "status": "healthy"},
    {"hostname": "node-mgmt-02", "rack": "rack-01", "gpu_type": None, "gpu_count": 0, "cpu_type": "Intel Xeon Gold 6348", "memory_gb": 256, "os": "Rocky Linux 9", "status": "healthy"},
]


async def seed_host_data() -> None:
    db = await get_db()
    count = (await db.execute_fetchall("SELECT COUNT(*) as c FROM hosts"))[0]["c"]
    if count > 0:
        logger.info("Hosts table already seeded (%d hosts)", count)
        return

    for host in HOSTS:
        uptime = round(random.uniform(24, 8760), 1)  # 1 day to 1 year
        metadata = {
            "ipmi_ip": f"10.0.{random.randint(1, 4)}.{random.randint(10, 250)}",
            "os_kernel": "5.15.0-91-generic",
            "nvidia_driver": "535.129.03" if host["gpu_count"] else None,
            "cuda_version": "12.2" if host["gpu_count"] else None,
            "network_speed": "100Gbps" if host["gpu_count"] else "25Gbps",
        }
        await db.execute(
            """INSERT INTO hosts
               (hostname, rack, datacenter, gpu_type, gpu_count, cpu_type,
                memory_gb, os, status, uptime_hours, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                host["hostname"], host["rack"], "dc-tokyo-01",
                host["gpu_type"], host["gpu_count"], host["cpu_type"],
                host["memory_gb"], host["os"], host["status"],
                uptime, json.dumps(metadata),
            ),
        )

    await db.commit()
    logger.info("Seeded %d hosts into database", len(HOSTS))
