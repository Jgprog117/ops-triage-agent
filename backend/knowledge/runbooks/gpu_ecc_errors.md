# GPU ECC Error Handling Runbook

**Facility:** dc-tokyo-01 | **Owner:** gpu-infra | **Last updated:** 2026-02-28  
**Severity:** P3 (correctable) / P1 (uncorrectable)

## ECC Error Types

**Correctable errors (CE):** Single-bit errors automatically corrected by the GPU memory controller. These do not cause data corruption but indicate degrading memory cells. A low background rate is normal; a sustained rate above 10 CE/hour on a single GPU warrants investigation.

**Uncorrectable errors (UCE):** Multi-bit errors that cannot be corrected. These cause immediate data corruption and typically crash the running CUDA process. A single UCE is a P1 event requiring immediate GPU isolation.

## Key XID Error Codes

| XID Code | Meaning | Action |
|----------|---------|--------|
| 48 | Double-bit ECC error (UCE) | Isolate GPU immediately |
| 63 | ECC page retirement (row remapping) | Monitor; retire GPU if rows exhausted |
| 64 | ECC page retirement failure | Retire GPU from service |
| 74 | NVLink ECC error | See NVLink Failure runbook |
| 94 | Contained ECC error (recoverable) | Log and monitor |
| 95 | Uncontained ECC error | Isolate GPU, drain node |

## Monitoring and Detection

ECC alerts fire when `dcgm_ecc_errors_total{type="uncorrectable"}` increments or when correctable error rate exceeds threshold:

    nvidia-smi -q -d ECC
    nvidia-smi --query-gpu=ecc.errors.corrected.volatile.total,ecc.errors.uncorrected.volatile.total --format=csv

Check retired pages (row remapping status):

    nvidia-smi -q -d RETIRED_PAGES

## Remediation Procedure

### 1. Correctable Error Spike

If CE rate exceeds 10/hour sustained over 4 hours on a single GPU:

1. Record full ECC state and `dmesg` output from the host.
2. Reset ECC counters after recording: `nvidia-smi -rac`
3. Monitor for 2 hours. If rate persists, proceed to step 4.
4. Coordinate with gpu-infra to drain workloads from the affected GPU via the cluster scheduler: `kubectl drain <node> --grace-period=300 --ignore-daemonsets`
5. Run extended diagnostics: `dcgmi diag -r 3 -g <gpu-id>`
6. If diagnostics fail, mark the GPU for RMA and open a ticket with NVIDIA support (contract ID: NV-ENT-TKY-2025).

### 2. Uncorrectable Error (XID 48)

1. The affected CUDA process will have already crashed. Confirm via `dmesg | grep -i xid`.
2. Immediately fence the GPU from the scheduler to prevent new workloads.
3. Drain remaining workloads from the node: allow graceful checkpoint if possible (5 min timeout).
4. Run `dcgmi diag -r 3`. If the GPU fails diagnostics, proceed to RMA.
5. If diagnostics pass, perform a GPU reset (`nvidia-smi -r`) and place back into service with elevated monitoring for 48 hours.

### 3. GPU Retirement Criteria

Retire a GPU from production if any of the following are true:

- More than 2 UCE events in a 30-day window
- Retired page count exceeds 60 (approaching hardware limit of 64 on A100/H100)
- XID 64 (page retirement failure) observed
- Extended diagnostics consistently fail

## Escalation

- **P3 (CE spike):** gpu-infra on-call, review within 4 hours.
- **P1 (UCE):** Page gpu-infra lead and dc-ops-tokyo immediately. If affecting active training run, notify ml-platform team.

**Contact:** gpu-infra on-call: +81-3-XXXX-4020 | NVIDIA support: nvcare-apac@nvidia.com
