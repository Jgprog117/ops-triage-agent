# Memory Error Handling

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo | **Last updated:** 2026-03-10

## Overview

Memory errors in dc-tokyo-01 compute nodes are one of the most frequent hardware fault categories. This runbook covers how to identify DIMM failure patterns, run diagnostics, evacuate workloads, and determine when replacement is required. Early detection prevents silent data corruption in training workloads.

## DIMM Failure Patterns

Memory errors are classified as correctable (CE) and uncorrectable (UE):

- **Correctable errors (CE):** Single-bit errors corrected by ECC. Low rates are normal. The threshold for investigation is > 100 CEs per 24 hours on a single DIMM, or > 10 CEs per hour.
- **Uncorrectable errors (UE):** Multi-bit errors that ECC cannot fix. Any UE is a critical event -- the node must be cordoned immediately.
- **Pattern recognition:** Errors concentrated on a single DIMM slot suggest a failing DIMM. Errors spread across multiple DIMMs on the same channel suggest a memory controller or CPU issue.

Check current error counts:
```
# Via EDAC sysfs
cat /sys/devices/system/edac/mc/mc*/csrow*/ce_count
cat /sys/devices/system/edac/mc/mc*/csrow*/ue_count

# Via rasdaemon database
ras-mc-ctl --errors
```

## Memtest Procedure

When a DIMM is suspected faulty:

1. Cordon the node: `scontrol update nodename=<node> state=drain reason="memory diagnostics"`
2. Wait for all running jobs to complete or migrate (max 30 minutes grace period)
3. Reboot into memtest86+ via IPMI: `ipmitool -H <bmc-ip> -U admin -P $BMC_PASS chassis bootdev pxe` (PXE boot to memtest image)
4. Run a minimum of 4 full passes. A single error confirms the DIMM is faulty.
5. Record the failing DIMM slot from the memtest output (e.g., `DIMM_A1`, `DIMM_B2`)

## Node Evacuation

Before taking a node offline for memory replacement:

1. Drain the node from Slurm with a 15-minute grace period: `scontrol update nodename=<node> state=drain reason="DIMM replacement"`
2. Verify all jobs have exited: `squeue -w <node>`
3. If a long-running training job cannot be interrupted, coordinate with ml-platform for a checkpoint-and-stop
4. Notify the job owners in `#training-ops` with an ETA for node return

## When to Replace Memory

Replace the DIMM if any of the following criteria are met:

- Any uncorrectable error (UE) detected
- Correctable error rate > 500 per day on a single DIMM, sustained over 48 hours
- Memtest86+ reports any error in 4-pass test
- DIMM reported as "degraded" in BMC system event log

After replacement, run a full 4-pass memtest and an overnight burn-in with `stress-ng --vm 8 --vm-bytes 90%` before returning the node to the cluster. Log the replacement in the asset management system with the old and new DIMM serial numbers.

Escalate to the hardware vendor (open an RMA case) if more than 2 DIMMs fail on the same node within 30 days -- this may indicate a motherboard or CPU defect.
