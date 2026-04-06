# Node Health Check Procedure

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo | **Last updated:** 2026-03-18

## Overview

This runbook covers the standard health check procedure for compute nodes in the dc-tokyo-01 cluster. All GPU and CPU compute nodes should be checked on a 4-hour cycle by the automated monitoring stack. Manual checks are triggered when alerts fire or during scheduled maintenance windows.

## Automated Health Check Thresholds

The following thresholds trigger an alert to the dc-ops-tokyo on-call:

- CPU temperature > 85C sustained for 5 minutes
- GPU temperature > 89C sustained for 3 minutes
- DIMM correctable ECC error count > 100 in 24 hours
- NVMe drive SMART health status != "OK"
- BMC unreachable for > 2 consecutive polls (60s interval)
- Fan RPM < 2000 on any chassis fan
- PSU efficiency drop > 10% from baseline

## Manual Diagnostic Commands

Run these from the ops jumpbox (`jump01.dc-tokyo-01.dc-internal.local`):

```
# Check IPMI sensor readings
ipmitool -H <bmc-ip> -U admin -P $BMC_PASS sensor list

# Check system event log for hardware errors
ipmitool -H <bmc-ip> -U admin -P $BMC_PASS sel list

# GPU health via DCGM
dcgmi diag -r 3 -j  # Level 3 diagnostic, JSON output

# NVMe health
nvme smart-log /dev/nvme0n1

# Memory error check
edac-util --status
rasdaemon --record
```

## When to Cordon a Node

Immediately cordon the node from the Slurm or Kubernetes cluster if any of the following are true:

1. Uncorrectable ECC (UE) memory error detected -- run `scontrol update nodename=<node> state=drain reason="UE memory error"`
2. GPU XID error 48 (double-bit ECC) or XID 79 (GPU fallen off bus)
3. BMC reports critical PSU or thermal event
4. NVMe predictive failure flag set
5. More than 2 correctable ECC errors per hour on a single DIMM

After cordoning, open a ticket in the dc-ops-tokyo queue and tag the node with `hw-investigation`. If GPU errors are involved, cc gpu-infra in the ticket.

## Post-Check Actions

- If the node passes all checks, return it to service: `scontrol update nodename=<node> state=resume`
- If hardware replacement is needed, escalate per the escalation policy and move the node to `state=down`
- Log all manual checks in the `#dc-ops-tokyo-log` Slack channel with the node ID and findings
