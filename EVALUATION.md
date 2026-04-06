# Evaluation: Triage Agent Accuracy

## Methodology

Each triage is assessed on three dimensions:

- **Classification** — Did the agent pick the right category?
- **Correlation** — Did it find related alerts from the same scenario?
- **Escalation** — Did it escalate when appropriate, and not when it shouldn't?

## Expected behavior per scenario

| Scenario | Expected class. | Should correlate | Escalate? |
|---|---|---|---|
| thermal_cascade | critical_escalation | 3-4 alerts | Yes |
| gpu_hardware_failure | critical_escalation | 3-4 alerts | Yes |
| network_partition | critical_escalation | 3-4 alerts | Yes |
| storage_degradation | incident | 2-4 alerts | Maybe |
| power_anomaly | acknowledged | 2-4 alerts | No (recovers) |
| isolated info | noise | 0 | No |
| isolated warning | acknowledged | 0-1 | No |

## Results

> Run the system and observe 10-15 triage cycles. Record each result and compare against the expected behavior above.

## Improvement ideas

- Few-shot examples in the system prompt for each classification level
- Structured output mode (`response_format`) to eliminate parsing failures
- Runbook-specific triage templates per alert category
