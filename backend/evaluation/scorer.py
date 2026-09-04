"""
Evaluation scorer - RECOVER-ALLOC, Phase 7.

THE ONLY module (besides oracle.py, which needs p_true for its
allocation decision, not its outcome sampling) permitted to read
data/test_set_ground_truth.jsonl. Strategies never import this module.
"""
import hashlib
import json
import os
import random

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def verify_and_load_frozen_test_set(data_dir=DATA_DIR, n_items=None):
    """
    Loads the OBSERVABLE frozen test set only (no hidden fields). Refuses
    to proceed if the checksum doesn't match the recorded one.
    """
    test_path = os.path.join(data_dir, "test_set_frozen.jsonl")
    checksum_path = os.path.join(data_dir, "test_set.checksum")

    if not os.path.exists(test_path) or not os.path.exists(checksum_path):
        raise RuntimeError("frozen test set not found - run `python -m simulation.freeze_test_set` first")

    with open(checksum_path) as f:
        recorded_checksum = f.read().strip()
    live_checksum = _sha256_of_file(test_path)
    if recorded_checksum != live_checksum:
        raise RuntimeError(
            f"FROZEN TEST SET CHECKSUM MISMATCH - refusing to evaluate. "
            f"recorded={recorded_checksum} live={live_checksum}. "
            f"The frozen dataset must never be modified after freezing."
        )

    items = []
    with open(test_path) as f:
        for line in f:
            items.append(json.loads(line))

    if n_items is not None:
        items = items[:n_items]
    return items


class HiddenGroundTruthScorer:
    """
    Loaded once per evaluation run. Provides read access to p_true (for
    Oracle's ALLOCATION decision only - never for outcome sampling) and
    to the independent true_diagnostic_class label, and provides
    deterministic, re-samplable realized-outcome draws for the
    stochastic evaluation (multiple seeds, common random numbers).
    """

    def __init__(self, data_dir=DATA_DIR):
        gt_path = os.path.join(data_dir, "test_set_ground_truth.jsonl")
        self._by_item_id = {}
        with open(gt_path) as f:
            for line in f:
                row = json.loads(line)
                self._by_item_id[row["item_id"]] = row

    def p_true(self, item_id, intervention_value):
        row = self._by_item_id.get(item_id)
        if row is None:
            return None
        return row["p_true_by_intervention"].get(intervention_value)

    def true_diagnostic_class(self, item_id):
        row = self._by_item_id.get(item_id)
        return row["true_diagnostic_class"] if row else None

    def sample_realized_outcome(self, item_id, intervention_value, eval_seed):
        """
        Common-random-numbers design, documented not incidental: RNG is
        seeded from (eval_seed, item_id, intervention_value) - NOT from
        strategy identity or allocation order. If two strategies choose
        the SAME (item, intervention) pair under the SAME eval_seed,
        they get the IDENTICAL realized draw, making cross-strategy
        comparison fair. This is a fresh re-sampling at evaluation time,
        NOT a reuse of the single fixed draw baked into
        sampled_outcome_by_intervention at dataset-generation time (a
        separate concept used for Phase 2's training labels).
        """
        p = self.p_true(item_id, intervention_value)
        if p is None:
            return False
        rng = random.Random(f"{eval_seed}:{item_id}:{intervention_value}")
        return rng.random() < p

    def diagnosis_accuracy(self, diagnoses):
        """
        `diagnoses`: item_id -> failure_class (string). Scored against
        the INDEPENDENT true_diagnostic_class (see
        simulation/ground_truth.py for why this is not tautological,
        unlike Phase 6's original reference label).
        """
        if not diagnoses:
            return 0.0
        correct = sum(
            1 for item_id, predicted in diagnoses.items()
            if predicted == self.true_diagnostic_class(item_id)
        )
        return correct / len(diagnoses)
