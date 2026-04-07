"""SQLite-backed persistence layer for alerts, incidents, and audit data.

The module owns a single process-wide :class:`aiosqlite.Connection` opened
during application startup. All public coroutines obtain that connection
via :func:`get_db`, so callers must call :func:`init_database` before any
read or write. The :data:`SCHEMA` constant is the canonical schema and is
applied idempotently — :func:`_migrate_incidents_columns` handles any
columns introduced after the initial release.
"""

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
    primary_alert_id TEXT,
    escalated INTEGER DEFAULT 0,
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
    """Returns the process-wide aiosqlite connection.

    Returns:
        The shared :class:`aiosqlite.Connection` opened by
        :func:`init_database`.

    Raises:
        RuntimeError: If the database has not been initialized yet.
    """
    global _db
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db


async def init_database() -> None:
    """Opens the database connection and applies the schema.

    Creates the database file (and parent directories) if needed, sets the
    pragmas used by the rest of the codebase (WAL, foreign keys, busy
    timeout, NORMAL sync, 64MB cache), runs the :data:`SCHEMA` script, and
    applies any column-level migrations. Safe to call once at startup.
    """
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
    await _migrate_incidents_columns(_db)
    await _db.commit()
    logger.info("Database initialized at %s", db_path)


async def _migrate_incidents_columns(db: aiosqlite.Connection) -> None:
    """Adds columns introduced after the initial schema, idempotently.

    Indexes that depend on the new columns are also created here — they
    cannot live in :data:`SCHEMA` because ``executescript`` runs before
    the ``ALTER TABLE`` statements on databases that pre-date the
    migration.

    Args:
        db: The open aiosqlite connection to migrate.
    """
    cursor = await db.execute("PRAGMA table_info(incidents)")
    existing = {row[1] for row in await cursor.fetchall()}
    if "primary_alert_id" not in existing:
        await db.execute("ALTER TABLE incidents ADD COLUMN primary_alert_id TEXT")
        logger.info("Migrated incidents: added primary_alert_id column")
    if "escalated" not in existing:
        await db.execute("ALTER TABLE incidents ADD COLUMN escalated INTEGER DEFAULT 0")
        logger.info("Migrated incidents: added escalated column")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_incidents_status_primary "
        "ON incidents(status, primary_alert_id)"
    )


async def close_database() -> None:
    """Closes the process-wide aiosqlite connection if it is open."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed")


async def insert_alert(alert: dict) -> None:
    """Inserts a new alert row.

    Args:
        alert: A dict matching the ``alerts`` table columns. ``raw_data``
            is JSON-serialized; ``triage_status`` defaults to ``pending``.
    """
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
    """Updates the ``triage_status`` column on a single alert.

    Args:
        alert_id: The alert id whose status to update.
        status: New status value.
    """
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
    exclude_id: str | None = None,
) -> list[dict]:
    """Returns recent alerts joined with their open-incident link, if any.

    Each row includes ``open_incident_id`` — the id of the first open
    incident whose ``correlated_alert_ids`` contains the alert, or
    ``NULL`` if none. This lets the agent see at a glance which alerts
    are already being handled and avoid creating duplicate incidents.

    Args:
        minutes_ago: Lookback window in minutes.
        rack: Optional rack filter.
        host: Optional hostname filter.
        category: Optional category filter.
        severity: Optional severity filter.
        limit: Maximum rows to return.
        exclude_id: Optional alert id to exclude (typically the alert
            currently being triaged).

    Returns:
        A list of dicts, one per alert row, ordered by ``timestamp``
        descending.
    """
    db = await get_db()
    conditions = ["a.timestamp >= datetime('now', ?)"]
    params: list = [f"-{minutes_ago} minutes"]

    if rack:
        conditions.append("a.rack = ?")
        params.append(rack)
    if host:
        conditions.append("a.host = ?")
        params.append(host)
    if category:
        conditions.append("a.category = ?")
        params.append(category)
    if severity:
        conditions.append("a.severity = ?")
        params.append(severity)
    if exclude_id:
        conditions.append("a.id != ?")
        params.append(exclude_id)

    where = " AND ".join(conditions)
    params.append(limit)

    # The correlated subquery uses json_each to find any open incident whose
    # correlated_alert_ids list contains this alert's id. Cheap at this scale
    # and avoids a schema migration to a junction table.
    rows = await db.execute_fetchall(
        f"""
        SELECT a.*,
               (SELECT i.id
                  FROM incidents i, json_each(i.correlated_alert_ids) je
                 WHERE je.value = a.id AND i.status = 'open'
                 LIMIT 1) AS open_incident_id
        FROM alerts a
        WHERE {where}
        ORDER BY a.timestamp DESC
        LIMIT ?
        """,
        params,
    )
    return [dict(row) for row in rows]


async def get_alert_by_id(alert_id: str) -> dict | None:
    """Fetches a single alert row by id.

    Args:
        alert_id: The alert id to fetch.

    Returns:
        The alert row as a dict, or ``None`` if no alert matches.
    """
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
    """Returns a paginated slice of alerts ordered by ``timestamp`` desc.

    Args:
        offset: Number of rows to skip.
        limit: Maximum rows to return.
        severity: Optional severity filter.
        category: Optional category filter.

    Returns:
        A list of dicts, one per alert row.
    """
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
    """Inserts a new incident row.

    Args:
        incident: A dict matching the ``incidents`` table columns.
            ``remediation_steps`` and ``correlated_alert_ids`` are
            JSON-serialized; ``escalated`` is coerced to 0/1.

    Returns:
        The id of the newly inserted incident.
    """
    db = await get_db()
    await db.execute(
        """INSERT INTO incidents
           (id, title, severity, summary, root_cause, remediation_steps,
            correlated_alert_ids, assigned_team, status, primary_alert_id, escalated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            incident["id"], incident["title"], incident["severity"],
            incident["summary"], incident.get("root_cause"),
            json.dumps(incident.get("remediation_steps", [])),
            json.dumps(incident.get("correlated_alert_ids", [])),
            incident.get("assigned_team"), incident.get("status", "open"),
            incident.get("primary_alert_id"),
            1 if incident.get("escalated") else 0,
        ),
    )
    await db.commit()
    return incident["id"]


async def attach_alert_to_incident(incident_id: str, alert_id: str) -> dict | None:
    """Adds an alert to an open incident's correlated alert list.

    Loads the existing list, appends ``alert_id`` if not already present,
    and writes the new list back. Refuses to attach to incidents that are
    not in ``open`` status.

    Args:
        incident_id: The incident to attach to.
        alert_id: The alert to add.

    Returns:
        The updated incident dict (with parsed list fields), or ``None``
        if the incident does not exist or is not open.
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT correlated_alert_ids, status FROM incidents WHERE id = ?",
        (incident_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    if row["status"] != "open":
        return None
    existing = json.loads(row["correlated_alert_ids"] or "[]")
    if alert_id not in existing:
        existing.append(alert_id)
        await db.execute(
            "UPDATE incidents SET correlated_alert_ids = ? WHERE id = ?",
            (json.dumps(existing), incident_id),
        )
        await db.commit()
    return await get_incident_by_id(incident_id)


async def find_open_incidents_for_alert(
    rack: str | None = None,
    host: str | None = None,
    category: str | None = None,
    minutes_ago: int = 60,
    limit: int = 5,
) -> list[dict]:
    """Finds open incidents whose primary alert matches the given filters.

    The agent calls this before :func:`insert_incident` to avoid creating
    duplicate records when a real incident is already being tracked for
    the same scenario. The filters combine with ``OR`` so any matching
    rack, host, or category produces a hit. Returns an empty list when
    none of ``rack``, ``host``, ``category`` are provided.

    Args:
        rack: Optional rack filter.
        host: Optional hostname filter.
        category: Optional category filter.
        minutes_ago: Lookback window for incident creation time.
        limit: Maximum incidents to return.

    Returns:
        A list of incident dicts (with parsed list fields), ordered by
        ``created_at`` descending.
    """
    if not (rack or host or category):
        return []

    db = await get_db()
    or_conds: list[str] = []
    params: list = [f"-{minutes_ago} minutes"]
    if host:
        or_conds.append("a.host = ?")
        params.append(host)
    if rack:
        or_conds.append("a.rack = ?")
        params.append(rack)
    if category:
        or_conds.append("a.category = ?")
        params.append(category)

    where_or = " OR ".join(or_conds)
    params.append(limit)

    rows = await db.execute_fetchall(
        f"""
        SELECT i.*
          FROM incidents i
          JOIN alerts a ON a.id = i.primary_alert_id
         WHERE i.status = 'open'
           AND i.created_at >= datetime('now', ?)
           AND ({where_or})
         ORDER BY i.created_at DESC
         LIMIT ?
        """,
        params,
    )
    results = []
    for row in rows:
        d = dict(row)
        d["remediation_steps"] = json.loads(d["remediation_steps"] or "[]")
        d["correlated_alert_ids"] = json.loads(d["correlated_alert_ids"] or "[]")
        results.append(d)
    return results


async def mark_incident_escalated(incident_id: str) -> None:
    """Sets the ``escalated`` flag on an incident.

    Args:
        incident_id: The incident to mark.
    """
    db = await get_db()
    await db.execute(
        "UPDATE incidents SET escalated = 1 WHERE id = ?",
        (incident_id,),
    )
    await db.commit()


async def get_incidents(status: str | None = None, limit: int = 50) -> list[dict]:
    """Returns incidents ordered by creation time descending.

    Args:
        status: Optional status filter (e.g., ``open``).
        limit: Maximum rows to return.

    Returns:
        A list of incident dicts with parsed ``remediation_steps`` and
        ``correlated_alert_ids`` lists.
    """
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
    """Fetches a single incident by id.

    Args:
        incident_id: The incident id to fetch.

    Returns:
        The incident dict (with parsed list fields), or ``None`` if no
        incident matches.
    """
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
    """Inserts a new escalation row.

    Args:
        escalation: A dict matching the ``escalations`` table columns.
            ``notification_channels`` is JSON-serialized.

    Returns:
        The id of the newly inserted escalation.
    """
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
    """Returns the most recent escalations.

    Args:
        limit: Maximum rows to return.

    Returns:
        A list of escalation dicts with parsed ``notification_channels``.
    """
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
    """Fetches a host inventory row by hostname.

    Args:
        hostname: The host to look up.

    Returns:
        The host dict with parsed ``metadata``, or ``None`` if no host
        matches.
    """
    db = await get_db()
    cursor = await db.execute("SELECT * FROM hosts WHERE hostname = ?", (hostname,))
    row = await cursor.fetchone()
    if not row:
        return None
    d = dict(row)
    d["metadata"] = json.loads(d["metadata"] or "{}")
    return d


async def insert_audit_log(event_type: str, entity_id: str | None = None, details: dict | None = None) -> None:
    """Writes an audit-log entry.

    Args:
        event_type: The event name (e.g., ``triage_started``).
        entity_id: Optional id of the entity the event refers to (alert,
            incident, escalation).
        details: Optional structured details. JSON-serialized.
    """
    db = await get_db()
    await db.execute(
        "INSERT INTO audit_log (event_type, entity_id, details) VALUES (?, ?, ?)",
        (event_type, entity_id, json.dumps(details or {})),
    )
    await db.commit()


async def insert_webhook_dlq(payload: str, error: str, attempts: int) -> None:
    """Persists a failed webhook delivery to the dead-letter queue.

    Args:
        payload: The exact body that failed delivery.
        error: The terminal error message.
        attempts: How many delivery attempts were made before giving up.
    """
    db = await get_db()
    await db.execute(
        "INSERT INTO webhook_dlq (payload, error, attempts) VALUES (?, ?, ?)",
        (payload, error, attempts),
    )
    await db.commit()


async def get_dashboard_stats() -> dict:
    """Returns aggregate counters for the dashboard.

    Computes alert and incident totals plus the open-incident counts in a
    single SQL roundtrip.

    Returns:
        A dict matching the field set of :class:`DashboardStats`, minus
        ``uptime_seconds`` which is added by the route handler.
    """
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
