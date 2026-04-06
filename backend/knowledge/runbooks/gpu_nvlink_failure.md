# GPU NVLink Failure Runbook

**Facility:** dc-tokyo-01 | **Owner:** gpu-infra | **Last updated:** 2026-03-05  
**Severity:** P2 (degraded link) / P1 (link down affecting training)

## NVLink Topology Overview

In dc-tokyo-01, GPU nodes use the following NVLink configurations:

- **A100 DGX (8x GPU):** NVLink 3.0, 12 links per GPU, 600 GB/s bidirectional per GPU. Full mesh within the 8-GPU baseboard.
- **H100 DGX (8x GPU):** NVLink 4.0 via NVSwitch, 18 links per GPU, 900 GB/s bidirectional per GPU. All-to-all connectivity through 4 NVSwitch chips on the baseboard.

NVLink failures break the high-bandwidth fabric between GPUs and force fallback to PCIe, reducing interconnect bandwidth by 5-10x. This is catastrophic for data-parallel and tensor-parallel training workloads.

## Failure Symptoms

- XID 74 (NVLink ECC error) or XID 45 (NVLink error) in `dmesg`
- `nvidia-smi nvlink -s` shows link state as "inactive" or elevated error counts
- Training jobs report degraded all-reduce throughput (NCCL logs show PCIe fallback)
- Prometheus alert: `dcgm_nvlink_bandwidth_total` drops below expected baseline

## Diagnostic Steps

### 1. Identify Affected Links

    nvidia-smi nvlink -s          # Summary of all NVLink states
    nvidia-smi nvlink -e          # Error counters per link
    dcgmi diag -r 2 -g <gpu-id>  # NVLink-specific diagnostics

Record which GPU pair and which specific link IDs are affected.

### 2. Check NVSwitch Health (H100 only)

    nvidia-smi nvswitch -s        # NVSwitch status
    dcgmi diag -r 2 --nvswitch

NVSwitch failures on H100 nodes affect multiple GPU pairs simultaneously. If an NVSwitch is faulted, the entire node must be drained.

### 3. Attempt Link Recovery

    nvidia-smi -r                 # GPU reset (resets NVLink state)

If the link recovers after reset, place the node back into service with elevated monitoring for 24 hours. If the link remains down after reset, proceed to isolation.

## Isolation Procedure

1. Notify ml-platform team of impending node drain via `#ml-platform` Slack.
2. Allow active training jobs to checkpoint (5 min grace period).
3. Drain the node: `kubectl drain <node> --grace-period=300 --ignore-daemonsets`
4. Label the node as degraded: `kubectl label node <node> aiand.co/gpu-health=degraded`
5. If a single GPU link is down but the node has other healthy GPU groups, gpu-infra may partition the node to offer a reduced GPU count. This requires manual NCCL topology configuration and is only appropriate for inference workloads, not distributed training.

## Impact on Multi-GPU Training

NVLink failures cause NCCL collective operations to fall back to PCIe, increasing all-reduce latency by 5-10x. For large model training (tensor parallelism across 8 GPUs), even a single degraded link can reduce overall training throughput by 30-50%. The NCCL library will log: `NCCL WARN: NET/Plugin: NVLink disabled between GPU X and GPU Y`.

Training jobs using pipeline parallelism across nodes (via InfiniBand) are less affected, as NVLink is only used intra-node. However, the affected node becomes the bottleneck.

## Escalation

- **P2 (degraded link, no active training impact):** gpu-infra on-call, investigate within 2 hours.
- **P1 (link down, active training impacted):** Page gpu-infra and ml-platform leads. Coordinate failover to standby node.

**Contact:** gpu-infra on-call: +81-3-XXXX-4020 | NVSwitch HW support: nvidia-nvswitch@nvidia.com
