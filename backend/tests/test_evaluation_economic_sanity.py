"""
Economic sanity tests - RECOVER-ALLOC, Phase 7 gate.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.models_stdlib_mirror import INTERVENTION_CATALOG
from evaluation.run import run_evaluation, _build_items_and_probabilities
from evaluation.scorer import verify_and_load_frozen_test_set
from probability.model import ProbabilityModel
from probability.train import MODEL_VERSION

ARTIFACTS_EXIST = os.path.exists(
    os.path.join(os.path.dirname(__file__), "..", "probability", "artifacts",
                 f"model_PAYMENT_RETRY_{MODEL_VERSION}.joblib")
)


@unittest.skipUnless(ARTIFACTS_EXIST, "run `python -m probability.train` first")
class TestEconomicSanity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_evaluation(n_items=40, n_seeds=5, run_id="test_economic_sanity")

    def test_no_action_recovered_amount_is_zero(self):
        d = self.report["strategies"]["no_action"]
        self.assertEqual(d["expected_objective"], 0.0)
        self.assertEqual(d["realized_net_recovered"]["mean"], 0.0)
        self.assertEqual(d["n_items_served"], 0)

    def test_allocations_never_exceed_budgets_for_all_available_strategies(self):
        for name, d in self.report["strategies"].items():
            if d["status"] != "OK":
                continue
            self.assertEqual(d["feasibility_violations"], [], f"{name} produced infeasible allocations")

    def test_intervention_costs_are_positive(self):
        for interv, entry in INTERVENTION_CATALOG.items():
            self.assertGreater(entry.cost_inr, 0, f"{interv} must have a nonzero cost")

    def test_policy_violations_zero_for_recover_alloc_or_marked_unavailable(self):
        d = self.report["strategies"]["recover_alloc"]
        if d["status"] == "UNAVAILABLE":
            self.assertIn("ortools", d["dependency"])
        else:
            self.assertEqual(d["feasibility_violations"], [])

    def test_frozen_checksum_is_verified_before_evaluation_runs(self):
        from evaluation.scorer import _sha256_of_file
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
        test_path = os.path.join(data_dir, "test_set_frozen.jsonl")
        checksum_path = os.path.join(data_dir, "test_set.checksum")
        with open(checksum_path) as f:
            recorded = f.read().strip()
        self.assertEqual(recorded, _sha256_of_file(test_path))

    def test_identical_seed_and_configuration_is_reproducible(self):
        r1 = run_evaluation(n_items=20, n_seeds=3, run_id="repro_a")
        r2 = run_evaluation(n_items=20, n_seeds=3, run_id="repro_b")
        for name in ("no_action", "random_under_budget", "blind_retry", "static_rules"):
            self.assertEqual(
                r1["strategies"][name]["realized_net_recovered"]["mean"],
                r2["strategies"][name]["realized_net_recovered"]["mean"],
                f"{name} not reproducible across identical-config runs",
            )

    def test_different_seed_batch_can_change_realized_outcomes(self):
        r_many = run_evaluation(n_items=20, n_seeds=20, run_id="seed_many")
        d = r_many["strategies"]["random_under_budget"]
        if d["status"] == "OK" and d["n_items_served"] > 0:
            self.assertGreater(d["realized_net_recovered"]["stddev"], 0.0)


class TestUnavailableStrategiesAreHonestlyMarked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ARTIFACTS_EXIST:
            raise unittest.SkipTest("run `python -m probability.train` first")
        cls.report = run_evaluation(n_items=10, n_seeds=2, run_id="test_unavailable_marking")

    def test_recover_alloc_marked_unavailable_not_faked(self):
        d = self.report["strategies"]["recover_alloc"]
        if d["status"] == "UNAVAILABLE":
            self.assertIn("reason", d)
            self.assertIn("dependency", d)
            self.assertIn("command", d)
            self.assertIn("ortools", d["dependency"])
        else:
            self.assertEqual(d["status"], "OK")

    def test_oracle_marked_unavailable_not_faked(self):
        d = self.report["strategies"]["oracle"]
        if d["status"] == "UNAVAILABLE":
            self.assertIn("ortools", d["dependency"])
        else:
            self.assertEqual(d["status"], "OK")

    def test_llm_only_marked_unavailable_not_faked(self):
        d = self.report["strategies"]["llm_only"]
        self.assertEqual(d["status"], "UNAVAILABLE")
        self.assertIn("anthropic", d["dependency"])

    def test_oracle_capture_percent_marked_unavailable_when_inputs_missing(self):
        if self.report["strategies"]["recover_alloc"]["status"] == "OK" and self.report["strategies"]["oracle"]["status"] == "OK":
            self.assertIsInstance(self.report["oracle_capture_percent"], (float, int))
        else:
            self.assertIsInstance(self.report["oracle_capture_percent"], str)
            self.assertIn("UNAVAILABLE", self.report["oracle_capture_percent"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
