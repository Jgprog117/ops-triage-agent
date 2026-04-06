# Power / PDU Anomaly Runbook

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo / facilities-tokyo | **Last updated:** 2026-03-20  
**Severity:** P2 (anomaly detected) / P1 (power loss risk)

## Power Architecture Overview

dc-tokyo-01 uses a 2N redundant power architecture:

- **Utility feeds:** Dual independent feeds from TEPCO (Tokyo Electric Power), each 2 MW capacity.
- **UPS:** 4x Eaton 9395P 600kVA UPS units (2 per feed), providing 10 minutes runtime at full load on battery.
- **PDUs:** Rack-level intelligent PDUs (ServerTech PRO4X), dual PDU per rack (A-feed and B-feed). Each PDU provides 3-phase 200V at 60A per phase.
- **GPU nodes draw:** Approximately 6-10 kW per node (8x A100/H100 + CPUs + networking).

## Voltage and Current Thresholds

| Parameter | Normal Range | Warning | Critical |
|-----------|-------------|---------|----------|
| Input Voltage (per phase) | 195-205V | < 190V or > 210V | < 185V or > 215V |
| Phase Current | 10-50A | > 48A (80% rated) | > 54A (90% rated) |
| Phase Imbalance | < 10% | > 15% | > 20% |
| Power Factor | > 0.95 | < 0.92 | < 0.88 |
| UPS Battery Charge | 100% | < 80% | < 50% |
| UPS Battery Temp | 20-25C | > 30C | > 35C |

## Detection

PDU metrics are collected via SNMP by `snmp_exporter` and visualized on `grafana.dc-tokyo-01.aiand.internal/d/power-monitoring`. UPS status is monitored via Eaton IPM (Intelligent Power Manager) at `ups-mgmt.dc-tokyo-01.aiand.internal`.

Check PDU status manually:

    snmpwalk -v2c -c <community> <pdu-ip> .1.3.6.1.4.1.1718   # ServerTech MIB
    curl -s http://<pdu-ip>/api/v1/outlets | jq .                # REST API

## Remediation Procedures

### 1. Single PDU Anomaly (Voltage Out of Range)

1. Confirm which feed (A or B) is affected via the monitoring dashboard.
2. Verify the alternate feed is healthy and carrying load. All nodes should continue operating on the redundant feed.
3. Check the UPS feeding the anomalous PDU path at `ups-mgmt.dc-tokyo-01.aiand.internal`. If the UPS has transferred to battery, note the estimated runtime.
4. Contact facilities-tokyo to check the upstream breaker panel and transformer.
5. If the anomaly is on the utility feed (upstream of UPS), contact TEPCO liason at facilities-tokyo.

### 2. UPS Failover Event

When a UPS transfers to battery:

1. An automatic P1 alert pages dc-ops-tokyo and facilities-tokyo.
2. Confirm the UPS event on the Eaton IPM dashboard. Note battery charge level and estimated runtime.
3. If battery runtime is below 5 minutes and utility power is not restored, initiate load shedding (see below).
4. Document the transfer event in the incident log, including timestamp and cause if known.

### 3. Load Shedding Procedure

If both utility feeds fail and UPS battery runtime drops below 5 minutes:

1. **Priority 1 (shed first):** Non-production workloads, dev/test GPU nodes. Issue graceful shutdown: `kubectl drain` dev nodes.
2. **Priority 2:** Inference serving nodes. Redirect traffic to dc-osaka-02 via DNS failover.
3. **Priority 3 (shed last):** Active training runs. Signal checkpoint and graceful stop. Training state is recoverable.
4. **Never shed:** Network core switches, storage controllers, management plane. These remain powered until generator starts or controlled shutdown.

Emergency generator (2 MW diesel) has a 30-second auto-transfer switch (ATS). Under normal failure, the generator covers the gap after UPS battery. Load shedding is only necessary if the generator fails to start.

## Escalation

- **P2 (anomaly, redundancy intact):** dc-ops-tokyo on-call, investigate within 1 hour.
- **P1 (power loss risk or UPS on battery):** Page dc-ops-tokyo lead, facilities-tokyo lead, and site manager. If generator fails, escalate to ai& executive on-call.

**Contact:** facilities-tokyo: +81-3-XXXX-4050 | Eaton support: eaton-ups-apac@eaton.com | TEPCO liason: via facilities-tokyo lead
