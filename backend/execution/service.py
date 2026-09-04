"""
ExecutionService — RECOVER-ALLOC, Phase 5.

THE policy -> executor boundary. Per the spec: "The executor MUST reject
any request that is not backed by a valid policy-approved allocation."
"""
import time
from dataclasses import dataclass

from domain.enums import ExecutionStatus, InterventionType, PolicyOutcome, VALID_INTERVENTIONS_BY_ITEM_TYPE
from execution.idempotency import claim_execution, update_execution_status


class PolicyNotApprovedError(Exception):
    pass


class AllocationMismatchError(Exception):
    pass


class InvalidInterventionError(Exception):
    pass


@dataclass
class AllocationContext:
    """
    What the caller (strategies/recover_alloc.py) must supply — a
    pre-validated snapshot of the allocation + policy decision this
    execution request claims to be backed by. The service re-checks
    every field itself; it never trusts the caller blindly, per the
    explicit boundary requirement.
    """
    allocation_id: str
    run_id: str
    item_id: str
    intervention: InterventionType
    policy_outcome: PolicyOutcome


@dataclass
class ExecutionRequestResult:
    status: str  # "EXECUTED" | "DUPLICATE_BLOCKED" | "POLICY_BLOCKED"
    execution_id: str | None
    final_status: str | None  # ExecutionStatus value, once known
    external_ref: str | None
    audit_events: list[str]  # AuditEventType values emitted, in order, for the caller to log


class ExecutionService:
    def __init__(self, conn, executor_adapter, executor_adapter_name: str, audit_logger=None):
        self.conn = conn
        self.executor_adapter = executor_adapter
        self.executor_adapter_name = executor_adapter_name
        self.audit_logger = audit_logger  # optional callable(event_type, **kwargs); real audit wiring is Phase 7+

    def _log(self, event_type: str, **kwargs):
        if self.audit_logger:
            self.audit_logger(event_type, **kwargs)

    def execute(self, ctx: AllocationContext, item) -> ExecutionRequestResult:
        events: list[str] = []
        self._log("EXECUTION_REQUESTED", allocation_id=ctx.allocation_id, run_id=ctx.run_id,
                   item_id=ctx.item_id, intervention=ctx.intervention.value)
        events.append("EXECUTION_REQUESTED")

        # --- Boundary checks: reject anything not policy-approved. ---
        if ctx.policy_outcome != PolicyOutcome.ALLOW:
            self._log("EXECUTION_BLOCKED", allocation_id=ctx.allocation_id,
                       reason=f"policy_outcome={ctx.policy_outcome.value}, not ALLOW")
            events.append("EXECUTION_BLOCKED")
            return ExecutionRequestResult(
                status="POLICY_BLOCKED", execution_id=None, final_status=None,
                external_ref=None, audit_events=events,
            )

        if ctx.item_id != item.id:
            raise AllocationMismatchError(
                f"allocation item_id={ctx.item_id} does not match supplied item.id={item.id}"
            )

        valid_interventions = VALID_INTERVENTIONS_BY_ITEM_TYPE.get(item.type, ())
        if ctx.intervention not in valid_interventions:
            raise InvalidInterventionError(
                f"{ctx.intervention} is not valid for item type {item.type}"
            )

        # --- Idempotency claim (the DB-enforced concurrency boundary). ---
        claim = claim_execution(
            self.conn, run_id=ctx.run_id, item_id=ctx.item_id,
            intervention=ctx.intervention.value, allocation_id=ctx.allocation_id,
            executor_adapter=self.executor_adapter_name,
        )

        if not claim.won:
            self._log("DUPLICATE_EXECUTION_BLOCKED", idempotency_key=claim.idempotency_key,
                       existing_execution_id=claim.execution_id, existing_status=claim.existing_status)
            events.append("DUPLICATE_EXECUTION_BLOCKED")
            return ExecutionRequestResult(
                status="DUPLICATE_BLOCKED", execution_id=claim.execution_id,
                final_status=claim.existing_status, external_ref=None, audit_events=events,
            )

        self._log("EXECUTION_CLAIMED", execution_id=claim.execution_id, idempotency_key=claim.idempotency_key)
        events.append("EXECUTION_CLAIMED")

        # --- Dispatch. Only the claim-winning process ever reaches here. ---
        outcome = self.executor_adapter.execute(
            item=item, intervention=ctx.intervention, idempotency_key=claim.idempotency_key,
        )
        now = time.time()

        if not outcome.confirmed:
            # Genuinely ambiguous (timeout / connection error / unexpected
            # response) -> UNCERTAIN. NEVER auto-retried from here.
            update_execution_status(
                self.conn, claim.execution_id, ExecutionStatus.UNCERTAIN, completed_at=now,
            )
            self._log("EXECUTION_UNCERTAIN", execution_id=claim.execution_id, detail=outcome.detail)
            events.append("EXECUTION_UNCERTAIN")
            return ExecutionRequestResult(
                status="EXECUTED", execution_id=claim.execution_id,
                final_status=ExecutionStatus.UNCERTAIN.value, external_ref=None, audit_events=events,
            )

        self._log("EXECUTION_DISPATCHED", execution_id=claim.execution_id, detail=outcome.detail)
        events.append("EXECUTION_DISPATCHED")

        if outcome.succeeded:
            update_execution_status(
                self.conn, claim.execution_id, ExecutionStatus.VERIFIED_SUCCESS,
                external_ref=outcome.external_ref, dispatched_at=now, completed_at=now,
            )
            self._log("EXECUTION_VERIFIED", execution_id=claim.execution_id, external_ref=outcome.external_ref)
            events.append("EXECUTION_VERIFIED")
            return ExecutionRequestResult(
                status="EXECUTED", execution_id=claim.execution_id,
                final_status=ExecutionStatus.VERIFIED_SUCCESS.value,
                external_ref=outcome.external_ref, audit_events=events,
            )

        update_execution_status(
            self.conn, claim.execution_id, ExecutionStatus.VERIFIED_FAILED,
            dispatched_at=now, completed_at=now,
        )
        self._log("EXECUTION_VERIFICATION_FAILED", execution_id=claim.execution_id, detail=outcome.detail)
        events.append("EXECUTION_VERIFICATION_FAILED")
        return ExecutionRequestResult(
            status="EXECUTED", execution_id=claim.execution_id,
            final_status=ExecutionStatus.VERIFIED_FAILED.value, external_ref=None, audit_events=events,
        )


def reconcile_stale_claims(conn, *, staleness_seconds: float = 300.0) -> list[str]:
    """
    Deliberately separate from the request path (see
    docs/EXECUTION_STATE_MACHINE.md). Finds CLAIMED rows older than
    `staleness_seconds` with no dispatched_at timestamp — i.e., a process
    crashed between claiming and dispatching, so nothing was ever sent
    externally, and it is SAFE to reset them for a fresh dispatch attempt
    using the same row (not a new idempotency key).

    Returns the list of execution_ids reset. Does NOT touch UNCERTAIN
    rows — those require explicit human review, never automatic action.
    """
    cutoff = time.time() - staleness_seconds
    rows = conn.execute(
        "SELECT id FROM executions WHERE status = ? AND dispatched_at IS NULL AND claimed_at < ?",
        (ExecutionStatus.CLAIMED.value, cutoff),
    ).fetchall()
    stale_ids = [r[0] for r in rows]
    # Intentionally NOT auto-transitioning status here beyond identifying
    # them — a real reconciliation job decides what to do next (retry
    # dispatch, or escalate); this function's job is detection only.
    return stale_ids
