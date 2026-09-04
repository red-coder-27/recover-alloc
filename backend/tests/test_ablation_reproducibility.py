"""
Ablation reproducibility test - RECOVER-ALLOC, Phase 6 gate requirement.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from diagnosis.ablation_pipeline import run_ablation_arm
from diagnosis.rule_diagnoser import diagnose as rule_diagnose
from probability.model import ProbabilityModel
from probability.train import MODEL_VERSION, _load_jsonl, DATA_DIR

ARTIFACTS_EXIST = os.path.exists(
    os.path.join(os.path.dirname(__file__), "..", "probability", "artifacts",
                 f"model_PAYMENT_RETRY_{MODEL_VERSION}.joblib")
)


@unittest.skipUnless(ARTIFACTS_EXIST, "run `python -m probability.train` first")
class TestAblationReproducibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_items = _load_jsonl(os.path.join(DATA_DIR, "test_set_frozen.jsonl"))[:30]
        cls.model = ProbabilityModel(MODEL_VERSION)
        cls.resources_budget = {"retry_slots": 10, "whatsapp_quota": 10, "human_hours": 3}

    def test_same_batch_same_diagnoser_produces_identical_results(self):
        r1 = run_ablation_arm(
            items=self.test_items, diagnoser_fn=rule_diagnose, diagnosis_source_label="rule_table",
            probability_model=self.model, resources_budget=self.resources_budget, run_id="repro_a",
        )
        r2 = run_ablation_arm(
            items=self.test_items, diagnoser_fn=rule_diagnose, diagnosis_source_label="rule_table",
            probability_model=self.model, resources_budget=self.resources_budget, run_id="repro_a",
        )
        self.assertEqual(r1.failure_class_accuracy, r2.failure_class_accuracy)
        self.assertEqual(r1.policy_allow_count, r2.policy_allow_count)
        self.assertEqual(r1.expected_net_recovery, r2.expected_net_recovery)
        self.assertEqual(r1.actual_simulated_net_recovery, r2.actual_simulated_net_recovery)
        self.assertEqual(r1.execution_count, r2.execution_count)

    def test_policy_violation_count_is_always_zero(self):
        """The one metric that must be zero regardless of diagnosis source."""
        result = run_ablation_arm(
            items=self.test_items, diagnoser_fn=rule_diagnose, diagnosis_source_label="rule_table",
            probability_model=self.model, resources_budget=self.resources_budget, run_id="repro_b",
        )
        self.assertEqual(result.policy_violation_count, 0)

    def test_different_run_id_does_not_change_the_measured_outcome(self):
        """run_id only affects idempotency keys, not the diagnosis/
        allocation/policy decisions themselves."""
        r1 = run_ablation_arm(
            items=self.test_items, diagnoser_fn=rule_diagnose, diagnosis_source_label="rule_table",
            probability_model=self.model, resources_budget=self.resources_budget, run_id="run_x",
        )
        r2 = run_ablation_arm(
            items=self.test_items, diagnoser_fn=rule_diagnose, diagnosis_source_label="rule_table",
            probability_model=self.model, resources_budget=self.resources_budget, run_id="run_y",
        )
        self.assertEqual(r1.policy_allow_count, r2.policy_allow_count)
        self.assertEqual(r1.expected_net_recovery, r2.expected_net_recovery)


if __name__ == "__main__":
    unittest.main(verbosity=2)
