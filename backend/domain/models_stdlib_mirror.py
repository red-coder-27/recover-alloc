"""
STDLIB MIRROR of domain/models.py — sandbox-testability only.

WHY THIS FILE EXISTS (read this before touching it):
The build environment used to author this repo had no network egress
(pip/PyPI unreachable), so `pydantic` could not be installed to actually
execute and verify domain-model validation logic. Rather than claim tests
passed without running them, this module re-implements the *same* field
set, constraints, and enum membership rules using only `dataclasses` +
manual `__post_init__` validation, so the logic could be genuinely
exercised with stdlib `unittest`/`pytest` right now.

THIS IS NOT THE PRODUCTION MODEL. `domain/models.py` (Pydantic v2) is the
real, shipped implementation per the locked spec (Part B, Part D). Once
`pip install -r requirements.txt` succeeds in a normal environment, run
`tests/test_domain_parity.py`, which asserts field names/types/enum
values match between this mirror and the real model — if they ever drift,
that test fails loudly rather than letting the mirror go stale.

Do not add a feature here without also adding it to domain/models.py,
and vice versa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from domain.enums import (
    ItemType,
    InterventionType,
    PolicyOutcome,
    ItemStatus,
    SolverStatus,
    DiagnosisSource,
)

VALID_CURRENCIES = {"INR"}
VALID_POLICY_TIERS = {"standard", "strict", "lenient"}
VALID_EXECUTION_ADAPTERS = {"simulator", "razorpay_test"}


class ValidationError(Exception):
    pass


@dataclass
class RecoverableItem:
    id: str
    type: ItemType
    merchant_id: str
    customer_id: str
    amount: Decimal
    created_at: datetime
    evidence_text: str
    currency: str = "INR"
    due_at: Optional[datetime] = None
    days_overdue: int = 0
    payment_method: Optional[str] = None
    failure_code: Optional[str] = None
    historical_attempts: int = 0
    contact_count_7d: int = 0
    risk_flags: list[str] = field(default_factory=list)
    status: ItemStatus = ItemStatus.PENDING
    merchant_recovery_policy_tier: str = "standard"

    def __post_init__(self):
        if self.amount < 0:
            raise ValidationError(f"amount must be >= 0, got {self.amount}")
        if self.currency not in VALID_CURRENCIES:
            raise ValidationError(f"unsupported currency: {self.currency}")
        if self.days_overdue < 0:
            raise ValidationError("days_overdue must be >= 0")
        if self.historical_attempts < 0:
            raise ValidationError("historical_attempts must be >= 0")
        if self.contact_count_7d < 0:
            raise ValidationError("contact_count_7d must be >= 0")
        if self.merchant_recovery_policy_tier not in VALID_POLICY_TIERS:
            raise ValidationError(
                f"invalid policy tier: {self.merchant_recovery_policy_tier}"
            )
        if not isinstance(self.type, ItemType):
            raise ValidationError(f"type must be an ItemType, got {type(self.type)}")


@dataclass
class Intervention:
    type: InterventionType
    resources_consumed: dict[str, int]
    cost_inr: Decimal
    max_frequency_per_item: int
    expected_duration_minutes: int
    execution_adapter: str
    policy_requirements: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.cost_inr < 0:
            raise ValidationError("cost_inr must be >= 0")
        if self.max_frequency_per_item < 1:
            raise ValidationError("max_frequency_per_item must be >= 1")
        if self.expected_duration_minutes < 0:
            raise ValidationError("expected_duration_minutes must be >= 0")
        if self.execution_adapter not in VALID_EXECUTION_ADAPTERS:
            raise ValidationError(f"invalid execution_adapter: {self.execution_adapter}")


@dataclass
class Diagnosis:
    item_id: str
    source: DiagnosisSource
    failure_class: str
    confidence: float
    evidence_spans: list[str] = field(default_factory=list)
    recommended_interventions: list[InterventionType] = field(default_factory=list)

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValidationError(f"confidence must be in [0,1], got {self.confidence}")


@dataclass
class ProbabilityEstimate:
    item_id: str
    intervention: InterventionType
    p_recover: float
    model_version: str

    def __post_init__(self):
        if not (0.0 <= self.p_recover <= 1.0):
            raise ValidationError(f"p_recover must be in [0,1], got {self.p_recover}")


@dataclass
class Allocation:
    run_id: str
    item_id: str
    expected_net_value: Decimal
    solver_status: SolverStatus
    intervention: Optional[InterventionType] = None


@dataclass
class PolicyDecision:
    allocation_id: str
    outcome: PolicyOutcome
    reason: str
    policy_version: str


@dataclass
class AuditEvent:
    id: str
    event_type: str
    payload: dict
    timestamp: datetime
    run_id: Optional[str] = None
    item_id: Optional[str] = None
    model_version: Optional[str] = None
    policy_version: Optional[str] = None
    optimizer_run_id: Optional[str] = None
    reason: Optional[str] = None
    result: Optional[str] = None


# Same fixed catalog as the production model — kept identical intentionally.
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
