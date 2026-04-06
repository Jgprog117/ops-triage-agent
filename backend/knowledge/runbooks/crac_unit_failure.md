# CRAC Unit Failure Runbook

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo / facilities-tokyo | **Last updated:** 2026-03-18  
**Severity:** P2 (single unit, redundancy intact) / P1 (multiple units or rising temps)

## Cooling Architecture

dc-tokyo-01 uses a chilled water CRAC (Computer Room Air Conditioning) system with N+1 redundancy per cooling zone:

- **Zone A (GPU compute rows 1-4):** 6x Liebert CW160 units, 160 kW each. Any 5 of 6 can handle full thermal load.
- **Zone B (GPU compute rows 5-8):** 6x Liebert CW160 units, same N+1 configuration.
- **Zone C (storage and network):** 3x Liebert CW080 units, 80 kW each, N+1.
- **Chilled water supply:** Dual chiller plant on roof, 7C supply / 12C return, redundant pumps.

Each CRAC unit delivers cold air into the raised floor plenum at 15-18C. Hot aisle containment captures exhaust air at 35-42C and returns it to CRAC intakes.

## Temperature Monitoring

Sensors at cold aisle, hot aisle, and rack inlet positions feed into the BMS (Building Management System) at `bms.dc-tokyo-01.dc-internal.local`.

| Location | Normal | Warning | Critical |
|----------|--------|---------|----------|
| Cold Aisle Inlet | 18-22C | > 25C | > 27C |
| Rack Inlet (GPU) | 20-27C | > 30C | > 32C |
| Hot Aisle | 35-42C | > 45C | > 50C |
| Raised Floor Plenum | 15-18C | > 20C | > 23C |

## Detection

CRAC unit faults are reported via BACnet to the BMS and trigger Prometheus alerts via `bacnet_exporter`. The Liebert iCOM controller at `crac-mgmt.dc-tokyo-01.dc-internal.local` provides unit-level diagnostics including compressor status, fan speed, refrigerant pressure, and water valve position.

## Remediation Procedures

### 1. Single CRAC Unit Failure (Redundancy Intact)

1. Confirm the faulted unit on the iCOM dashboard. Note the fault code (common: E01 high discharge pressure, E04 low water flow, E07 fan motor fault).
2. Verify the remaining units in the zone have ramped up to compensate. Cold aisle temperature should stabilize within 5 minutes.
3. If cold aisle temperature remains stable (below 25C), this is a P2 event. Contact facilities-tokyo to dispatch HVAC technician within 4 hours.
4. Attempt a remote restart via iCOM: select the faulted unit and press "Reset and Restart." Some transient faults (E01 from momentary chilled water pressure drop) will clear on restart.

### 2. Multiple CRAC Units Down or Rising Temperatures

If two or more CRAC units fail in the same zone, or if cold aisle temperature exceeds 27C:

1. **Immediately page dc-ops-tokyo lead and facilities-tokyo lead.** This is a P1 event.
2. Verify chilled water supply is operational. Check chiller plant status at `bms.dc-tokyo-01.dc-internal.local/chillers`. If chilled water supply temp exceeds 10C, the issue is upstream.
3. Open the hot aisle containment doors in the affected zone to allow ambient mixing as a temporary measure. This is not ideal but slows the rate of temperature rise.
4. If temperature continues rising, initiate emergency thermal load reduction (see below).

### 3. Emergency Thermal Procedure

**Trigger:** Rack inlet temperature exceeds 32C and is still rising.

1. Apply GPU power caps across all nodes in the affected zone:

       ansible -i dc-tokyo-01 zone_a_gpu_nodes -m shell -a "nvidia-smi -pl 300"

2. If temperature exceeds 35C at rack inlet, begin graceful node shutdown starting with lowest-priority workloads. Coordinate with ml-platform for training job checkpoints.
3. If temperature exceeds 40C at rack inlet, initiate emergency power-off for the affected zone via the EPO (Emergency Power Off) panel. **Warning:** This is a last resort and will cause hard shutdown of all equipment in the zone.

## Temperature Escalation Matrix

| Rack Inlet Temp | Action | Timeline |
|-----------------|--------|----------|
| 27C | Alert dc-ops-tokyo, investigate | Immediate |
| 30C | Apply GPU power caps, notify ml-platform | Within 5 min |
| 32C | Begin draining non-critical workloads | Within 10 min |
| 35C | Graceful shutdown of all GPU nodes in zone | Within 15 min |
| 40C | Emergency power-off (EPO) for zone | Immediate |

## Post-Incident

After cooling is restored, allow the room to return to normal temperature range (cold aisle below 22C) for at least 15 minutes before powering nodes back on. GPU nodes should be brought up gradually (4 nodes per minute) to avoid inrush current spikes on the PDUs.

## Escalation

- **P2 (single unit, stable temps):** facilities-tokyo on-call, repair within 4 hours.
- **P1 (rising temps or multi-unit failure):** Page dc-ops-tokyo lead, facilities-tokyo lead, and site manager. If EPO is triggered, notify executive on-call and prepare incident report.

**Contact:** facilities-tokyo on-call: +81-3-XXXX-4050 | Liebert/Vertiv service: vertiv-apac-emergency@vertiv.com | Chiller plant: managed by facilities-tokyo
