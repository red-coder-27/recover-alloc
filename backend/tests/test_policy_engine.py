"""
Policy engine tests — RECOVER-ALLOC, Phase 4 gate.
Real, executable, stdlib-compatible (policy/engine.py has zero external
dependencies, so this runs regardless of ortools/pydantic availability).
"""
import os
import sys
import unittest
from dataclasses import dataclass, field
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.enums import InterventionType, ItemType, PolicyOutcome
from domain.models_stdlib_mirror import INTERVENTION_CATALOG
from policy.config import PolicyConfig
from policy.engine import evaluate_policy, batch_block_rate_exceeded, PolicyDecision


@dataclass
class FixtureItem:
    id: str
    type: ItemType
    amount: Decimal
    risk_flags: list = field(default_factory=list)
    historical_attempts: int = 0
    contact_count_7d: int = 0


@dataclass
class FixtureDiagnosis:
    confidence: float


DEFAULT_CONFIG = PolicyConfig(version="test-v1")


def make_item(**overrides):
    defaults = dict(id="item_1", type=ItemType.PAYMENT_FAILURE, amount=Decimal("5000"))
    defaults.update(overrides)
    return FixtureItem(**defaults)


class TestRule1FraudFlag(unittest.TestCase):
    def test_fraud_flag_blocks_regardless_of_everything_else(self):
        item = make_item(risk_flags=["fraud_suspect"], amount=Decimal("999999"))
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.99),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.BLOCK)
        self.assertIn("fraud", decision.reason.lower())

    def test_no_fraud_flag_does_not_block_on_this_rule(self):
        item = make_item(risk_flags=[])
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertNotEqual(decision.outcome, PolicyOutcome.BLOCK)


class TestRule2LowConfidence(unittest.TestCase):
    def test_low_confidence_escalates(self):
        item = make_item()
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.1),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.ESCALATE)

    def test_confidence_exactly_at_threshold_does_not_escalate(self):
        item = make_item()
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=DEFAULT_CONFIG.confidence_escalation_threshold),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertNotEqual(decision.outcome, PolicyOutcome.ESCALATE)

    def test_zero_confidence_llm_fallback_always_escalates(self):
        """Part I's fail-safe rule: confidence=0.0 must route to ESCALATE."""
        item = make_item()
        decision = evaluate_policy(
            item=item, intervention=InterventionType.HUMAN_ESCALATION,
            diagnosis=FixtureDiagnosis(confidence=0.0),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.ESCALATE)


class TestRule3MonetaryFloor(unittest.TestCase):
    def test_below_floor_blocks(self):
        item = make_item(amount=Decimal("50"))
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.BLOCK)
        self.assertIn("floor", decision.reason.lower())

    def test_at_floor_does_not_block(self):
        item = make_item(amount=Decimal(str(DEFAULT_CONFIG.min_intervention_amount)))
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertNotEqual(decision.outcome, PolicyOutcome.BLOCK)


class TestRule4Modify(unittest.TestCase):
    def test_whatsapp_without_consent_downgrades_to_human_escalation(self):
        item = make_item(type=ItemType.PAYMENT_FAILURE, amount=Decimal("5000"))
        decision = evaluate_policy(
            item=item, intervention=InterventionType.WHATSAPP_REMINDER,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, consent_on_file=False, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.MODIFY)
        self.assertEqual(decision.original_intervention, InterventionType.WHATSAPP_REMINDER)
        self.assertEqual(decision.final_intervention, InterventionType.HUMAN_ESCALATION)

    def test_modified_allocation_is_revalidated_against_full_rule_chain(self):
        """
        A MODIFY target must itself pass every other rule — not be
        rubber-stamped. Here the alternative (HUMAN_ESCALATION) should
        still be blocked by the frequency ceiling if already exhausted.
        """
        item = make_item(
            type=ItemType.PAYMENT_FAILURE,
            historical_attempts=INTERVENTION_CATALOG[InterventionType.HUMAN_ESCALATION].max_frequency_per_item,
        )
        decision = evaluate_policy(
            item=item, intervention=InterventionType.WHATSAPP_REMINDER,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, consent_on_file=False, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.BLOCK)

    def test_whatsapp_with_consent_does_not_modify(self):
        item = make_item()
        decision = evaluate_policy(
            item=item, intervention=InterventionType.WHATSAPP_REMINDER,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, consent_on_file=True, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)


class TestRule5FrequencyCeiling(unittest.TestCase):
    def test_at_or_above_ceiling_blocks(self):
        item = make_item(historical_attempts=INTERVENTION_CATALOG[InterventionType.PAYMENT_RETRY].max_frequency_per_item)
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.BLOCK)

    def test_below_ceiling_does_not_block_on_this_rule(self):
        item = make_item(historical_attempts=0)
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertNotEqual(decision.outcome, PolicyOutcome.BLOCK)


class TestRule6ContactFatigue(unittest.TestCase):
    def test_at_or_above_fatigue_cap_blocks_contact_interventions(self):
        item = make_item(type=ItemType.B2B_RECEIVABLE, contact_count_7d=DEFAULT_CONFIG.max_contacts_per_week)
        decision = evaluate_policy(
            item=item, intervention=InterventionType.WHATSAPP_REMINDER,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.BLOCK)

    def test_fatigue_cap_does_not_apply_to_payment_retry(self):
        """PAYMENT_RETRY is not a 'contact', per Part L rule 6's scope."""
        item = make_item(type=ItemType.PAYMENT_FAILURE, contact_count_7d=99)
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertNotEqual(decision.outcome, PolicyOutcome.BLOCK)


class TestRule7Allow(unittest.TestCase):
    def test_clean_item_allows(self):
        item = make_item()
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)
        self.assertEqual(decision.final_intervention, InterventionType.PAYMENT_RETRY)


class TestPolicyPrecedenceIsDeterministic(unittest.TestCase):
    """
    Combination tests: when MULTIPLE rules could plausibly fire, the
    FIRST one in fixed order must win, every time, deterministically —
    this is what "no rule stacking/overriding ambiguity" means in
    practice, not just in prose.
    """

    def test_fraud_flag_beats_low_confidence(self):
        item = make_item(risk_flags=["fraud_suspect"])
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.01),  # would also trigger rule 2
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.BLOCK)
        self.assertIn("fraud", decision.reason.lower())

    def test_fraud_flag_beats_monetary_floor(self):
        item = make_item(risk_flags=["fraud_suspect"], amount=Decimal("1"))
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.BLOCK)
        self.assertIn("fraud", decision.reason.lower())

    def test_low_confidence_beats_monetary_floor(self):
        item = make_item(amount=Decimal("1"))  # would also trigger rule 3
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.01),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.ESCALATE)

    def test_monetary_floor_beats_frequency_ceiling(self):
        item = make_item(
            amount=Decimal("1"),
            historical_attempts=INTERVENTION_CATALOG[InterventionType.PAYMENT_RETRY].max_frequency_per_item,
        )
        decision = evaluate_policy(
            item=item, intervention=InterventionType.PAYMENT_RETRY,
            diagnosis=FixtureDiagnosis(confidence=0.9),
            interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
        )
        self.assertEqual(decision.outcome, PolicyOutcome.BLOCK)
        self.assertIn("floor", decision.reason.lower())

    def test_policy_version_always_recorded(self):
        item = make_item()
        for intervention in (InterventionType.PAYMENT_RETRY, None):
            decision = evaluate_policy(
                item=item, intervention=intervention, diagnosis=FixtureDiagnosis(confidence=0.9),
                interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
            )
            self.assertEqual(decision.policy_version, DEFAULT_CONFIG.version)


class TestBlockedAndEscalatedNeverExecute(unittest.TestCase):
    """
    Integration-style check on the DECISION LIST itself (not the
    executor, which doesn't exist as a callable unit here — this tests
    the invariant at the boundary strategies/recover_alloc.py must
    respect: only ALLOW/MODIFY-with-ALLOW-final decisions may be handed
    to the executor).
    """

    def test_only_allow_outcomes_are_eligible_for_execution(self):
        scenarios = [
            (make_item(risk_flags=["fraud_suspect"]), InterventionType.PAYMENT_RETRY, 0.9),
            (make_item(), InterventionType.PAYMENT_RETRY, 0.1),
            (make_item(amount=Decimal("1")), InterventionType.PAYMENT_RETRY, 0.9),
            (make_item(historical_attempts=99), InterventionType.PAYMENT_RETRY, 0.9),
            (make_item(type=ItemType.B2B_RECEIVABLE, contact_count_7d=99), InterventionType.WHATSAPP_REMINDER, 0.9),
            (make_item(), InterventionType.PAYMENT_RETRY, 0.9),  # the one clean ALLOW case
        ]
        decisions = [
            evaluate_policy(
                item=item, intervention=interv, diagnosis=FixtureDiagnosis(confidence=conf),
                interventions_catalog=INTERVENTION_CATALOG, config=DEFAULT_CONFIG,
            )
            for item, interv, conf in scenarios
        ]
        executable = [d for d in decisions if d.outcome == PolicyOutcome.ALLOW]
        non_executable = [d for d in decisions if d.outcome != PolicyOutcome.ALLOW]
        self.assertEqual(len(executable), 1, "exactly one clean scenario should be ALLOW")
        self.assertEqual(len(non_executable), 5)
        for d in non_executable:
            self.assertIn(d.outcome, (PolicyOutcome.BLOCK, PolicyOutcome.ESCALATE))


class TestBatchStoppingRule(unittest.TestCase):
    def test_high_block_rate_triggers_halt(self):
        decisions = [
            PolicyDecision(item_id=f"i{i}", outcome=PolicyOutcome.BLOCK, reason="x",
                            policy_version="v1", original_intervention=None, final_intervention=None)
            for i in range(5)
        ] + [
            PolicyDecision(item_id="i5", outcome=PolicyOutcome.ALLOW, reason="x",
                            policy_version="v1", original_intervention=None, final_intervention=None)
        ]
        # 5/6 blocked = 83% > 40% threshold
        self.assertTrue(batch_block_rate_exceeded(decisions, DEFAULT_CONFIG))

    def test_low_block_rate_does_not_halt(self):
        decisions = [
            PolicyDecision(item_id=f"i{i}", outcome=PolicyOutcome.ALLOW, reason="x",
                            policy_version="v1", original_intervention=None, final_intervention=None)
            for i in range(9)
        ] + [
            PolicyDecision(item_id="i9", outcome=PolicyOutcome.BLOCK, reason="x",
                            policy_version="v1", original_intervention=None, final_intervention=None)
        ]
        # 1/10 blocked = 10% < 40% threshold
        self.assertFalse(batch_block_rate_exceeded(decisions, DEFAULT_CONFIG))

    def test_empty_batch_does_not_halt(self):
        self.assertFalse(batch_block_rate_exceeded([], DEFAULT_CONFIG))


if __name__ == "__main__":
    unittest.main(verbosity=2)
