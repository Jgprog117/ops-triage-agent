# Network Partition Detection and Recovery

**Facility:** dc-tokyo-01 | **Owner:** network-ops | **Last updated:** 2026-02-28

## Overview

Network partitions in dc-tokyo-01 primarily affect the high-speed InfiniBand fabric used for GPU-to-GPU communication during distributed training. Even a brief partition can cause NCCL collective operations to hang and eventually timeout, killing multi-node training jobs. This runbook covers detection, impact assessment, and recovery.

## Detection

Network partitions are detected through multiple signals:

- **Automated monitoring:** The UFM (Unified Fabric Manager) dashboard at `https://ufm01.dc-tokyo-01.aiand.internal` reports link-down events and subnet topology changes within 30 seconds
- **NCCL alerts:** Multiple concurrent NCCL timeout failures across different jobs indicate a fabric-level issue rather than a single-node fault
- **Heartbeat failures:** The Slurm health check daemon reports unreachable nodes via `scontrol show node | grep -c DOWN`
- **Ping mesh:** The `netcheck` service runs a full mesh ICMP and RDMA connectivity test every 60 seconds across all compute nodes

Thresholds that indicate a partition rather than isolated node failure:
- 3 or more nodes simultaneously unreachable from the management network
- UFM reports 2 or more spine switch links down
- NCCL timeouts on 5+ independent jobs within a 2-minute window

## Impact on Distributed Training

When a partition occurs:
- All training jobs spanning the partition boundary will fail with NCCL timeouts (default 300s, configurable via `NCCL_TIMEOUT`)
- Checkpoint writes in progress may leave corrupted partial files on Lustre
- The Slurm scheduler may mark affected nodes as DOWN, triggering cascading job failures

## Recovery Steps

1. **Assess scope:** Run `ibdiagnet` from the management node to map the partition boundary. Check UFM for the affected switches and ports.
2. **Notify stakeholders:** Post in `#dc-ops-tokyo-log` and `#training-ops` with the affected node range and estimated scope.
3. **Stabilize:** Cordon all affected nodes: `scontrol update nodename=<node-range> state=drain reason="network partition investigation"`
4. **Root cause:** Work with network-ops to identify the failed link or switch. Common causes include:
   - Leaf or spine switch failure -- check `show interface status` on the switch
   - Optical transceiver degradation -- check `mlxlink -d <hca> -m` for BER (bit error rate > 1e-12 is actionable)
   - Firmware bug -- compare switch firmware version against the approved version list
5. **Restore:** Once the link is restored, verify full mesh connectivity with `ibdiagnet --pc` and resume nodes.

## NCCL Diagnostics

For post-recovery validation, run the NCCL all-reduce test across the recovered nodes:
```
mpirun -np 16 --hostfile recovered_hosts.txt nccl-tests/build/all_reduce_perf -b 8 -e 4G -f 2 -g 1
```
Expected bandwidth: > 380 Gb/s per node on HDR InfiniBand. If bandwidth is below 300 Gb/s, escalate to network-ops before returning nodes to production.
