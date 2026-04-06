# GPU Thermal Throttling Runbook

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo | **Last updated:** 2026-03-12  
**Severity:** P2 (throttling active) / P1 (shutdown imminent)

## Temperature Thresholds

| GPU Model | Normal Operating | Throttle Onset | Hard Throttle | Emergency Shutdown |
|-----------|-----------------|----------------|---------------|--------------------|
| A100 SXM4 | 35-70C | 75C | 83C | 90C |
| H100 SXM5 | 35-72C | 78C | 85C | 92C |

Throttling reduces GPU clock frequency progressively. At hard throttle, clock drops to approximately 60% of base frequency, causing severe training performance degradation. Emergency shutdown triggers an immediate GPU halt and raises a P1 alert to dc-ops-tokyo.

## Detection

Thermal alerts fire via Prometheus when `dcgm_gpu_temp` exceeds threshold for more than 60 seconds. Check current readings:

    nvidia-smi -q -d TEMPERATURE
    dcgmi diag -r 1 -g <gpu-id>

## Step-by-Step Remediation

### 1. Verify CRAC Unit Status

Check the CRAC (Computer Room Air Conditioning) units serving the affected row. Log into the Liebert iCOM controller at `crac-mgmt.dc-tokyo-01.dc-internal.local` and confirm all units in the row are operational. If a CRAC unit has faulted, escalate immediately to facilities-tokyo per the CRAC Unit Failure runbook.

### 2. Check Airflow Obstructions

Physically inspect the hot aisle / cold aisle containment around the affected rack. Confirm blanking panels are installed in all empty U positions. Check that perforated floor tiles are properly placed and not blocked. Verify the raised floor plenum pressure is above 0.05 inches WC on the BMS dashboard.

### 3. Assess Workload Distribution

Review GPU utilization across the node. Uneven workload can cause hotspots:

    nvidia-smi dmon -s pucvmet -d 5

If a single GPU is disproportionately loaded due to a scheduling error, coordinate with gpu-infra to rebalance. For multi-node training jobs, the scheduler should distribute evenly across all available GPUs in the thermal budget.

### 4. Reduce Ambient Load (Temporary)

If CRAC and airflow are nominal but temperatures remain elevated, apply a temporary power cap:

    nvidia-smi -pl 300   # A100: reduce from 400W TDP
    nvidia-smi -pl 550   # H100: reduce from 700W TDP

This reduces thermal output while the root cause is investigated. Notify the training team via `#gpu-infra` Slack channel.

## Escalation

- **P2 (throttling):** dc-ops-tokyo on-call, notify gpu-infra within 30 minutes.
- **P1 (shutdown risk):** Page dc-ops-tokyo lead and facilities-tokyo immediately. If ambient temperature exceeds 32C at cold aisle, initiate emergency thermal procedure per CRAC runbook.

**Contact:** dc-ops-tokyo on-call: +81-3-XXXX-4010 | gpu-infra lead: gpu-infra@ops-team.local
