"""
Feature engineering — RECOVER-ALLOC, Locked spec Part H.

This IS the production implementation (not a sandbox mirror) — building a
feature dict from a RecoverableItem + Diagnosis requires no ML libraries,
only stdlib, so there is no environment gap here. `train.py`/`model.py`
convert this module's output into numpy arrays right before calling into
sklearn, keeping this module itself fully dependency-free and fully
testable regardless of what ML stack is installed.

LEAKAGE INVARIANT: this function's input signature intentionally has no
parameter for `reliability_archetype` or any hidden ground-truth field —
it is structurally impossible to pass one in, not just a convention.
"""
from __future__ import annotations

import math

FAILURE_CODES = [
    "insufficient_funds", "issuer_soft_decline", "bank_server_error",
    "risk_threshold_hold", "expired_card", "do_not_honor",
]
ITEM_TYPES = ["PAYMENT_FAILURE", "B2B_RECEIVABLE"]
POLICY_TIERS = ["standard", "strict", "lenient"]
# Kept in sync with diagnosis/schema.py's LLMDiagnosisOutput.failure_class
# Literal values (Part I) — intentionally a superset since rule-table
# diagnosis (Part 12/Q) may only ever emit a subset of these.
FAILURE_CLASSES = [
    "issuer_soft_decline", "insufficient_funds", "bank_server_error",
    "risk_threshold_hold", "expired_card", "do_not_honor",
    "genuine_hardship_receivable", "administrative_delay_receivable",
    "dispute_risk_receivable", "fraud_suspected", "unclear",
]


def build_feature_dict(
    *,
    days_overdue: int,
    historical_attempts: int,
    contact_count_7d: int,
    amount: float,
    failure_code: str | None,
    item_type: str,
    merchant_recovery_policy_tier: str,
    diagnosis_failure_class: str,
    diagnosis_confidence: float,
    risk_flags: list[str] | None = None,
) -> dict:
    """
    Returns a flat dict of feature_name -> value, suitable for
    sklearn.feature_extraction.DictVectorizer. One-hot categorical
    features are represented as {"feature=value": 1} sparse-style,
    which is exactly the DictVectorizer input convention, so no
    additional encoding step is needed downstream.

    Deliberately excluded (per Part H): reliability_archetype (does not
    exist as a parameter — cannot leak what was never passed in).

    `risk_flags` (added in the Phase 4 ML diagnostic follow-up): the
    locked spec (Part H) explicitly says "risk_flags is included
    deliberately so the model can learn to suppress fraud-suspect
    items" — the original implementation of this function omitted it
    entirely, which a real diagnostic (not a tuning exercise) found to
    be the single largest available, non-leaky, currently-unused signal
    (fraud-suspect items have a ~0.48 lower realized recovery rate than
    non-flagged items across all three interventions on the training
    set). Adding it is a spec-compliance fix, not a leakage-prone hack:
    `risk_flags` is an OBSERVABLE field on RecoverableItem (Part D),
    exactly like failure_code or days_overdue — not a hidden variable.
    """
    if amount < 0:
        raise ValueError(f"amount must be >= 0, got {amount}")

    risk_flags = risk_flags or []

    features: dict[str, float] = {
        "days_overdue": float(days_overdue),
        "historical_attempts": float(historical_attempts),
        "contact_count_7d": float(contact_count_7d),
        "log_amount": math.log1p(amount),
        "diagnosis_confidence": float(diagnosis_confidence),
        "risk_flag_fraud_suspect": 1.0 if "fraud_suspect" in risk_flags else 0.0,
    }

    # One-hot: failure_code (payment failures only; None -> no bit set,
    # which is itself informative — a receivable has none of these bits).
    for code in FAILURE_CODES:
        features[f"failure_code={code}"] = 1.0 if failure_code == code else 0.0

    for t in ITEM_TYPES:
        features[f"item_type={t}"] = 1.0 if item_type == t else 0.0

    for tier in POLICY_TIERS:
        features[f"policy_tier={tier}"] = 1.0 if merchant_recovery_policy_tier == tier else 0.0

    for fc in FAILURE_CLASSES:
        features[f"diagnosis_class={fc}"] = 1.0 if diagnosis_failure_class == fc else 0.0

    return features


def feature_dict_from_item_and_diagnosis(item, diagnosis) -> dict:
    """
    Convenience wrapper matching the shapes of domain.models_stdlib_mirror
    .RecoverableItem and .Diagnosis (or the pydantic equivalents, which
    expose the same attribute names) — accepts either, since both mirror
    and production models are duck-type compatible on these field names.
    """
    return build_feature_dict(
        days_overdue=item.days_overdue,
        historical_attempts=item.historical_attempts,
        contact_count_7d=item.contact_count_7d,
        amount=float(item.amount),
        failure_code=item.failure_code,
        item_type=item.type.value if hasattr(item.type, "value") else item.type,
        merchant_recovery_policy_tier=item.merchant_recovery_policy_tier,
        diagnosis_failure_class=diagnosis.failure_class,
        diagnosis_confidence=diagnosis.confidence,
        risk_flags=item.risk_flags,
    )
