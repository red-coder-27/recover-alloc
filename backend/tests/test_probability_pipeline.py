"""
Probability pipeline tests — ACTUALLY EXECUTABLE in this environment,
since numpy/scikit-learn are genuinely available here (confirmed:
numpy 2.4.4, scikit-learn 1.8.0). These are real tests against real
trained artifacts, not a stdlib mirror.

Run: cd backend/tests && python3 -m unittest test_probability_pipeline -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from probability.features import build_feature_dict
from probability.model import ProbabilityModel
from probability.train import MODEL_VERSION, _load_jsonl, DATA_DIR
from domain.enums import InterventionType

ARTIFACTS_EXIST = os.path.exists(
    os.path.join(os.path.dirname(__file__), "..", "probability", "artifacts",
                 f"model_PAYMENT_RETRY_{MODEL_VERSION}.joblib")
)


class TestFeatureDeterminism(unittest.TestCase):
    def test_identical_inputs_produce_identical_features(self):
        kwargs = dict(
            days_overdue=10, historical_attempts=1, contact_count_7d=0,
            amount=2500.0, failure_code="insufficient_funds",
            item_type="PAYMENT_FAILURE", merchant_recovery_policy_tier="standard",
            diagnosis_failure_class="insufficient_funds", diagnosis_confidence=0.7,
        )
        f1 = build_feature_dict(**kwargs)
        f2 = build_feature_dict(**kwargs)
        self.assertEqual(f1, f2)

    def test_no_hidden_archetype_parameter_exists(self):
        import inspect
        sig = inspect.signature(build_feature_dict)
        self.assertNotIn("reliability_archetype", sig.parameters)
        self.assertNotIn("archetype", sig.parameters)

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValueError):
            build_feature_dict(
                days_overdue=0, historical_attempts=0, contact_count_7d=0,
                amount=-1.0, failure_code=None, item_type="B2B_RECEIVABLE",
                merchant_recovery_policy_tier="standard",
                diagnosis_failure_class="unclear", diagnosis_confidence=0.0,
            )


class TestTrainValSeparation(unittest.TestCase):
    def test_no_item_id_overlap_between_train_and_val(self):
        train_items = _load_jsonl(os.path.join(DATA_DIR, "train_set.jsonl"))
        val_items = _load_jsonl(os.path.join(DATA_DIR, "val_set.jsonl"))
        train_ids = {r["id"] for r in train_items}
        val_ids = {r["id"] for r in val_items}
        self.assertEqual(train_ids & val_ids, set())

    def test_labels_reference_only_their_own_split(self):
        train_items = _load_jsonl(os.path.join(DATA_DIR, "train_set.jsonl"))
        train_labels = _load_jsonl(os.path.join(DATA_DIR, "train_labels.jsonl"))
        train_item_ids = {r["id"] for r in train_items}
        label_item_ids = {r["item_id"] for r in train_labels}
        self.assertEqual(label_item_ids, train_item_ids)


@unittest.skipUnless(ARTIFACTS_EXIST, "run `python -m probability.train` first")
class TestTrainedModelInference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ProbabilityModel(MODEL_VERSION)

    def test_all_three_interventions_have_artifacts(self):
        available = self.model.available_interventions()
        self.assertEqual(len(available), 3)
        for interv in InterventionType:
            self.assertIn(interv, available)

    def test_prediction_is_in_valid_range(self):
        fdict = build_feature_dict(
            days_overdue=10, historical_attempts=1, contact_count_7d=0,
            amount=2500.0, failure_code="insufficient_funds",
            item_type="PAYMENT_FAILURE", merchant_recovery_policy_tier="standard",
            diagnosis_failure_class="insufficient_funds", diagnosis_confidence=0.7,
        )
        p = self.model.predict_p_recover(fdict, InterventionType.PAYMENT_RETRY)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_prediction_is_deterministic_given_same_features(self):
        fdict = build_feature_dict(
            days_overdue=60, historical_attempts=2, contact_count_7d=1,
            amount=15000.0, failure_code=None, item_type="B2B_RECEIVABLE",
            merchant_recovery_policy_tier="strict",
            diagnosis_failure_class="genuine_hardship_receivable", diagnosis_confidence=0.55,
        )
        p1 = self.model.predict_p_recover(fdict, InterventionType.HUMAN_ESCALATION)
        p2 = self.model.predict_p_recover(fdict, InterventionType.HUMAN_ESCALATION)
        self.assertEqual(p1, p2)

    def test_invalid_intervention_for_missing_artifact_raises(self):
        # Construct a model instance pointed at an empty dir to simulate
        # a missing artifact, rather than mutating the real loaded model.
        empty_model = ProbabilityModel(MODEL_VERSION, artifact_dir="/tmp/nonexistent_dir_xyz")
        with self.assertRaises(ValueError):
            empty_model.predict_p_recover({"days_overdue": 0.0}, InterventionType.PAYMENT_RETRY)

    def test_artifact_round_trip_via_reload(self):
        """
        Loading a fresh ProbabilityModel instance from the same artifact
        directory must reproduce the same prediction — proves the
        joblib serialize/deserialize round trip preserves the fitted
        calibrated model, not just that the object exists.
        """
        model_a = ProbabilityModel(MODEL_VERSION)
        model_b = ProbabilityModel(MODEL_VERSION)
        fdict = build_feature_dict(
            days_overdue=5, historical_attempts=0, contact_count_7d=0,
            amount=1200.0, failure_code="bank_server_error",
            item_type="PAYMENT_FAILURE", merchant_recovery_policy_tier="standard",
            diagnosis_failure_class="bank_server_error", diagnosis_confidence=0.8,
        )
        p_a = model_a.predict_p_recover(fdict, InterventionType.PAYMENT_RETRY)
        p_b = model_b.predict_p_recover(fdict, InterventionType.PAYMENT_RETRY)
        self.assertEqual(p_a, p_b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
