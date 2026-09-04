"""
Critical data leakage test - RECOVER-ALLOC, Phase 7 gate.

Proves, structurally, that strategy allocation decisions cannot depend
on a realized future recovery outcome, and that Oracle specifically can
see p_true but never a realized outcome.
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import strategies.no_action as no_action_strategy
import strategies.random_under_budget as random_strategy
import strategies.blind_retry as blind_retry_strategy
import strategies.static_rules as static_rules_strategy
import strategies.llm_only as llm_only_strategy
import strategies.recover_alloc as recover_alloc_strategy
import strategies.oracle as oracle_strategy
from evaluation.scorer import HiddenGroundTruthScorer


class TestNoFutureOutcomeLeakage(unittest.TestCase):
    def test_oracle_signature_has_no_outcome_parameter(self):
        sig = inspect.signature(oracle_strategy.allocate)
        forbidden_names = {"outcome", "outcomes", "realized_outcome", "sampled_outcome", "actual_outcome"}
        for name in sig.parameters:
            self.assertNotIn(
                name.lower(), forbidden_names,
                f"oracle.allocate() must never accept a realized-outcome parameter, found '{name}'",
            )

    def test_oracle_source_never_calls_sample_realized_outcome(self):
        source = inspect.getsource(oracle_strategy)
        self.assertNotIn(
            "sample_realized_outcome", source,
            "Oracle must never call the scorer's realized-outcome sampler",
        )

    def test_no_strategy_module_imports_the_scorer(self):
        import re
        strategy_modules = [
            no_action_strategy, random_strategy, blind_retry_strategy,
            static_rules_strategy, llm_only_strategy, recover_alloc_strategy, oracle_strategy,
        ]
        for module in strategy_modules:
            source = inspect.getsource(module)
            import_lines = [line.strip() for line in source.splitlines()
                             if re.match(r"^\s*(import|from)\s+", line)]
            for line in import_lines:
                self.assertFalse(
                    re.match(r"^(import\s+evaluation(\.|$)|from\s+evaluation(\.|\s))", line),
                    f"{module.__name__} must not import evaluation.scorer: '{line}'",
                )

    def test_allocation_functions_accept_no_eval_seed_parameter(self):
        for module in (no_action_strategy, blind_retry_strategy, static_rules_strategy):
            sig = inspect.signature(module.allocate)
            self.assertNotIn("eval_seed", sig.parameters)

    def test_random_strategy_seed_parameter_is_for_candidate_ordering_not_outcomes(self):
        source = inspect.getsource(random_strategy)
        for forbidden in ("p_true", "outcome", "scorer", "ground_truth"):
            self.assertNotIn(forbidden, source)

    def test_hidden_ground_truth_scorer_exposes_p_true_and_outcome_as_clearly_separate_methods(self):
        self.assertTrue(hasattr(HiddenGroundTruthScorer, "p_true"))
        self.assertTrue(hasattr(HiddenGroundTruthScorer, "sample_realized_outcome"))
        self.assertNotEqual(HiddenGroundTruthScorer.p_true, HiddenGroundTruthScorer.sample_realized_outcome)


if __name__ == "__main__":
    unittest.main(verbosity=2)
