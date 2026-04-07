# Evaluation: Triage Agent Accuracy

## Methodology

Each triage is assessed on three dimensions:

- **Classification** — Did the agent pick the right category?
- **Correlation** — Did it find related alerts from the same scenario?
- **Escalation** — Did it escalate when appropriate, and not when it shouldn't?

Ground truth comes from the simulator's scenario tags (`raw_data.scenario` /
`scenario_step`) and the expected-behavior table below. Predictions come from
`audit_log.triage_completed` events written by the agent at the end of each run.
The analysis script (`scripts/eval_analyze.py`) joins the two and prints both a
per-alert table and aggregate metrics. The same DB powers the live dashboard, so
results are reproducible from a fresh run with `python3 scripts/eval_analyze.py`.

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

> Note: step 3 of `storage_degradation` is a checkpoint write failure, which
> the system prompt explicitly lists as a data-loss criterion. The eval grader
> overrides the table for that one step to expect `critical_escalation` rather
> than `incident`. Step 1 of `network_partition` is intentionally evaluated
> against the table even though the prompt would let the agent be more
> conservative — see "Findings" below.

## Results

**Sample**: 27 completed triages run against `claude-sonnet-4-6` — 17 from
ambient simulator runs (mixed scenarios + isolated alerts) plus a focused
top-up batch of 10 (`scripts/eval_run.py`) that filled in
`gpu_hardware_failure` (missing from the ambient runs) and added isolated
warning cases.

### Aggregate

| Metric | Result |
|---|---|
| Classification accuracy | **15 / 27 (56%)** |
| Escalation accuracy | **14 / 27 (52%)** |
| Predicted escalations | **24 / 27 (89%)** |
| Expected escalations | 15 / 27 (56%) |

The agent escalates 89% of the time when it should escalate 56% of the time —
a **+33 pp over-escalation gap**. This is the dominant failure mode.

### Per-scenario classification accuracy

| Scenario | Hits | Total | Accuracy | Failure mode |
|---|---|---|---|---|
| thermal_cascade | 3 | 3 | **100%** | — |
| gpu_hardware_failure | 7 | 8 | **88%** | step-1 ECC warning classified as `incident` instead of escalating (conservative) |
| isolated/critical | 2 | 2 | **100%** | — |
| network_partition | 2 | 3 | 67% | step-1 port-flap warning conservatively classified as `incident` instead of `critical_escalation` |
| storage_degradation | 1 | 5 | **20%** | steps 1–2 (SMART warnings, I/O latency) over-escalated to `critical_escalation` |
| power_anomaly | 0 | 2 | **0%** | both steps over-escalated (voltage fluctuation + UPS engagement on a single PDU) |
| isolated/warning | 0 | 4 | **0%** | every isolated warning was lifted to `incident` or `critical_escalation`, never `acknowledged` |

### Confusion matrix (expected → predicted)

```
expected               | noise | acknowledged | incident | critical_escalation
-----------------------+-------+--------------+----------+--------------------
noise                  |   0   |      0       |    0     |         0
acknowledged           |   0   |      0       |    1     |         5
incident               |   0   |      0       |    1     |         5
critical_escalation    |   0   |      0       |    2     |        13
```

The agent never picks `noise` or `acknowledged`. Every alert that warrants a
`noise` or `acknowledged` verdict gets lifted at least one step. The diagonal
weight is concentrated in the bottom-right cell — the agent is essentially a
two-class classifier (`incident` / `critical_escalation`) with a strong bias
toward the latter.

### Failure case study: false-positive cascade rollup

The clearest failure pattern shows up when an unrelated alert lands in a rack
that already had real activity in the prior 15 minutes. Walking through one
example from the eval batch:

1. **16:49–16:52** — A `gpu_hardware_failure` scenario emitted four alerts on
   `node-gpu-rack12-02`: ECC warning → uncorrectable ECC critical → NVLink
   peer warning → node drained. The agent correctly classified all four as
   `critical_escalation`.
2. **16:53** — A *separate, unrelated* `memory_usage_percent` warning was
   generated on the same host (`node-gpu-rack12-02`). This is the kind of
   alert the eval table expects to be `acknowledged`. The agent classified it
   as `critical_escalation` — defensible, since memory pressure on a draining
   node could plausibly be a downstream effect.
3. **16:55** — Another isolated `memory_usage_percent` warning was generated,
   this time on a *different host in the same rack* (`node-gpu-rack12-04`).
   There is no causal mechanism linking GPU-1 ECC errors on `rack12-02` to
   memory pressure on `rack12-04`. The agent created incident
   `INC-A06FFCACF0FD` titled
   *"rack-12 GPU Hardware Failure Cascade: Uncorrectable ECC + NVLink Failure
   on node-gpu-rack12-02, Memory Pressure on node-gpu-rack12-04"*, correlated
   it with all six prior alerts in the rack, and escalated.

The root cause is that `query_recent_alerts` returns everything in the rack
within the 15-minute window, and the agent treats temporal + spatial proximity
as evidence of causation. There is no notion of *which prior incident a new
alert belongs to* or whether the host is even in a degraded state. In
production this would mean any follow-on alert in a rack that recently had a
real cascade gets paged as P1 for ~15 minutes after the original incident.

Other recurring failure shapes:

- **Storage SMART warnings classified as data-loss events.** The system prompt
  explicitly lists "uncorrectable ECC, RAID degradation, checkpoint write
  failures" as the data-loss criteria — SMART pre-failure warnings are not on
  that list, but the agent generalises them anyway. Steps 1–2 of every
  `storage_degradation` run get lifted to `critical_escalation`.
- **Power anomalies on a single PDU treated as multi-PDU events.** The prompt
  reserves escalation for *multiple* PDUs; the agent escalates on the first
  voltage fluctuation regardless. The "(recovers)" semantics of the
  `power_anomaly` scenario are completely lost.

## Findings

1. **Classification accuracy is 56%, escalation accuracy is 52%.** Both are
   well below where this would need to be for unattended on-call use. They are
   adequate for "human reviews every recommendation" workflows.
2. **Recall on real escalations is effectively 100%; precision is the
   problem.** Of 15 alerts that should have been `critical_escalation`, the
   agent missed only one (a step-1 port-flap warning, which is a defensible
   conservative call). The agent does not under-react to real incidents.
3. **The agent is biased toward action over restraint.** It never picks
   `acknowledged`, and 89% of triages end in escalation against an expected
   rate of 56%. This is consistent across all four runs of "isolated warning"
   alerts, every one of which was lifted out of the `acknowledged` bucket.
4. **Correlation is too aggressive.** The 15-minute / same-rack window pulls
   in unrelated alerts and the model treats co-location as causation. This is
   what causes the over-escalation, not (only) prompt wording — even with a
   stricter prompt, the tool would still surface noise.
5. **The strongest scenarios are the ones with critical-severity alerts:**
   `thermal_cascade` (100%), `gpu_hardware_failure` (88%), isolated criticals
   (100%). The model's prior on "this is bad" is well-calibrated when severity
   is high; it is poorly calibrated when severity is `warning`.

## Improvement ideas

Concrete fixes mapped to the failures above:

- **Stricter correlation tool semantics.** Have `query_recent_alerts` return
  alerts grouped by *open incident* rather than by rack/window, and pass an
  `incident_open` flag the agent can reason about. Caller-side filtering would
  cut most of the rollup false positives without prompt changes.
- **Few-shot examples for `acknowledged`.** The agent has no in-context
  examples of correctly *de-escalating* a warning. Two or three negative
  examples (single isolated warning, voltage fluctuation that recovers, SMART
  warning without I/O degradation) would likely shift the bias measurably.
- **Pull thresholds out of the prompt** into a configuration table the agent
  reads via tool call. Hardcoded `95°C` / `3+ correlated criticals in 30 min`
  is brittle and prevents per-tenant tuning.
- **Structured output mode** (`response_format`) to eliminate the parse-retry
  fallback path, which currently downgrades any parse failure to a silent
  `acknowledged`.
- **Add a `host_health` check** before correlation: if the host has no open
  incident and was healthy in the last hour, weight prior alerts much lower
  in the reasoning.
- **Per-category triage templates** so storage SMART warnings get evaluated
  against storage-specific criteria (paired with I/O metrics) rather than
  collapsed into the general "potential data loss" bucket.

Re-run the evaluation after each change with:

```bash
python3 scripts/eval_analyze.py
```
