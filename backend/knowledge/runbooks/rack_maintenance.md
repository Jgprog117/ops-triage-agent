# Rack Maintenance Procedure

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo / power-facilities | **Last updated:** 2026-03-20

## Overview

Planned rack maintenance at dc-tokyo-01 includes firmware upgrades, cable re-routing, power feed work, cooling system servicing, and hardware replacements that require taking an entire rack offline. This runbook defines the end-to-end procedure for planned maintenance to minimize disruption to training workloads.

## Notification Requirements

All planned rack maintenance must follow these notification lead times:

| Scope | Lead Time | Approval Required |
|-------|-----------|-------------------|
| Single node (no rack power impact) | 24 hours | dc-ops-tokyo on-call |
| Partial rack (1-4 nodes) | 48 hours | dc-ops-tokyo lead |
| Full rack (all nodes + TOR switch) | 5 business days | dc-ops-tokyo lead + ml-platform lead |
| Multi-rack or spine-level work | 10 business days | Engineering manager + ml-platform lead |

Notifications must be posted in `#dc-ops-tokyo-log` and `#training-ops` with the maintenance ticket number, affected node list, and scheduled window.

## Pre-Maintenance Checklist

- [ ] Maintenance ticket created and approved per the table above
- [ ] Affected nodes identified by hostname and rack position (e.g., `gpu-r14-n01` through `gpu-r14-n08`)
- [ ] ml-platform notified and confirmed no critical training runs span the maintenance window
- [ ] Nodes drained from Slurm: `scontrol update nodename=<node-range> state=drain reason="planned maintenance MAINT-<ticket>"`
- [ ] All jobs evacuated -- verify with `squeue -w <node-range>` returns empty
- [ ] For long-running jobs, coordinate checkpoint-and-stop with the job owner at least 2 hours before the window
- [ ] If TOR switch work is involved, network-ops has confirmed the maintenance plan
- [ ] Backup current firmware versions and switch configs before any upgrades
- [ ] Physical access request submitted to power-facilities for the cage/rack (requires 24-hour advance notice)

## Workload Migration

For full-rack maintenance, workloads must be migrated in advance:

1. Identify all jobs running on the target rack: `squeue -w <node-range> -o "%i %j %u %T %M %l"`
2. Notify job owners 48 hours before the window via `#training-ops`
3. For jobs with checkpoint support, request a manual checkpoint and graceful stop
4. For jobs without checkpoint support, coordinate a natural stopping point with the owner
5. After all jobs are clear, verify no orphan GPU processes remain: `pdsh -w <node-range> "nvidia-smi --query-compute-apps=pid,name --format=csv"`

## Post-Maintenance Checklist

- [ ] Hardware/firmware changes verified and documented in the asset management system
- [ ] Run node health check on all affected nodes (see node_health_check runbook)
- [ ] For GPU nodes, run DCGM level-3 diagnostic: `dcgmi diag -r 3`
- [ ] For network changes, verify InfiniBand link status: `ibstat` and run an all-reduce bandwidth test
- [ ] Resume nodes in Slurm: `scontrol update nodename=<node-range> state=resume`
- [ ] Monitor the nodes for 30 minutes after resuming for any alert triggers
- [ ] Post completion notice in `#dc-ops-tokyo-log` with the maintenance ticket number and outcome
- [ ] Close the maintenance ticket with a summary of work performed
