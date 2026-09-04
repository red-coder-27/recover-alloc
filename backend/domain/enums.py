"""
Domain enums — RECOVER-ALLOC
Locked spec: Part D.

NOTE ON IMPLEMENTATION ENVIRONMENT:
The production build (per Part B / requirements.txt) uses Pydantic v2 for
domain models. This module itself has zero external dependencies (stdlib
`enum` only) either way, so it is unaffected by that choice and is written
exactly as it will ship.
"""
from enum import Enum


class ItemType(str, Enum):
    PAYMENT_FAILURE = "PAYMENT_FAILURE"
    B2B_RECEIVABLE = "B2B_RECEIVABLE"


class InterventionType(str, Enum):
    PAYMENT_RETRY = "PAYMENT_RETRY"
    WHATSAPP_REMINDER = "WHATSAPP_REMINDER"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"


class PolicyOutcome(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    MODIFY = "MODIFY"
    ESCALATE = "ESCALATE"


class ItemStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    EXECUTED = "EXECUTED"
    VERIFIED_RECOVERED = "VERIFIED_RECOVERED"
    VERIFIED_NOT_RECOVERED = "VERIFIED_NOT_RECOVERED"
    ESCALATED = "ESCALATED"
    EXCEPTION_UNSERVED = "EXCEPTION_UNSERVED"


class SolverStatus(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    SOLVER_ERROR = "SOLVER_ERROR"


class ExecutionStatus(str, Enum):
    """
    Phase 5 execution state machine. See docs/EXECUTION_STATE_MACHINE.md
    for the full transition diagram and crash-safety reasoning.

    CLAIMED is written atomically by the idempotency claim itself,
    BEFORE any external side effect is attempted. This is the state a
    row is stuck in if the owning process crashes between claiming and
    dispatching — UNCERTAIN is reserved specifically for "dispatch was
    attempted but its outcome could not be confirmed" (e.g. a timeout),
    which is a DIFFERENT situation from "never got as far as dispatching"
    (a stale CLAIMED row) — the two must not be conflated, since a stale
    CLAIMED row is safe to hand to a fresh dispatch attempt (nothing was
    ever sent) while UNCERTAIN must never be auto-retried.
    """
    CLAIMED = "CLAIMED"
    DISPATCHED = "DISPATCHED"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILED = "VERIFIED_FAILED"
    DISPATCH_FAILED = "DISPATCH_FAILED"
    UNCERTAIN = "UNCERTAIN"


class DiagnosisSource(str, Enum):
    LLM = "llm"
    RULE_TABLE = "rule_table"


class AuditEventType(str, Enum):
    EVENT_RECEIVED = "EVENT_RECEIVED"
    DIAGNOSIS_CREATED = "DIAGNOSIS_CREATED"
    LLM_EVIDENCE_HALLUCINATION = "LLM_EVIDENCE_HALLUCINATION"
    LLM_FALLBACK_TRIGGERED = "LLM_FALLBACK_TRIGGERED"
    PROBABILITY_ESTIMATED = "PROBABILITY_ESTIMATED"
    ALLOCATION_CREATED = "ALLOCATION_CREATED"
    SOLVER_INFEASIBLE = "SOLVER_INFEASIBLE"
    SOLVER_ERROR = "SOLVER_ERROR"
    POLICY_CHECKED = "POLICY_CHECKED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    ACTION_VERIFIED = "ACTION_VERIFIED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    ACTION_ESCALATED = "ACTION_ESCALATED"
    DUPLICATE_EXECUTION_BLOCKED = "DUPLICATE_EXECUTION_BLOCKED"
    EXTERNAL_API_FAILURE = "EXTERNAL_API_FAILURE"
    RUN_HALTED_POLICY_ANOMALY = "RUN_HALTED_POLICY_ANOMALY"
    # Phase 5 execution-service-specific events (finer-grained than the
    # Part O baseline list above; both taxonomies coexist deliberately —
    # ACTION_EXECUTED/ACTION_VERIFIED are strategy-level summary events,
    # EXECUTION_* below are the execution service's own detailed trail).
    EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
    EXECUTION_CLAIMED = "EXECUTION_CLAIMED"
    EXECUTION_DISPATCHED = "EXECUTION_DISPATCHED"
    EXECUTION_VERIFIED = "EXECUTION_VERIFIED"
    EXECUTION_BLOCKED = "EXECUTION_BLOCKED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_VERIFICATION_FAILED = "EXECUTION_VERIFICATION_FAILED"
    EXECUTION_UNCERTAIN = "EXECUTION_UNCERTAIN"


# Fixed catalog of valid (ItemType, InterventionType) pairs.
# Enforced at optimizer variable-construction time (Part D/J) — this is the
# single source of truth both the optimizer and the tests import from,
# so "no PAYMENT_RETRY on a B2B_RECEIVABLE" can never drift out of sync.
VALID_INTERVENTIONS_BY_ITEM_TYPE: dict[ItemType, tuple[InterventionType, ...]] = {
    ItemType.PAYMENT_FAILURE: (
        InterventionType.PAYMENT_RETRY,
        InterventionType.WHATSAPP_REMINDER,
        InterventionType.HUMAN_ESCALATION,
    ),
    ItemType.B2B_RECEIVABLE: (
        InterventionType.WHATSAPP_REMINDER,
        InterventionType.HUMAN_ESCALATION,
    ),
}
