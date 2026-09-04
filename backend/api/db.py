"""
Database helper for RECOVER-ALLOC API.
Provides an SQLite connection manager compatible with idempotency.py,
schema initialization, and structured audit event logging.
"""
import json
import os
import sqlite3
import time
import uuid

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "recover_alloc_demo.db")


def get_db_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS allocations (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            intervention TEXT,
            expected_net_value REAL NOT NULL,
            solver_status TEXT NOT NULL,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            allocation_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            intervention TEXT NOT NULL,
            executor_adapter TEXT NOT NULL,
            status TEXT NOT NULL,
            external_ref TEXT,
            requested_at REAL NOT NULL,
            claimed_at REAL,
            dispatched_at REAL,
            completed_at REAL
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            item_id TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            model_version TEXT,
            policy_version TEXT,
            timestamp REAL NOT NULL,
            reason TEXT,
            result TEXT
        );
        """
    )
    conn.commit()


def log_audit_event(
    conn: sqlite3.Connection,
    event_type: str,
    payload: dict,
    run_id: str | None = None,
    item_id: str | None = None,
    reason: str | None = None,
    result: str | None = None,
    model_version: str = "v1.0.0",
    policy_version: str = "v1.0.0",
) -> str:
    event_id = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        """
        INSERT INTO audit_events
            (id, run_id, item_id, event_type, payload_json, model_version, policy_version, timestamp, reason, result)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            run_id,
            item_id,
            event_type,
            json.dumps(payload),
            model_version,
            policy_version,
            now,
            reason,
            result,
        ),
    )
    conn.commit()
    return event_id


def get_all_audit_events(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    cursor = conn.execute(
        """
        SELECT id, run_id, item_id, event_type, payload_json, model_version, policy_version, timestamp, reason, result
        FROM audit_events
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    events = []
    for r in rows:
        events.append(
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "item_id": r["item_id"],
                "event_type": r["event_type"],
                "payload": json.loads(r["payload_json"]),
                "model_version": r["model_version"],
                "policy_version": r["policy_version"],
                "timestamp": r["timestamp"],
                "reason": r["reason"],
                "result": r["result"],
            }
        )
    return events


def get_all_executions(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    cursor = conn.execute(
        """
        SELECT id, idempotency_key, allocation_id, item_id, intervention, executor_adapter, status, external_ref, requested_at, claimed_at, dispatched_at, completed_at
        FROM executions
        ORDER BY requested_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    executions = []
    for r in rows:
        executions.append(
            {
                "id": r["id"],
                "idempotency_key": r["idempotency_key"],
                "allocation_id": r["allocation_id"],
                "item_id": r["item_id"],
                "intervention": r["intervention"],
                "executor_adapter": r["executor_adapter"],
                "status": r["status"],
                "external_ref": r["external_ref"],
                "requested_at": r["requested_at"],
                "claimed_at": r["claimed_at"],
                "dispatched_at": r["dispatched_at"],
                "completed_at": r["completed_at"],
            }
        )
    return executions
