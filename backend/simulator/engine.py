"""Background alert generator that drives the rest of the system.

The simulator runs forever in a single asyncio task started from the
application lifespan. On each iteration it sleeps for a randomized
interval and then either emits a single isolated alert or runs a
multi-step :class:`Scenario` from :mod:`backend.simulator.scenarios`.

The simulator does not import the triage agent directly; the triage
function is plugged in through :func:`set_triage_callback` so the
import graph stays acyclic.
"""

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from backend.config import settings
from backend.db.database import insert_alert, insert_audit_log
from backend.simulator.components import (
    CATEGORY_METRICS,
    CRAC_UNITS,
    GPU_COMPONENTS,
    PDU_UNITS,
    RACK_HOSTS,
    RACKS,
)
from backend.simulator.scenarios import pick_scenario
from backend.sse.broadcaster import broadcast_alert

logger = logging.getLogger(__name__)

# Set by the triage agent module via set_triage_callback to avoid a circular import.
_triage_callback: Callable[[dict], Awaitable[object]] | None = None
_background_tasks: set[asyncio.Task] = set()


def set_triage_callback(callback: Callable[[dict], Awaitable[object]]) -> None:
    """Registers the triage entry point invoked for warning/critical alerts.

    Called once at startup from :func:`backend.main.lifespan`. Kept as
    a setter rather than an import so the simulator package does not
    have to know about the agent package.

    Args:
        callback: An ``async`` function taking the alert dict and
            performing triage. Its return value is discarded.
    """
    global _triage_callback
    _triage_callback = callback


def _generate_isolated_alert() -> dict:
    """Builds a single, randomly chosen alert with no scenario context.

    Picks a random category, metric, rack, host, and severity (weighted
    40/40/20 across info/warning/critical), samples a metric value
    consistent with that severity, and selects a category-appropriate
    component name.

    Returns:
        A fully populated alert dict ready for insertion via
        :func:`_emit_alert`.
    """
    category = random.choice(list(CATEGORY_METRICS.keys()))
    metric = random.choice(CATEGORY_METRICS[category])
    rack = random.choice(RACKS)
    host = random.choice(RACK_HOSTS[rack])
    severity = random.choices(
        ["info", "warning", "critical"],
        weights=[0.4, 0.4, 0.2],
        k=1,
    )[0]

    if severity == "info":
        value = round(random.uniform(metric.normal_min, metric.normal_max), 2)
    elif severity == "warning":
        value = round(random.uniform(metric.warning_threshold * 0.9, metric.warning_threshold * 1.1), 2)
    else:
        value = round(random.uniform(metric.critical_threshold * 0.95, metric.critical_threshold * 1.15), 2)

    if category == "thermal":
        component = random.choice(CRAC_UNITS)
    elif category == "gpu":
        component = random.choice(GPU_COMPONENTS)
    elif category == "network":
        component = f"TOR-Switch-{rack}"
    elif category == "storage":
        component = random.choice(["disk-sda", "disk-sdb", "disk-nvme0n1"])
    elif category == "power":
        component = random.choice(PDU_UNITS)
    else:  # memory
        component = f"DIMM-{random.choice(['A', 'B', 'C', 'D'])}{random.randint(1, 4)}"

    message_templates = {
        "thermal": f"{component} temperature {'elevated' if severity == 'warning' else 'critical'} on {host}",
        "gpu": f"GPU metric {metric.name} {'above normal' if severity == 'warning' else 'at critical level'} on {host}",
        "network": f"Network {metric.name} {'degraded' if severity == 'warning' else 'severely impacted'} on {rack}",
        "storage": f"Storage {metric.name} {'warning' if severity == 'warning' else 'critical'} on {host}",
        "power": f"Power {metric.name} {'fluctuation' if severity == 'warning' else 'anomaly'} detected on {component}",
        "memory": f"Memory {metric.name} {'elevated' if severity == 'warning' else 'critical'} on {host}",
    }

    return {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "severity": severity,
        "category": category,
        "component": component,
        "host": host,
        "rack": rack,
        "datacenter": "dc-tokyo-01",
        "metric_name": metric.name,
        "metric_value": value,
        "threshold": metric.warning_threshold if severity == "warning" else metric.critical_threshold,
        "message": message_templates.get(category, f"Alert on {host}: {metric.name}"),
        "raw_data": {"isolated": True, "metric_unit": metric.unit},
        "triage_status": "pending",
    }


async def _emit_alert(alert: dict) -> None:
    """Persists, broadcasts, and (when warranted) triages a single alert.

    Inserts the alert into the database, writes an audit-log entry,
    pushes a ``new_alert`` envelope onto the global SSE feed, and — for
    ``warning`` and ``critical`` alerts — schedules a triage task on the
    registered callback. Triage tasks are kept in
    :data:`_background_tasks` so they are not garbage-collected before
    completing.

    Args:
        alert: A fully populated alert dict.
    """
    await insert_alert(alert)
    await insert_audit_log("alert_received", alert["id"], {"severity": alert["severity"], "category": alert["category"]})
    await broadcast_alert({"type": "new_alert", "alert": alert})

    if alert["severity"] in ("warning", "critical"):
        if _triage_callback:
            task = asyncio.create_task(_triage_callback(alert))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        else:
            logger.debug("No triage callback registered, skipping triage for alert %s", alert["id"])


async def _run_scenario() -> None:
    """Picks a scenario and emits its alerts on the configured schedule.

    The first step fires immediately; subsequent steps wait for the
    larger of the step's own ``delay_seconds`` and the configured
    minimum interval, so scenarios cannot fire faster than the global
    pacing config allows. Each emitted alert carries scenario metadata
    in its ``raw_data`` so downstream tooling can identify it.
    """
    scenario = pick_scenario()
    logger.info("Starting scenario: %s — %s", scenario.name, scenario.description)

    for i, step in enumerate(scenario.alerts):
        if i > 0:
            await asyncio.sleep(max(step.delay_seconds, settings.ALERT_INTERVAL_MIN))

        alert = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "severity": step.severity,
            "category": step.category,
            "component": step.component,
            "host": step.host,
            "rack": step.rack,
            "datacenter": "dc-tokyo-01",
            "metric_name": step.metric_name,
            "metric_value": step.metric_value,
            "threshold": step.threshold,
            "message": step.message,
            "raw_data": {**step.raw_data, "scenario": scenario.name, "scenario_step": i + 1},
            "triage_status": "pending",
        }
        await _emit_alert(alert)

    logger.info("Scenario complete: %s", scenario.name)


async def alert_simulator() -> None:
    """Runs the alert generator loop until cancelled.

    On each iteration, sleeps a uniformly-random number of seconds in
    ``[ALERT_INTERVAL_MIN, ALERT_INTERVAL_MAX]`` and then either runs a
    multi-step scenario (with probability
    :attr:`Settings.SCENARIO_PROBABILITY`) or emits a single isolated
    alert. Exits cleanly on :class:`asyncio.CancelledError`; other
    exceptions are logged and the loop sleeps briefly before resuming.
    """
    logger.info(
        "Alert simulator started (interval: %d-%ds, scenario probability: %.0f%%)",
        settings.ALERT_INTERVAL_MIN,
        settings.ALERT_INTERVAL_MAX,
        settings.SCENARIO_PROBABILITY * 100,
    )

    while True:
        try:
            interval = random.uniform(settings.ALERT_INTERVAL_MIN, settings.ALERT_INTERVAL_MAX)
            await asyncio.sleep(interval)

            if random.random() < settings.SCENARIO_PROBABILITY:
                await _run_scenario()
            else:
                alert = _generate_isolated_alert()
                await _emit_alert(alert)

        except asyncio.CancelledError:
            logger.info("Alert simulator shutting down")
            break
        except Exception:
            logger.exception("Error in alert simulator loop")
            await asyncio.sleep(5)
