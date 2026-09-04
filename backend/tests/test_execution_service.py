"""
Execution service tests — RECOVER-ALLOC, Phase 5.

SANDBOX HONESTY NOTE (read before trusting these as "Postgres verified"):
these tests run against a real SQLite database (file-backed, not
:memory:, so genuine multi-thread/multi-connection access is exercised)
using the EXACT SAME idempotency-claim SQL
(`INSERT ... ON CONFLICT (col) DO NOTHING RETURNING id`) that
execution/idempotency.py uses in production. This is valid syntax in
both SQLite 3.35+ and PostgreSQL — confirmed directly, not assumed (see
the sandbox verification note in execution/idempotency.py's docstring).

What this DOES prove: the idempotency-claim MECHANISM (an atomic
INSERT-or-conflict against a UNIQUE index) correctly resolves genuine
concurrent access from multiple OS threads, each with their own DB
connection, racing to claim the same key.

What this does NOT prove: PostgreSQL-specific behavior (connection
pooling, MVCC visibility across real separate processes/machines, actual
network-based concurrency). That remains unverified until run against a
real Postgres instance — do not report otherwise.
"""
import os
import sys
import sqlite3
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.enums import ExecutionStatus, InterventionType, ItemType, PolicyOutcome
from execution.base import ExecutionOutcome
from execution.idempotency import claim_execution, compute_idempotency_key, update_execution_status
from execution.service import (
    AllocationContext, AllocationMismatchError, ExecutionService,
    InvalidInterventionError, reconcile_stale_claims,
)
from execution.simulator_executor import SimulatorExecutor

TEST_SCHEMA = """
CREATE TABLE merchants (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE customers (id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL);
CREATE TABLE recoverable_items (id TEXT PRIMARY KEY, type TEXT NOT NULL);
CREATE TABLE allocations (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, item_id TEXT NOT NULL);
CREATE TABLE executions (
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
"""


@dataclass
class FixtureItem:
    id: str
    type: ItemType
    amount: Decimal
    risk_flags: list = field(default_factory=list)


def make_test_db():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "test.db")
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(TEST_SCHEMA)
    conn.commit()
    return conn, path


class TestIdempotencyClaimDirect(unittest.TestCase):
    def setUp(self):
        self.conn, self.path = make_test_db()

    def test_first_claim_wins(self):
        result = claim_execution(
            self.conn, run_id="run1", item_id="item1", intervention="PAYMENT_RETRY",
            allocation_id="alloc1", executor_adapter="simulator",
        )
        self.assertTrue(result.won)

    def test_second_identical_claim_loses(self):
        r1 = claim_execution(self.conn, run_id="run1", item_id="item1", intervention="PAYMENT_RETRY",
                              allocation_id="alloc1", executor_adapter="simulator")
        r2 = claim_execution(self.conn, run_id="run1", item_id="item1", intervention="PAYMENT_RETRY",
                              allocation_id="alloc1", executor_adapter="simulator")
        self.assertTrue(r1.won)
        self.assertFalse(r2.won)
        self.assertEqual(r2.execution_id, r1.execution_id, "loser must be told the WINNER's execution id")
        self.assertEqual(r2.existing_status, ExecutionStatus.CLAIMED.value)

    def test_different_intervention_same_item_is_a_different_key(self):
        r1 = claim_execution(self.conn, run_id="run1", item_id="item1", intervention="PAYMENT_RETRY",
                              allocation_id="alloc1", executor_adapter="simulator")
        r2 = claim_execution(self.conn, run_id="run1", item_id="item1", intervention="WHATSAPP_REMINDER",
                              allocation_id="alloc1", executor_adapter="simulator")
        self.assertTrue(r1.won)
        self.assertTrue(r2.won)
        self.assertNotEqual(r1.idempotency_key, r2.idempotency_key)

    def test_idempotency_key_is_sha256_of_exact_spec_format(self):
        key = compute_idempotency_key("run1", "item1", "PAYMENT_RETRY")
        import hashlib
        expected = hashlib.sha256(b"run1:item1:PAYMENT_RETRY").hexdigest()
        self.assertEqual(key, expected)

    def test_database_enforces_uniqueness_at_the_constraint_level(self):
        """
        Bypass claim_execution() entirely and try a raw duplicate INSERT
        directly, proving the UNIQUE constraint itself (not just our
        Python wrapper) is what blocks duplicates.
        """
        key = compute_idempotency_key("run1", "item1", "PAYMENT_RETRY")
        self.conn.execute(
            "INSERT INTO executions (id, idempotency_key, allocation_id, item_id, intervention, "
            "executor_adapter, status, requested_at, claimed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("exec_a", key, "alloc1", "item1", "PAYMENT_RETRY", "simulator", "CLAIMED", time.time(), time.time()),
        )
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO executions (id, idempotency_key, allocation_id, item_id, intervention, "
                "executor_adapter, status, requested_at, claimed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("exec_b", key, "alloc1", "item1", "PAYMENT_RETRY", "simulator", "CLAIMED", time.time(), time.time()),
            )


class TestExecutionServiceBoundary(unittest.TestCase):
    def setUp(self):
        self.conn, self.path = make_test_db()
        self.item = FixtureItem(id="item1", type=ItemType.PAYMENT_FAILURE, amount=Decimal("5000"))

    def test_policy_blocked_never_reaches_executor(self):
        calls = []
        executor = SimulatorExecutor(forced_behavior="success")
        original_execute = executor.execute
        def spy_execute(**kwargs):
            calls.append(kwargs)
            return original_execute(**kwargs)
        executor.execute = spy_execute

        service = ExecutionService(self.conn, executor, "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.BLOCK,
        )
        result = service.execute(ctx, self.item)
        self.assertEqual(result.status, "POLICY_BLOCKED")
        self.assertEqual(len(calls), 0, "executor must NEVER be called for a BLOCKed allocation")

    def test_escalate_never_reaches_executor(self):
        executor = SimulatorExecutor(forced_behavior="success")
        service = ExecutionService(self.conn, executor, "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ESCALATE,
        )
        result = service.execute(ctx, self.item)
        self.assertEqual(result.status, "POLICY_BLOCKED")

    def test_allow_reaches_executor_and_succeeds(self):
        executor = SimulatorExecutor(forced_behavior="success")
        service = ExecutionService(self.conn, executor, "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        result = service.execute(ctx, self.item)
        self.assertEqual(result.status, "EXECUTED")
        self.assertEqual(result.final_status, ExecutionStatus.VERIFIED_SUCCESS.value)
        self.assertIsNotNone(result.external_ref)

    def test_invalid_intervention_for_item_type_raises(self):
        executor = SimulatorExecutor(forced_behavior="success")
        service = ExecutionService(self.conn, executor, "simulator")
        receivable = FixtureItem(id="item2", type=ItemType.B2B_RECEIVABLE, amount=Decimal("5000"))
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item2",
            intervention=InterventionType.PAYMENT_RETRY,  # invalid for B2B_RECEIVABLE
            policy_outcome=PolicyOutcome.ALLOW,
        )
        with self.assertRaises(InvalidInterventionError):
            service.execute(ctx, receivable)

    def test_allocation_item_mismatch_raises(self):
        executor = SimulatorExecutor(forced_behavior="success")
        service = ExecutionService(self.conn, executor, "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item_DIFFERENT",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        with self.assertRaises(AllocationMismatchError):
            service.execute(ctx, self.item)

    def test_duplicate_execution_request_is_blocked_and_executor_called_once(self):
        call_count = {"n": 0}
        base_executor = SimulatorExecutor(forced_behavior="success")
        class CountingExecutor:
            def execute(self, **kwargs):
                call_count["n"] += 1
                return base_executor.execute(**kwargs)
        service = ExecutionService(self.conn, CountingExecutor(), "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        r1 = service.execute(ctx, self.item)
        r2 = service.execute(ctx, self.item)
        self.assertEqual(r1.status, "EXECUTED")
        self.assertEqual(r2.status, "DUPLICATE_BLOCKED")
        self.assertEqual(call_count["n"], 1, "executor must be called exactly once, not twice")

    def test_recoverable_failure_produces_verified_failed(self):
        executor = SimulatorExecutor(forced_behavior="recoverable_failure")
        service = ExecutionService(self.conn, executor, "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        result = service.execute(ctx, self.item)
        self.assertEqual(result.final_status, ExecutionStatus.VERIFIED_FAILED.value)

    def test_timeout_produces_uncertain_not_failed_or_success(self):
        """Critical: an ambiguous outcome must NEVER be recorded as a
        definite success or failure."""
        executor = SimulatorExecutor(forced_behavior="timeout")
        service = ExecutionService(self.conn, executor, "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        result = service.execute(ctx, self.item)
        self.assertEqual(result.final_status, ExecutionStatus.UNCERTAIN.value)
        self.assertIsNone(result.external_ref)

    def test_invalid_response_also_produces_uncertain(self):
        executor = SimulatorExecutor(forced_behavior="invalid_response")
        service = ExecutionService(self.conn, executor, "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        result = service.execute(ctx, self.item)
        self.assertEqual(result.final_status, ExecutionStatus.UNCERTAIN.value)

    def test_simulator_is_deterministic_across_repeated_calls(self):
        """Same idempotency_key inputs -> same behavior, every time (no
        actual randomness) - required for a non-flaky live demo."""
        executor = SimulatorExecutor()  # no forced_behavior - real hash-based selection
        key = compute_idempotency_key("run1", "item1", "PAYMENT_RETRY")
        outcomes = [executor.execute(item=self.item, intervention=InterventionType.PAYMENT_RETRY,
                                      idempotency_key=key) for _ in range(20)]
        first = outcomes[0]
        for o in outcomes[1:]:
            self.assertEqual(o.confirmed, first.confirmed)
            self.assertEqual(o.succeeded, first.succeeded)
            self.assertEqual(o.detail, first.detail)

    def test_uncertain_execution_audit_event_emitted(self):
        events_seen = []
        executor = SimulatorExecutor(forced_behavior="timeout")
        service = ExecutionService(self.conn, executor, "simulator",
                                    audit_logger=lambda ev, **kw: events_seen.append(ev))
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        service.execute(ctx, self.item)
        self.assertIn("EXECUTION_UNCERTAIN", events_seen)
        self.assertNotIn("EXECUTION_VERIFIED", events_seen)

    def test_full_audit_trail_for_successful_execution(self):
        events_seen = []
        executor = SimulatorExecutor(forced_behavior="success")
        service = ExecutionService(self.conn, executor, "simulator",
                                    audit_logger=lambda ev, **kw: events_seen.append(ev))
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        service.execute(ctx, self.item)
        self.assertEqual(
            events_seen,
            ["EXECUTION_REQUESTED", "EXECUTION_CLAIMED", "EXECUTION_DISPATCHED", "EXECUTION_VERIFIED"],
        )

    def test_full_audit_trail_for_duplicate_blocked(self):
        executor = SimulatorExecutor(forced_behavior="success")
        service = ExecutionService(self.conn, executor, "simulator")
        ctx = AllocationContext(
            allocation_id="alloc1", run_id="run1", item_id="item1",
            intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
        )
        service.execute(ctx, self.item)
        events_seen = []
        service2 = ExecutionService(self.conn, executor, "simulator",
                                     audit_logger=lambda ev, **kw: events_seen.append(ev))
        service2.execute(ctx, self.item)
        self.assertEqual(events_seen, ["EXECUTION_REQUESTED", "DUPLICATE_EXECUTION_BLOCKED"])


class TestConcurrentExecution(unittest.TestCase):
    """
    THE mandatory concurrency test: >=10 concurrent execution attempts
    for the SAME (run_id, item_id, intervention), verified against real
    database state, not just return values.
    """

    def test_ten_concurrent_identical_requests_exactly_one_wins(self):
        conn_main, path = make_test_db()
        conn_main.close()  # each thread opens its OWN connection to the same file, per the spec's "must survive concurrent requests and multiple application processes"

        N_THREADS = 10
        dispatch_count = {"n": 0}
        dispatch_lock = threading.Lock()
        results = [None] * N_THREADS
        barrier = threading.Barrier(N_THREADS)  # force genuinely simultaneous starts, not a sequential race

        class CountingSimulator:
            def execute(self, **kwargs):
                with dispatch_lock:
                    dispatch_count["n"] += 1
                return SimulatorExecutor(forced_behavior="success").execute(**kwargs)

        def worker(idx):
            thread_conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
            thread_conn.execute("PRAGMA journal_mode=WAL;")
            service = ExecutionService(thread_conn, CountingSimulator(), "simulator")
            ctx = AllocationContext(
                allocation_id="alloc1", run_id="run_concurrent", item_id="item_concurrent",
                intervention=InterventionType.PAYMENT_RETRY, policy_outcome=PolicyOutcome.ALLOW,
            )
            item = FixtureItem(id="item_concurrent", type=ItemType.PAYMENT_FAILURE, amount=Decimal("5000"))
            barrier.wait()  # all threads hit claim_execution at approximately the same instant
            results[idx] = service.execute(ctx, item)
            thread_conn.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        statuses = [r.status for r in results if r is not None]
        self.assertEqual(len(statuses), N_THREADS, "every thread must complete and return a result")

        n_executed = statuses.count("EXECUTED")
        n_duplicate = statuses.count("DUPLICATE_BLOCKED")
        print(f"\n  concurrency result: {n_executed} EXECUTED, {n_duplicate} DUPLICATE_BLOCKED "
              f"(expected 1 and {N_THREADS-1})")
        self.assertEqual(n_executed, 1, "exactly ONE request must actually execute")
        self.assertEqual(n_duplicate, N_THREADS - 1, "all others must be blocked as duplicates")
        self.assertEqual(dispatch_count["n"], 1, "the external adapter must be dispatched to EXACTLY ONCE")

        # Verify against real DATABASE STATE, not just return values.
        verify_conn = sqlite3.connect(path)
        rows = verify_conn.execute("SELECT id, status FROM executions").fetchall()
        self.assertEqual(len(rows), 1, "exactly ONE execution ownership record must exist in the database")
        self.assertEqual(rows[0][1], ExecutionStatus.VERIFIED_SUCCESS.value)
        verify_conn.close()


class TestReconciliation(unittest.TestCase):
    def test_stale_claimed_row_detected(self):
        conn, path = make_test_db()
        old_time = time.time() - 1000  # older than default staleness threshold
        conn.execute(
            "INSERT INTO executions (id, idempotency_key, allocation_id, item_id, intervention, "
            "executor_adapter, status, requested_at, claimed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("exec_stale", "key_stale", "alloc1", "item1", "PAYMENT_RETRY", "simulator",
             ExecutionStatus.CLAIMED.value, old_time, old_time),
        )
        conn.commit()
        stale_ids = reconcile_stale_claims(conn, staleness_seconds=300.0)
        self.assertIn("exec_stale", stale_ids)

    def test_fresh_claimed_row_not_flagged_stale(self):
        conn, path = make_test_db()
        conn.execute(
            "INSERT INTO executions (id, idempotency_key, allocation_id, item_id, intervention, "
            "executor_adapter, status, requested_at, claimed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("exec_fresh", "key_fresh", "alloc1", "item1", "PAYMENT_RETRY", "simulator",
             ExecutionStatus.CLAIMED.value, time.time(), time.time()),
        )
        conn.commit()
        stale_ids = reconcile_stale_claims(conn, staleness_seconds=300.0)
        self.assertNotIn("exec_fresh", stale_ids)

    def test_uncertain_row_never_flagged_for_auto_retry(self):
        """
        reconcile_stale_claims only looks at CLAIMED rows by construction
        - this test documents/enforces that UNCERTAIN rows are structurally
        excluded, not just "usually" excluded.
        """
        conn, path = make_test_db()
        conn.execute(
            "INSERT INTO executions (id, idempotency_key, allocation_id, item_id, intervention, "
            "executor_adapter, status, requested_at, claimed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("exec_uncertain", "key_uncertain", "alloc1", "item1", "PAYMENT_RETRY", "simulator",
             ExecutionStatus.UNCERTAIN.value, time.time() - 1000, time.time() - 1000),
        )
        conn.commit()
        stale_ids = reconcile_stale_claims(conn, staleness_seconds=300.0)
        self.assertNotIn("exec_uncertain", stale_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
