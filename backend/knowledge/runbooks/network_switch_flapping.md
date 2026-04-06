# Network Switch Port Flapping Runbook

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo / network-infra | **Last updated:** 2026-01-20  
**Severity:** P2 (isolated port) / P1 (ToR switch affecting rack)

## Overview

Port flapping occurs when a network interface repeatedly transitions between up and down states. In dc-tokyo-01, this most commonly affects the Mellanox/NVIDIA Spectrum-3 Top-of-Rack (ToR) switches connecting compute nodes via 100GbE (front-end) and 400Gb InfiniBand (back-end RDMA fabric). Flapping ports disrupt distributed training by causing NCCL timeouts and Spanning Tree Protocol (STP) reconvergence events.

## Common Causes

- **Physical layer:** Damaged fiber optic cable, dirty transceiver, loose QSFP module, bent pins
- **Transceiver failure:** Failing or incompatible optic (check vendor compatibility list)
- **Switch software:** ASIC errors, firmware bugs (check known issues for current NOS version)
- **Oversubscription:** Excessive PFC (Priority Flow Control) pause frames causing link resets
- **Environmental:** Vibration from adjacent rack work, temperature fluctuations in cabling tray

## Detection

Alerts fire via Prometheus on `switch_interface_flap_count` exceeding 3 transitions in 5 minutes:

    ssh admin@<switch-ip> "show interface status"
    ssh admin@<switch-ip> "show logging | grep 'link state'"
    ssh admin@<switch-ip> "show interface <port> counters errors"

## Step-by-Step Remediation

### 1. Identify the Flapping Port

Check the network monitoring dashboard at `netmon.dc-tokyo-01.dc-internal.local`. Identify the specific switch, port, and connected device. Correlate with recent change tickets (fiber moves, transceiver replacements).

### 2. Check Physical Layer

1. Inspect the transceiver and cable at both ends. Look for LED indicators on the transceiver (amber = fault).
2. Check transceiver DOM (Digital Optical Monitoring) readings: `show interface <port> transceiver`. Rx/Tx power should be within -1 to -12 dBm for 100GbE SR4.
3. Reseat the QSFP module. If flapping persists, swap transceiver with a known-good spare from dc-ops-tokyo spares cabinet (Rack A01, shelf 3).

### 3. Software Mitigation

If physical layer checks pass, apply dampening to prevent STP reconvergence storms:

    configure terminal
    interface <port>
    dampening 5 1000 2000 20

This sets a 5-second half-life, 1000 suppress threshold, 2000 reuse threshold, and 20-second max suppress time.

### 4. Assess STP Impact

If the flapping port is an uplink (ToR to spine), STP reconvergence may have occurred. Verify convergence state:

    show spanning-tree summary
    show spanning-tree topology-change

During reconvergence (typically 2-30 seconds with RSTP), all traffic through the affected switch is disrupted. If distributed training jobs report NCCL timeouts during this window, coordinate with ml-platform for job restart.

### 5. Hardware Replacement Decision

Replace the switch port or transceiver if:

- Flapping recurs after transceiver swap (indicates switch ASIC port failure)
- DOM readings show power outside spec even with new transceiver
- Error counters show persistent CRC or FCS errors above 100/hour

For full ToR switch replacement, coordinate a maintenance window with dc-ops-tokyo (minimum 2-hour window, requires draining all nodes in the rack).

## Impact on Distributed Training

NCCL all-reduce operations over InfiniBand have a default timeout of 30 minutes (`NCCL_TIMEOUT`). Brief flaps under 5 seconds may cause temporary stalls but training can recover. Sustained flapping or STP reconvergence exceeding timeout will crash the entire distributed job. Recommend reducing `NCCL_TIMEOUT` to 600s to fail fast and allow job rescheduling on healthy fabric.

## Escalation

- **P2 (single port, non-critical):** network-infra on-call, resolve within 4 hours.
- **P1 (uplink or multiple ports):** Page dc-ops-tokyo and network-infra. If InfiniBand fabric affected, also page gpu-infra.

**Contact:** network-infra on-call: +81-3-XXXX-4030 | Mellanox TAC: mellanox-support-apac@nvidia.com
