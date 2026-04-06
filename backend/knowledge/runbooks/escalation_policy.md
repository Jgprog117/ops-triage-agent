# Escalation Policy

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo | **Last updated:** 2026-03-25

## Overview

This document defines the escalation policy for all operational incidents at dc-tokyo-01. Follow this policy to ensure the right people are engaged at the right time. All incident communication happens in the `#dc-incidents-tokyo` Slack channel unless otherwise specified.

## Severity Definitions

| Severity | Definition | Example |
|----------|-----------|---------|
| **P1 - Critical** | Total loss of training capacity or imminent data loss. Multiple racks or core infrastructure affected. | Full fabric outage, storage system failure, cooling system critical alarm, power feed loss |
| **P2 - High** | Significant capacity degradation (>25% of compute unavailable) or single-system data risk. | Spine switch failure, Lustre OST down, multiple node failures in same rack |
| **P3 - Medium** | Limited impact, single node or small group of nodes affected. Workaround available. | Single node DIMM failure, single GPU failure, individual job failures due to hardware |
| **P4 - Low** | Minimal impact, cosmetic or informational. No immediate production effect. | Monitoring alert tuning, non-critical firmware update available, single disk degraded in RAID |

## Response Time SLAs

| Severity | Acknowledge | First Update | Resolution Target |
|----------|-------------|--------------|-------------------|
| P1 | 5 minutes | 15 minutes | 2 hours |
| P2 | 15 minutes | 30 minutes | 8 hours |
| P3 | 1 hour | 4 hours | 48 hours |
| P4 | 4 hours | Next business day | 5 business days |

## When to Escalate

- **P1:** Immediately page the dc-ops-tokyo on-call lead AND the infrastructure engineering manager. Activate the incident bridge in `#dc-incidents-tokyo`.
- **P2:** Page the dc-ops-tokyo on-call. If no acknowledgment within 15 minutes, escalate to the on-call lead.
- **P3:** Create a ticket in the dc-ops-tokyo queue. Tag the relevant sub-team (gpu-infra, network-ops, storage-team, power-facilities).
- **P4:** Create a ticket. No paging required.

## Team Contacts

| Team | Slack Channel | On-Call PagerDuty | Scope |
|------|--------------|-------------------|-------|
| dc-ops-tokyo | #dc-ops-tokyo-log | `dc-ops-tokyo` schedule | Physical infrastructure, node hardware, general ops |
| gpu-infra | #gpu-infra | `gpu-infra` schedule | GPU health, driver issues, DCGM, XID errors |
| network-ops | #network-ops | `network-ops` schedule | InfiniBand fabric, Ethernet management network, UFM, switches |
| storage-team | #storage-ops | `storage-team` schedule | Lustre, NFS, NVMe-oF, backup systems |
| ml-platform | #training-ops | `ml-platform` schedule | Slurm, job scheduling, training frameworks, checkpointing |
| power-facilities | #facilities-tokyo | `power-facilities` schedule | Power distribution, UPS, cooling, physical access |

## Cross-Team Escalation

If an incident spans multiple teams (e.g., network issue causing training failures), the dc-ops-tokyo on-call acts as incident commander and pulls in the relevant teams. For P1 incidents, the engineering manager on-call (`eng-management` PagerDuty schedule) is automatically paged and serves as executive liaison.
