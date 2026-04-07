"""Analyze triage results in the local SQLite DB against expected behavior.

Joins alerts (with raw_data scenario tag) against audit_log (triage_completed events)
and prints a per-alert ground-truth-vs-prediction table plus aggregate metrics.

Run from project root:
    python scripts/eval_analyze.py
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ops_agent.db"


# What the EVALUATION.md table says we should expect.
# Conservative: matches what the eval framework asserts.
EXPECTED_BY_SCENARIO = {
    "thermal_cascade": {"class": "critical_escalation", "escalate": True},
    "gpu_hardware_failure": {"class": "critical_escalation", "escalate": True},
    "network_partition": {"class": "critical_escalation", "escalate": True},
    "storage_degradation": {"class": "incident", "escalate": False},
    "power_anomaly": {"class": "acknowledged", "escalate": False},
}

# A more nuanced view: what the system prompt's classification rules actually say.
# Used to identify cases where the eval table and the prompt disagree.
PROMPT_OVERRIDES = {
    # Step 3 of storage_degradation is a checkpoint write failure, which the
    # prompt explicitly lists as a data-loss criterion -> critical_escalation.
    ("storage_degradation", 3): {"class": "critical_escalation", "escalate": True},
    ("storage_degradation", 4): {"class": "critical_escalation", "escalate": True},
}


def load_triages() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT a.id, a.timestamp, a.severity, a.category, a.message, a.raw_data,
               al.details
        FROM alerts a
        JOIN audit_log al ON al.entity_id = a.id
        WHERE al.event_type='triage_completed'
        ORDER BY a.timestamp
        """
    )
    rows = []
    for r in cur:
        raw = json.loads(r["raw_data"] or "{}")
        details = json.loads(r["details"] or "{}")
        rows.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "severity": r["severity"],
            "category": r["category"],
            "message": r["message"],
            "scenario": raw.get("scenario", "isolated"),
            "scenario_step": raw.get("scenario_step"),
            "isolated": bool(raw.get("isolated")),
            "predicted_class": details.get("classification"),
            "predicted_escalate": details.get("escalation_required"),
        })
    conn.close()
    return rows


def expected_for(row: dict) -> dict:
    """Return the expected classification and escalation per the eval framework
    (with prompt overrides for cases the table is too coarse to capture)."""
    if row["isolated"]:
        if row["severity"] == "info":
            return {"class": "noise", "escalate": False}
        if row["severity"] == "warning":
            return {"class": "acknowledged", "escalate": False}
        # isolated critical: not in the table, treat as incident-or-better
        return {"class": "incident", "escalate": False, "lenient": True}

    scenario = row["scenario"]
    step = row["scenario_step"]
    if (scenario, step) in PROMPT_OVERRIDES:
        return PROMPT_OVERRIDES[(scenario, step)]
    return EXPECTED_BY_SCENARIO.get(scenario, {"class": "?", "escalate": False})


def is_class_hit(predicted: str, expected: dict) -> bool:
    if expected.get("lenient"):
        # For ambiguous cases, accept anything other than "noise" / "acknowledged"
        return predicted in ("incident", "critical_escalation")
    return predicted == expected["class"]


def is_escalation_hit(predicted: bool, expected: dict) -> bool:
    return bool(predicted) == bool(expected.get("escalate"))


def main() -> None:
    rows = load_triages()
    print(f"Loaded {len(rows)} completed triages\n")

    print(f"{'#':>2}  {'severity':<8} {'scenario':<22} {'step':>4}  "
          f"{'predicted':<22} {'expected':<22}  class  esc")
    print("-" * 100)

    class_hits = 0
    esc_hits = 0
    by_scenario_total: Counter = Counter()
    by_scenario_hits: Counter = Counter()
    confusion: defaultdict = defaultdict(int)

    for i, r in enumerate(rows, 1):
        exp = expected_for(r)
        pred_class = r["predicted_class"] or "?"
        ch = is_class_hit(pred_class, exp)
        eh = is_escalation_hit(r["predicted_escalate"], exp)
        if ch:
            class_hits += 1
        if eh:
            esc_hits += 1

        scenario_label = r["scenario"]
        if r["isolated"]:
            scenario_label = f"isolated/{r['severity']}"
        by_scenario_total[scenario_label] += 1
        if ch:
            by_scenario_hits[scenario_label] += 1
        confusion[(exp["class"], pred_class)] += 1

        step_str = str(r["scenario_step"]) if r["scenario_step"] else "-"
        print(f"{i:>2}  {r['severity']:<8} {scenario_label:<22} {step_str:>4}  "
              f"{pred_class:<22} {exp['class']:<22}  "
              f"{'OK' if ch else 'XX':<5} {'OK' if eh else 'XX'}")

    n = len(rows) or 1
    print("\n" + "=" * 60)
    print(f"Aggregate classification accuracy: {class_hits}/{n} = {class_hits/n:.0%}")
    print(f"Aggregate escalation accuracy:     {esc_hits}/{n} = {esc_hits/n:.0%}")

    print("\nPer-scenario classification:")
    for scen in sorted(by_scenario_total):
        h = by_scenario_hits[scen]
        t = by_scenario_total[scen]
        print(f"  {scen:<24} {h}/{t} = {h/t:.0%}")

    print("\nConfusion matrix (expected -> predicted):")
    classes = ["noise", "acknowledged", "incident", "critical_escalation"]
    print(f"{'expected':<22} | " + " ".join(f"{c[:6]:>8}" for c in classes))
    for exp_c in classes:
        row_str = f"{exp_c:<22} | "
        for pred_c in classes:
            row_str += f"{confusion[(exp_c, pred_c)]:>8} "
        print(row_str)

    # Escalation rates
    pred_escalations = sum(1 for r in rows if r["predicted_escalate"])
    expected_escalations = sum(1 for r in rows if expected_for(r).get("escalate"))
    print(f"\nEscalations predicted: {pred_escalations}/{n} ({pred_escalations/n:.0%})")
    print(f"Escalations expected:  {expected_escalations}/{n} ({expected_escalations/n:.0%})")


if __name__ == "__main__":
    main()
