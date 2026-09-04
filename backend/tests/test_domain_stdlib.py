"""
Domain model tests — STDLIB ONLY, actually executable in this environment
with `python3 -m unittest` (no pytest/pydantic install required).

These exercise domain/models_stdlib_mirror.py. The equivalent pydantic-based
tests for domain/models.py live in test_domain.py and require
`pip install -r requirements.txt` to run (pytest + pydantic) — see that
file's docstring for the exact command. Both test files assert the same
validation rules against their respective implementations.
"""
import sys
import os
import unittest
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.enums import (
    ItemType,
    InterventionType,
    ItemStatus,
    DiagnosisSource,
    SolverStatus,
    VALID_INTERVENTIONS_BY_ITEM_TYPE,
)
from domain.models_stdlib_mirror import (
    RecoverableItem,
    Diagnosis,
    ProbabilityEstimate,
    Intervention,
    ValidationError,
    INTERVENTION_CATALOG,
)


def make_valid_item(**overrides) -> RecoverableItem:
    defaults = dict(
        id="item_001",
        type=ItemType.PAYMENT_FAILURE,
        merchant_id="merchant_a",
        customer_id="cust_1",
        amount=Decimal("1500.00"),
        created_at=datetime(2026, 1, 1),
        evidence_text="Card declined, insufficient funds per issuer.",
    )
    defaults.update(overrides)
    return RecoverableItem(**defaults)


class TestRecoverableItemValidation(unittest.TestCase):
    def test_valid_item_constructs(self):
        item = make_valid_item()
        self.assertEqual(item.status, ItemStatus.PENDING)
        self.assertEqual(item.currency, "INR")

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValidationError):
            make_valid_item(amount=Decimal("-10"))

    def test_negative_days_overdue_rejected(self):
        with self.assertRaises(ValidationError):
            make_valid_item(days_overdue=-1)

    def test_negative_historical_attempts_rejected(self):
        with self.assertRaises(ValidationError):
            make_valid_item(historical_attempts=-1)

    def test_invalid_currency_rejected(self):
        with self.assertRaises(ValidationError):
            make_valid_item(currency="USD")

    def test_invalid_policy_tier_rejected(self):
        with self.assertRaises(ValidationError):
            make_valid_item(merchant_recovery_policy_tier="whatever")

    def test_valid_policy_tiers_accepted(self):
        for tier in ("standard", "strict", "lenient"):
            item = make_valid_item(merchant_recovery_policy_tier=tier)
            self.assertEqual(item.merchant_recovery_policy_tier, tier)

    def test_wrong_type_enum_rejected(self):
        with self.assertRaises(ValidationError):
            make_valid_item(type="not_an_enum_member")

    def test_b2b_receivable_item_constructs(self):
        item = make_valid_item(
            type=ItemType.B2B_RECEIVABLE,
            due_at=datetime(2026, 2, 1),
            days_overdue=45,
            evidence_text="Invoice 45 days overdue, client requested extension.",
        )
        self.assertEqual(item.type, ItemType.B2B_RECEIVABLE)
        self.assertEqual(item.days_overdue, 45)

    def test_risk_flags_default_empty(self):
        item = make_valid_item()
        self.assertEqual(item.risk_flags, [])

    def test_fraud_suspect_flag_stored(self):
        item = make_valid_item(risk_flags=["fraud_suspect"])
        self.assertIn("fraud_suspect", item.risk_flags)


class TestDiagnosisValidation(unittest.TestCase):
    def test_valid_diagnosis(self):
        d = Diagnosis(
            item_id="item_001",
            source=DiagnosisSource.RULE_TABLE,
            failure_class="insufficient_funds",
            confidence=0.8,
        )
        self.assertEqual(d.confidence, 0.8)

    def test_confidence_out_of_range_high_rejected(self):
        with self.assertRaises(ValidationError):
            Diagnosis(
                item_id="item_001",
                source=DiagnosisSource.RULE_TABLE,
                failure_class="insufficient_funds",
                confidence=1.5,
            )

    def test_confidence_out_of_range_low_rejected(self):
        with self.assertRaises(ValidationError):
            Diagnosis(
                item_id="item_001",
                source=DiagnosisSource.LLM,
                failure_class="unclear",
                confidence=-0.1,
            )

    def test_zero_confidence_allowed(self):
        # The fail-safe path (Part I) deliberately produces confidence=0.0
        d = Diagnosis(
            item_id="item_001",
            source=DiagnosisSource.LLM,
            failure_class="unclear",
            confidence=0.0,
            recommended_interventions=[InterventionType.HUMAN_ESCALATION],
        )
        self.assertEqual(d.confidence, 0.0)
        self.assertEqual(d.recommended_interventions, [InterventionType.HUMAN_ESCALATION])


class TestProbabilityEstimateValidation(unittest.TestCase):
    def test_valid_probability(self):
        p = ProbabilityEstimate(
            item_id="item_001",
            intervention=InterventionType.PAYMENT_RETRY,
            p_recover=0.42,
            model_version="v1",
        )
        self.assertEqual(p.p_recover, 0.42)

    def test_probability_above_one_rejected(self):
        with self.assertRaises(ValidationError):
            ProbabilityEstimate(
                item_id="item_001",
                intervention=InterventionType.PAYMENT_RETRY,
                p_recover=1.01,
                model_version="v1",
            )

    def test_probability_below_zero_rejected(self):
        with self.assertRaises(ValidationError):
            ProbabilityEstimate(
                item_id="item_001",
                intervention=InterventionType.PAYMENT_RETRY,
                p_recover=-0.01,
                model_version="v1",
            )


class TestInterventionCatalog(unittest.TestCase):
    """
    These tests directly enforce the "valid intervention per item type"
    invariant that Part D/J says must never be left to the policy engine
    to catch after the fact — it must be structurally true.
    """

    def test_catalog_has_exactly_three_interventions(self):
        self.assertEqual(len(INTERVENTION_CATALOG), 3)

    def test_payment_retry_valid_only_for_payment_failure(self):
        valid_types = [
            item_type
            for item_type, interventions in VALID_INTERVENTIONS_BY_ITEM_TYPE.items()
            if InterventionType.PAYMENT_RETRY in interventions
        ]
        self.assertEqual(valid_types, [ItemType.PAYMENT_FAILURE])

    def test_whatsapp_and_human_valid_for_both_types(self):
        for item_type in (ItemType.PAYMENT_FAILURE, ItemType.B2B_RECEIVABLE):
            valid = VALID_INTERVENTIONS_BY_ITEM_TYPE[item_type]
            self.assertIn(InterventionType.WHATSAPP_REMINDER, valid)
            self.assertIn(InterventionType.HUMAN_ESCALATION, valid)

    def test_catalog_costs_are_nonnegative(self):
        for intervention in INTERVENTION_CATALOG.values():
            self.assertGreaterEqual(intervention.cost_inr, Decimal("0"))

    def test_invalid_execution_adapter_rejected(self):
        with self.assertRaises(ValidationError):
            Intervention(
                type=InterventionType.PAYMENT_RETRY,
                resources_consumed={"retry_slots": 1},
                cost_inr=Decimal("2"),
                max_frequency_per_item=3,
                expected_duration_minutes=1,
                execution_adapter="not_a_real_adapter",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
