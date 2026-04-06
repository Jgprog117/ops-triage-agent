# Storage SMART Warning Runbook

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo / storage-infra | **Last updated:** 2026-02-15  
**Severity:** P3 (predictive warning) / P2 (imminent failure)

## Overview

dc-tokyo-01 uses a mix of NVMe SSDs (Samsung PM9A3 3.84TB, Micron 7450 Pro 7.68TB) for local scratch storage on GPU nodes and enterprise HDDs (Seagate Exos X20 20TB) in the shared storage tier (Ceph cluster). SMART (Self-Monitoring, Analysis, and Reporting Technology) provides early warning of drive degradation before catastrophic failure.

## Critical SMART Attributes to Monitor

### NVMe SSDs

| Attribute | Warning Threshold | Critical Threshold |
|-----------|------------------|-------------------|
| Available Spare | < 20% | < 10% |
| Percentage Used | > 80% | > 95% |
| Media Errors | > 0 | > 5 |
| Critical Warning | Any non-zero bit | -- |
| Temperature | > 70C | > 75C |

### SATA/SAS HDDs

| Attribute ID | Name | Warning Threshold |
|-------------|------|-------------------|
| 5 | Reallocated Sector Count | > 10 |
| 187 | Reported Uncorrectable | > 0 |
| 188 | Command Timeout | > 100 |
| 197 | Current Pending Sector | > 0 |
| 198 | Offline Uncorrectable | > 0 |

## Detection

SMART alerts are collected by the `smartctl_exporter` running on every node and aggregated in Prometheus. Dashboard: `grafana.dc-tokyo-01.aiand.internal/d/storage-health`.

Check a specific drive manually:

    smartctl -a /dev/nvme0n1        # NVMe
    smartctl -a /dev/sda            # HDD
    nvme smart-log /dev/nvme0n1     # NVMe native

## Disk Replacement Procedure

### 1. Confirm Failure Prediction

Verify the SMART alert is genuine and not transient:

    smartctl -H /dev/<device>       # Overall health assessment

If the health check returns "PASSED" but specific attributes are degrading, continue monitoring for 24 hours. If health check returns "FAILED", proceed to immediate replacement.

### 2. Drain Workloads from Affected Drive

For local scratch SSDs on GPU nodes:

1. Check if active training jobs are using the drive for checkpoints: `lsof +D /mnt/scratch`
2. Notify ml-platform to redirect checkpoint writes to alternate storage.
3. If the drive is part of a local RAID array, verify rebuild will be possible: `mdadm --detail /dev/md0`

For Ceph OSD drives:

1. Set the OSD to "noout" temporarily: `ceph osd set noout`
2. Gracefully remove the OSD: `ceph osd out osd.<id>` then `systemctl stop ceph-osd@<id>`
3. Wait for Ceph rebalance to complete: `ceph -w` (watch for "active+clean" on all PGs)

### 3. Physical Replacement

1. Identify the drive's physical location using the enclosure LED: `ledctl locate=/dev/<device>`
2. For hot-swap bays, pull the drive after confirming it is fully offline.
3. Insert the replacement drive from dc-ops-tokyo spares inventory (tracked in `inventory.dc-tokyo-01.aiand.internal`).
4. For Ceph: initialize the new OSD via `ceph-volume lvm create --data /dev/<device>` and unset noout flag.
5. For local RAID: add the drive back to the array: `mdadm --manage /dev/md0 --add /dev/<device>`

### 4. Post-Replacement Verification

Run a 4-hour burn-in test on the new drive:

    fio --name=burnin --rw=randrw --bs=4k --size=100G --runtime=14400 --filename=/dev/<device>

Confirm SMART attributes are nominal after burn-in.

## Escalation

- **P3 (predictive warning):** storage-infra on-call, schedule replacement within 72 hours.
- **P2 (imminent/active failure):** dc-ops-tokyo on-call, replace within 4 hours. If Ceph cluster health drops below HEALTH_WARN, also page storage-infra lead.

**Contact:** storage-infra on-call: +81-3-XXXX-4040 | Samsung enterprise support: samsung-ssd-ent@samsung.com
