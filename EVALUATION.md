# Evaluation: Triage Agent Accuracy

## Methodology

Each triage is assessed on three dimensions:

- **Classification**: Did the agent pick the right category? (noise / acknowledged / incident / critical_escalation)
- **Correlation**: Did the agent find related alerts from the same scenario?
- **Escalation decision**: Did the agent escalate when it should, and not when it shouldn't?

## Ground Truth per Scenario

| Scenario | Expected Classification | Should Correlate | Should Escalate | Expected Team |
|---|---|---|---|---|
| thermal_cascade | critical_escalation | 3-4 alerts (same rack, thermal + gpu) | Yes | dc-ops-tokyo |
| gpu_hardware_failure | critical_escalation | 3-4 alerts (same host, gpu) | Yes | gpu-infra |
| network_partition | critical_escalation | 3-4 alerts (same rack, network + gpu) | Yes | network-ops |
| storage_degradation | incident | 2-4 alerts (storage category) | Maybe | storage-team |
| power_anomaly | incident or acknowledged | 2-4 alerts (same rack, power) | No (self-recovers) | power-facilities |
| isolated (info) | noise | 0 | No | - |
| isolated (warning) | acknowledged | 0-1 | No | - |
| isolated (critical) | incident | 0-1 | Maybe | varies |

## Results

> Run the system (`uvicorn backend.main:app --port 8000`) and observe 15-20 triage cycles. Record results below.

| # | Scenario | Alert Severity | Expected Class. | Actual Class. | Correlated? | Escalated? | Correct? | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 4 | | | | | | | | |
| 5 | | | | | | | | |
| 6 | | | | | | | | |
| 7 | | | | | | | | |
| 8 | | | | | | | | |
| 9 | | | | | | | | |
| 10 | | | | | | | | |
| 11 | | | | | | | | |
| 12 | | | | | | | | |
| 13 | | | | | | | | |
| 14 | | | | | | | | |
| 15 | | | | | | | | |

## Analysis

**Classification accuracy**: _/15 correct (_%)

**Correlation accuracy**: _/_ scenarios correctly correlated

**Escalation accuracy**: _/_ correct escalation decisions

### Common Failure Modes

_Fill in after running:_
- Does the agent over-escalate isolated warnings?
- Does it miss cross-category correlations (e.g., thermal + gpu in thermal_cascade)?
- Does it correctly identify self-recovering scenarios (power_anomaly)?

### What Would Improve Accuracy

- Few-shot examples in the system prompt
- Structured output mode (response_format) to eliminate parsing failures
- Explicit correlation scoring in the prompt
- Runbook-specific triage templates per category
