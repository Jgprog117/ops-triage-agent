import json
import logging
from pathlib import Path

import aiosqlite

from backend.config import settings

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    component TEXT NOT NULL,
    host TEXT NOT NULL,
    rack TEXT NOT NULL,
    datacenter TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    threshold REAL NOT NULL,
    message TEXT NOT NULL,
    raw_data TEXT,
    triage_status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    severity TEXT NOT NULL,
    summary TEXT NOT NULL,
    root_cause TEXT,
    remediation_steps TEXT,
    correlated_alert_ids TEXT,
    assigned_team TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS escalations (
    id TEXT PRIMARY KEY,
    incident_id TEXT REFERENCES incidents(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    urgency TEXT NOT NULL,
    notification_channels TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hosts (
    hostname TEXT PRIMARY KEY,
    rack TEXT NOT NULL,
    datacenter TEXT NOT NULL,
    gpu_type TEXT,
    gpu_count INTEGER,
    cpu_type TEXT,
    memory_gb INTEGER,
    os TEXT,
    status TEXT DEFAULT 'healthy',
    uptime_hours REAL,
    last_incident_id TEXT,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    entity_id TEXT,
    details TEXT
);

CREATE TABLE IF NOT EXISTS webhook_dlq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL,
    error TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_rack ON alerts(rack);
CREATE INDEX IF NOT EXISTS idx_alerts_host ON alerts(host);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_category ON alerts(category);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);

CREATE TRIGGER IF NOT EXISTS trg_incidents_updated_at
AFTER UPDATE ON incidents
BEGIN
    UPDATE incidents SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db


async def init_database() -> None:
    global _db
    db_path = Path(settings.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(db_path))
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.execute("PRAGMA cache_size=-64000")
    await _db.executescript(SCHEMA)
    await _db.commit()
    logger.info("Database initialized at %s", db_path)


async def close_database() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed")


async def insert_alert(alert: dict) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO alerts
           (id, timestamp, severity, category, component, host, rack,
            datacenter, metric_name, metric_value, threshold, message, raw_data, triage_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            alert["id"], alert["timestamp"], alert["severity"],
            alert["category"], alert["component"], alert["host"],
            alert["rack"], alert["datacenter"], alert["metric_name"],
            alert["metric_value"], alert["threshold"], alert["message"],
            json.dumps(alert.get("raw_data", {})),
            alert.get("triage_status", "pending"),
        ),
    )
    await db.commit()


async def update_alert_triage_status(alert_id: str, status: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE alerts SET triage_status = ? WHERE id = ?",
        (status, alert_id),
    )
    await db.commit()


async def get_recent_alerts(
    minutes_ago: int = 15,
    rack: str | None = None,
    host: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    limit: int = 50,
) -> list[dict]:
    db = await get_db()
    conditions = ["timestamp >= datetime('now', ?)", ]
    params: list = [f"-{minutes_ago} minutes"]

    if rack:
        conditions.append("rack = ?")
        params.append(rack)
    if host:
        conditions.append("host = ?")
        params.append(host)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)

    where = " AND ".join(conditions)
    params.append(limit)

    rows = await db.execute_fetchall(
        f"SELECT * FROM alerts WHERE {where} ORDER BY timestamp DESC LIMIT ?",
        params,
    )
    return [dict(row) for row in rows]


async def get_alert_by_id(alert_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_alerts_paginated(
    offset: int = 0,
    limit: int = 50,
    severity: str | None = None,
    category: str | None = None,
) -> list[dict]:
    db = await get_db()
    conditions: list[str] = []
    params: list = []

    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if category:
        conditions.append("category = ?")
        params.append(category)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])

    rows = await db.execute_fetchall(
        f"SELECT * FROM alerts {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        params,
    )
    return [dict(row) for row in rows]


async def insert_incident(incident: dict) -> str:
    db = await get_db()
    await db.execute(
        """INSERT INTO incidents
           (id, title, severity, summary, root_cause, remediation_steps,
            correlated_alert_ids, assigned_team, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            incident["id"], incident["title"], incident["severity"],
            incident["summary"], incident.get("root_cause"),
            json.dumps(incident.get("remediation_steps", [])),
            json.dumps(incident.get("correlated_alert_ids", [])),
            incident.get("assigned_team"), incident.get("status", "open"),
        ),
    )
    await db.commit()
    return incident["id"]


async def get_incidents(status: str | None = None, limit: int = 50) -> list[dict]:
    db = await get_db()
    if status:
        rows = await db.execute_fetchall(
            "SELECT * FROM incidents WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    results = []
    for row in rows:
        d = dict(row)
        d["remediation_steps"] = json.loads(d["remediation_steps"] or "[]")
        d["correlated_alert_ids"] = json.loads(d["correlated_alert_ids"] or "[]")
        results.append(d)
    return results


async def get_incident_by_id(incident_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    d = dict(row)
    d["remediation_steps"] = json.loads(d["remediation_steps"] or "[]")
    d["correlated_alert_ids"] = json.loads(d["correlated_alert_ids"] or "[]")
    return d


async def insert_escalation(escalation: dict) -> str:
    db = await get_db()
    await db.execute(
        """INSERT INTO escalations (id, incident_id, reason, urgency, notification_channels)
           VALUES (?, ?, ?, ?, ?)""",
        (
            escalation["id"], escalation["incident_id"],
            escalation["reason"], escalation["urgency"],
            json.dumps(escalation.get("notification_channels", [])),
        ),
    )
    await db.commit()
    return escalation["id"]


async def get_escalations(limit: int = 50) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM escalations ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    results = []
    for row in rows:
        d = dict(row)
        d["notification_channels"] = json.loads(d["notification_channels"] or "[]")
        results.append(d)
    return results


async def get_host(hostname: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM hosts WHERE hostname = ?", (hostname,))
    row = await cursor.fetchone()
    if not row:
        return None
    d = dict(row)
    d["metadata"] = json.loads(d["metadata"] or "{}")
    return d


async def insert_audit_log(event_type: str, entity_id: str | None = None, details: dict | None = None) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO audit_log (event_type, entity_id, details) VALUES (?, ?, ?)",
        (event_type, entity_id, json.dumps(details or {})),
    )
    await db.commit()


async def insert_webhook_dlq(payload: str, error: str, attempts: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO webhook_dlq (payload, error, attempts) VALUES (?, ?, ?)",
        (payload, error, attempts),
    )
    await db.commit()


async def get_dashboard_stats() -> dict:
    db = await get_db()
    row = (await db.execute_fetchall("""
        SELECT
            (SELECT COUNT(*) FROM alerts) AS total_alerts,
            (SELECT COUNT(*) FROM alerts WHERE timestamp >= datetime('now', '-1 hour')) AS alerts_last_hour,
            (SELECT COUNT(*) FROM incidents) AS total_incidents,
            (SELECT COUNT(*) FROM incidents WHERE status IN ('open', 'investigating')) AS open_incidents,
            (SELECT COUNT(*) FROM incidents WHERE severity = 'P1' AND status IN ('open', 'investigating')) AS p1_open,
            (SELECT COUNT(*) FROM escalations) AS total_escalations
    """))[0]

    return {
        "total_alerts": row["total_alerts"],
        "alerts_last_hour": row["alerts_last_hour"],
        "total_incidents": row["total_incidents"],
        "open_incidents": row["open_incidents"],
        "p1_open": row["p1_open"],
        "total_escalations": row["total_escalations"],
    }
