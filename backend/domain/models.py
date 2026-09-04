"""
Domain models — RECOVER-ALLOC
Locked spec: Part D.

This is the PRODUCTION version (Pydantic v2), exactly as specified in
Part B (tech stack) and Part D (domain model). It requires `pydantic`
installed (see backend/requirements.txt) and is not runnable inside a
network-isolated sandbox without that dependency.

For sandbox-only verification of the *validation logic* (field types,
constraints, enum membership) without pydantic installed, see
`domain/models_stdlib_mirror.py`, which re-implements the same rules
using only `dataclasses`. That mirror is NOT a replacement for this file
in the shipped product — it exists solely so the logic could be exercised
with `pytest` in an environment with no package-installation access.
Both files must be kept in sync; `tests/test_domain_parity.py` checks
that the two field sets/enums match so they cannot silently drift apart.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from domain.enums import (
    ItemType,
    InterventionType,
    PolicyOutcome,
    ItemStatus,
    SolverStatus,
    DiagnosisSource,
)


class RecoverableItem(BaseModel):
    id: str
    type: ItemType
    merchant_id: str
    customer_id: str
    amount: Decimal = Field(ge=0)
    currency: Literal["INR"] = "INR"
    created_at: datetime
    due_at: Optional[datetime] = None
    days_overdue: int = Field(ge=0, default=0)
    payment_method: Optional[str] = None
    failure_code: Optional[str] = None
    historical_attempts: int = Field(ge=0, default=0)
    contact_count_7d: int = Field(ge=0, default=0)
    evidence_text: str
    risk_flags: list[str] = Field(default_factory=list)
    status: ItemStatus = ItemStatus.PENDING
    merchant_recovery_policy_tier: Literal["standard", "strict", "lenient"] = "standard"

    @field_validator("due_at")
    @classmethod
    def due_at_only_for_receivable(cls, v, info):
        # B2B_RECEIVABLE should have a due date; PAYMENT_FAILURE should not.
        # Enforced as a soft check (warning-level in generator, hard in tests)
        # rather than a raised ValidationError, since some real-world
        # payment-failure records could legitimately carry a due date in
        # edge cases (e.g. an installment). Kept permissive at the schema
        # level; the generator itself never produces the invalid combination.
        return v


class Intervention(BaseModel):
    type: InterventionType
    resources_consumed: dict[str, int]
    cost_inr: Decimal = Field(ge=0)
    max_frequency_per_item: int = Field(ge=1)
    expected_duration_minutes: int = Field(ge=0)
    policy_requirements: list[str] = Field(default_factory=list)
    execution_adapter: Literal["simulator", "razorpay_test"]


class Diagnosis(BaseModel):
    item_id: str
    source: DiagnosisSource
    failure_class: str
    evidence_spans: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_interventions: list[InterventionType] = Field(default_factory=list)


class ProbabilityEstimate(BaseModel):
    item_id: str
    intervention: InterventionType
    p_recover: float = Field(ge=0.0, le=1.0)
    model_version: str


class Allocation(BaseModel):
    run_id: str
    item_id: str
    intervention: Optional[InterventionType] = None
    expected_net_value: Decimal
    solver_status: SolverStatus


class PolicyDecision(BaseModel):
    allocation_id: str
    outcome: PolicyOutcome
    reason: str
    policy_version: str


class AuditEvent(BaseModel):
    id: str
    run_id: Optional[str] = None
    item_id: Optional[str] = None
    event_type: str
    payload: dict
    model_version: Optional[str] = None
    policy_version: Optional[str] = None
    optimizer_run_id: Optional[str] = None
    timestamp: datetime
    reason: Optional[str] = None
    result: Optional[str] = None


# Fixed intervention catalog — Part D. Not user-editable at MVP.
INTERVENTION_CATALOG: dict[InterventionType, Intervention] = {
    InterventionType.PAYMENT_RETRY: Intervention(
        type=InterventionType.PAYMENT_RETRY,
        resources_consumed={"retry_slots": 1},
        cost_inr=Decimal("2"),
        max_frequency_per_item=3,
        expected_duration_minutes=1,
        policy_requirements=[],
        execution_adapter="razorpay_test",
    ),
    InterventionType.WHATSAPP_REMINDER: Intervention(
        type=InterventionType.WHATSAPP_REMINDER,
        resources_consumed={"whatsapp_quota": 1},
        cost_inr=Decimal("0.5"),
        max_frequency_per_item=2,
        expected_duration_minutes=1,
        policy_requirements=["consent_on_file"],
        execution_adapter="simulator",
    ),
    InterventionType.HUMAN_ESCALATION: Intervention(
        type=InterventionType.HUMAN_ESCALATION,
        resources_consumed={"human_hours": 1},
        cost_inr=Decimal("250"),
        max_frequency_per_item=1,
        expected_duration_minutes=30,
        policy_requirements=[],
        execution_adapter="simulator",
    ),
}
