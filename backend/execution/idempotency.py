"""
Idempotency — RECOVER-ALLOC, Phase 5.

THE core guarantee: idempotency_key = SHA256(run_id:item_id:intervention),
enforced by a database UNIQUE constraint (schema.sql / migration 0002),
NOT by Python dictionaries, in-memory locks, or single-thread assumptions.

`claim_execution()` below takes a DB-API 2.0-compatible connection/cursor
(works with sqlite3 out of the box; the SQL itself — `ON CONFLICT (col)
DO NOTHING RETURNING id` — is valid, unmodified Postgres syntax too,
confirmed against SQLite 3.45 in this sandbox). This is a single
atomic round-trip: either this call wins the claim (gets a row back) or
it doesn't (someone else already owns this idempotency_key), with no
window for a second process to sneak in between a check and an insert.

SANDBOX HONESTY NOTE: this has been exercised against real SQLite (a
real relational engine enforcing its own UNIQUE index under genuine
concurrent OS-thread access — see tests/test_execution_concurrency.py),
which proves the SQL pattern and the concurrency-resolution MECHANISM
work correctly under real concurrent access. It does NOT prove Postgres
specifically — connection pooling behavior, MVCC visibility rules, and
real multi-process (not just multi-thread) behavior remain unverified
until this runs against a real Postgres instance. Do not report this as
"PostgreSQL concurrency verified."
"""
import hashlib
import time
import uuid
from dataclasses import dataclass

from domain.enums import ExecutionStatus


def compute_idempotency_key(run_id: str, item_id: str, intervention: str) -> str:
    raw = f"{run_id}:{item_id}:{intervention}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class ClaimResult:
    won: bool
    execution_id: str
    idempotency_key: str
    existing_status: str | None = None  # populated only when won=False


def claim_execution(
    conn,
    *,
    run_id: str,
    item_id: str,
    intervention: str,
    allocation_id: str,
    executor_adapter: str,
) -> ClaimResult:
    """
    Attempts to atomically claim ownership of (run_id, item_id,
    intervention). Returns won=True with a fresh execution_id if this
    call wins; won=False with the EXISTING row's status if it doesn't.

    `conn` must support `.execute(sql, params)` returning a cursor with
    `.fetchone()`/`.fetchall()`, and `.commit()` — i.e., the stdlib
    sqlite3 connection interface, which is also what psycopg2 connections
    expose. No sqlite-specific behavior is used beyond that surface.
    """
    idempotency_key = compute_idempotency_key(run_id, item_id, intervention)
    execution_id = str(uuid.uuid4())
    now = time.time()

    cur = conn.execute(
        """
        INSERT INTO executions
            (id, idempotency_key, allocation_id, item_id, intervention,
             executor_adapter, status, requested_at, claimed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """,
        (
            execution_id, idempotency_key, allocation_id, item_id, intervention,
            executor_adapter, ExecutionStatus.CLAIMED.value, now, now,
        ),
    )
    row = cur.fetchone()
    conn.commit()

    if row is not None:
        return ClaimResult(won=True, execution_id=execution_id, idempotency_key=idempotency_key)

    # Lost the race (or this exact (run,item,intervention) was already
    # claimed earlier) — look up the existing row to report its status.
    existing = conn.execute(
        "SELECT id, status FROM executions WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    existing_id, existing_status = existing[0], existing[1]
    return ClaimResult(
        won=False, execution_id=existing_id, idempotency_key=idempotency_key,
        existing_status=existing_status,
    )


def update_execution_status(
    conn, execution_id: str, status: ExecutionStatus, *,
    external_ref: str | None = None, dispatched_at: float | None = None,
    completed_at: float | None = None,
) -> None:
    conn.execute(
        """
        UPDATE executions
        SET status = ?, external_ref = COALESCE(?, external_ref),
            dispatched_at = COALESCE(?, dispatched_at),
            completed_at = COALESCE(?, completed_at)
        WHERE id = ?
        """,
        (status.value, external_ref, dispatched_at, completed_at, execution_id),
    )
    conn.commit()


def get_execution(conn, execution_id: str):
    row = conn.execute(
        "SELECT id, idempotency_key, status, external_ref, claimed_at, dispatched_at, completed_at "
        "FROM executions WHERE id = ?",
        (execution_id,),
    ).fetchone()
    return row
