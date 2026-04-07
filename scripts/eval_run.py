"""Run a balanced batch of triages directly to expand the eval dataset.

Targets the gaps in the existing data: gpu_hardware_failure (currently 0),
plus a couple of isolated warning/critical cases.

Each triage is invoked synchronously through the same triage_alert function
the simulator uses, so it writes to the same DB and audit_log. The eval
analysis script can then re-read the combined data.

Run from project root:
    python3 scripts/eval_run.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.triage import triage_alert
from backend.db.database import close_database, init_database, insert_alert, insert_audit_log
from backend.db.seed import seed_host_data
from backend.knowledge.rag import init_knowledge_base
from backend.simulator.engine import _generate_isolated_alert
from backend.simulator.scenarios import gpu_hardware_failure

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("eval_run")


def make_alert_dict(scenario_name: str, step_index: int, scenario_alert) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "severity": scenario_alert.severity,
        "category": scenario_alert.category,
        "component": scenario_alert.component,
        "host": scenario_alert.host,
        "rack": scenario_alert.rack,
        "datacenter": "dc-tokyo-01",
        "metric_name": scenario_alert.metric_name,
        "metric_value": scenario_alert.metric_value,
        "threshold": scenario_alert.threshold,
        "message": scenario_alert.message,
        "raw_data": {**scenario_alert.raw_data, "scenario": scenario_name, "scenario_step": step_index + 1, "eval_run": True},
        "triage_status": "pending",
    }


async def emit_and_triage(alert: dict) -> dict | None:
    await insert_alert(alert)
    await insert_audit_log("alert_received", alert["id"], {"severity": alert["severity"], "category": alert["category"]})

    if alert["severity"] == "info":
        logger.info("[skip-info] %s", alert["message"])
        return None

    t0 = time.time()
    result = await triage_alert(alert)
    elapsed = time.time() - t0
    if result is None:
        logger.warning("Triage returned None for alert %s", alert["id"])
        return None
    logger.info("[%s in %.1fs] %s",
                result.classification, elapsed, alert["message"][:60])
    return {
        "alert_id": alert["id"],
        "scenario": alert["raw_data"].get("scenario", "isolated"),
        "step": alert["raw_data"].get("scenario_step"),
        "severity": alert["severity"],
        "predicted_class": result.classification,
        "predicted_escalate": result.escalation_required,
        "correlated_alert_ids": result.correlated_alert_ids,
        "elapsed_seconds": round(elapsed, 2),
    }


async def run_scenario(scenario_func, label: str) -> list[dict]:
    scen = scenario_func()
    logger.info("=== Running %s ===", label)
    results = []
    for i, step in enumerate(scen.alerts):
        alert = make_alert_dict(scen.name, i, step)
        # Brief pause between alerts so timestamps differ and tools see ordering.
        if i > 0:
            await asyncio.sleep(2)
        r = await emit_and_triage(alert)
        if r:
            results.append(r)
    return results


async def run_isolated(severity: str, count: int = 1) -> list[dict]:
    results = []
    for _ in range(count):
        # Force severity by retrying generation
        for _attempt in range(20):
            alert = _generate_isolated_alert()
            if alert["severity"] == severity:
                break
        else:
            logger.warning("Could not generate %s isolated alert after 20 attempts", severity)
            continue
        logger.info("=== Running isolated %s ===", severity)
        r = await emit_and_triage(alert)
        if r:
            results.append(r)
        await asyncio.sleep(1)
    return results


async def main() -> None:
    await init_database()
    await seed_host_data()
    await asyncio.to_thread(init_knowledge_base)
    logger.info("Eval run setup complete")

    all_results = []

    # 1. Two gpu_hardware_failure scenarios (missing entirely from existing data)
    all_results.extend(await run_scenario(gpu_hardware_failure, "gpu_hardware_failure #1"))
    all_results.extend(await run_scenario(gpu_hardware_failure, "gpu_hardware_failure #2"))

    # 2. A couple of isolated warnings (existing data has 2, both misclassified — confirm)
    all_results.extend(await run_isolated("warning", count=2))

    # Save raw results to disk for the analysis script
    out_path = "data/eval_run_results.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    logger.info("Wrote %d new triage results to %s", len(all_results), out_path)

    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
