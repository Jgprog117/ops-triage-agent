# Incident Response Template

**Facility:** dc-tokyo-01 | **Owner:** dc-ops-tokyo | **Last updated:** 2026-03-15

## Overview

This runbook defines the standard incident response process for dc-tokyo-01. All incidents P1 through P3 must follow this format. P4 issues are tracked as tickets and do not require the full incident response process.

## Incident Declaration

An incident is declared when any of the following are true:

- An automated P1 or P2 alert fires from the monitoring stack
- An on-call engineer identifies a problem meeting P1-P3 severity criteria
- A user reports a widespread issue confirmed by the ops team

To declare an incident, post in `#dc-incidents-tokyo` using this format:

```
INCIDENT DECLARED
Severity: P<1-3>
Title: <brief description>
Impact: <what is affected, estimated scope>
Incident Commander: <your name>
Bridge: <Slack thread or video call link>
```

## Roles During an Incident

- **Incident Commander (IC):** Owns the incident lifecycle. Coordinates response, delegates tasks, manages communication. The dc-ops-tokyo on-call is the default IC.
- **Technical Lead:** The engineer actively debugging the root cause. Reports findings to the IC.
- **Communications Lead:** Posts status updates to stakeholders. For P1, this is a dedicated role; for P2-P3, the IC handles communications.

## Status Update Cadence

| Severity | Internal Update (Slack) | External Update (Status Page) |
|----------|------------------------|-------------------------------|
| P1 | Every 15 minutes | Every 30 minutes |
| P2 | Every 30 minutes | Every 60 minutes |
| P3 | Every 2 hours | As needed |

Status update template:
```
INCIDENT UPDATE - <title>
Severity: P<X> | Duration: <time since declaration>
Status: Investigating / Identified / Mitigated / Resolved
Current understanding: <1-2 sentences>
Next steps: <what is being done>
ETA to resolution: <estimate or "unknown">
```

## Resolution and Closure

1. When the issue is resolved, post a final update with `Status: Resolved`
2. Return all affected nodes to service per the node_health_check runbook
3. Verify monitoring shows nominal state for 15 minutes before closing
4. Update the incident ticket with a timeline and final root cause

## Post-Mortem Requirements

All P1 and P2 incidents require a post-mortem document within 5 business days. P3 incidents require a post-mortem if the resolution time exceeded the SLA.

The post-mortem must include:

- **Timeline:** Minute-by-minute account from detection to resolution
- **Root cause:** Technical explanation of what failed and why
- **Impact:** Number of affected nodes, jobs, and user-facing impact hours
- **Detection:** How the issue was found and whether monitoring caught it
- **Action items:** Concrete follow-ups with owners and due dates to prevent recurrence
- **Lessons learned:** What went well, what could be improved in the response

Post-mortems are reviewed in the weekly dc-ops-tokyo team meeting and stored in the `post-mortems/` directory of the ops wiki. The post-mortem process is blameless -- the goal is systemic improvement, not individual accountability.
