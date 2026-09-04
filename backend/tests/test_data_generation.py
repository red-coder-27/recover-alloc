"""
Data generation reproducibility + checksum enforcement tests.
Actually executable now (stdlib only) — this is GATE 2 from the
Principal Engineer execution prompt: "frozen dataset generation must be
reproducible."
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulation.generator import generate_pool, split_pool, SEED
from simulation.freeze_test_set import freeze, verify_checksum, _sha256_of_file
from domain.enums import ItemType


class TestGenerationReproducibility(unittest.TestCase):
    def test_same_seed_produces_identical_pool(self):
        pool_a = generate_pool(1200, seed=SEED)
        pool_b = generate_pool(1200, seed=SEED)
        ids_a = [b.item.id for b in pool_a]
        ids_b = [b.item.id for b in pool_b]
        amounts_a = [str(b.item.amount) for b in pool_a]
        amounts_b = [str(b.item.amount) for b in pool_b]
        self.assertEqual(ids_a, ids_b)
        self.assertEqual(amounts_a, amounts_b)

    def test_same_seed_produces_identical_ground_truth(self):
        pool_a = generate_pool(1200, seed=SEED)
        pool_b = generate_pool(1200, seed=SEED)
        gt_a = [b.p_true_by_intervention for b in pool_a]
        gt_b = [b.p_true_by_intervention for b in pool_b]
        self.assertEqual(gt_a, gt_b)

    def test_different_seed_produces_different_pool(self):
        pool_a = generate_pool(1200, seed=SEED)
        pool_b = generate_pool(1200, seed=SEED + 1)
        amounts_a = [str(b.item.amount) for b in pool_a]
        amounts_b = [str(b.item.amount) for b in pool_b]
        self.assertNotEqual(amounts_a, amounts_b)

    def test_type_split_exact_ratio(self):
        pool = generate_pool(1200, seed=SEED)
        n_payment = sum(1 for b in pool if b.item.type == ItemType.PAYMENT_FAILURE)
        n_receivable = sum(1 for b in pool if b.item.type == ItemType.B2B_RECEIVABLE)
        self.assertEqual(n_payment, 720)
        self.assertEqual(n_receivable, 480)

    def test_split_sizes_exact(self):
        pool = generate_pool(1200, seed=SEED)
        train, val, test = split_pool(pool)
        self.assertEqual(len(train), 700)
        self.assertEqual(len(val), 200)
        self.assertEqual(len(test), 300)

    def test_no_item_id_overlap_across_splits(self):
        pool = generate_pool(1200, seed=SEED)
        train, val, test = split_pool(pool)
        train_ids = {b.item.id for b in train}
        val_ids = {b.item.id for b in val}
        test_ids = {b.item.id for b in test}
        self.assertEqual(train_ids & val_ids, set())
        self.assertEqual(train_ids & test_ids, set())
        self.assertEqual(val_ids & test_ids, set())

    def test_leakage_recoverable_item_has_no_hidden_fields(self):
        pool = generate_pool(1200, seed=SEED)
        item = pool[0].item
        forbidden_attrs = ["reliability_archetype", "hidden_archetype", "p_true", "p_true_by_intervention"]
        for attr in forbidden_attrs:
            self.assertFalse(
                hasattr(item, attr),
                f"LEAKAGE: RecoverableItem must not expose '{attr}'",
            )


class TestFreezeAndChecksum(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_freeze_writes_all_four_files(self):
        result = freeze(seed=SEED, data_dir=self.tmpdir)
        for fname in ["train_set.jsonl", "val_set.jsonl", "test_set_frozen.jsonl", "test_set.checksum"]:
            path = os.path.join(self.tmpdir, fname)
            self.assertTrue(os.path.exists(path), f"missing frozen artifact: {fname}")

    def test_freeze_is_reproducible_bytewise(self):
        result_a = freeze(seed=SEED, data_dir=os.path.join(self.tmpdir, "a"))
        result_b = freeze(seed=SEED, data_dir=os.path.join(self.tmpdir, "b"))
        self.assertEqual(result_a["test_checksum"], result_b["test_checksum"])

    def test_verify_checksum_passes_on_untampered_file(self):
        freeze(seed=SEED, data_dir=self.tmpdir)
        self.assertTrue(verify_checksum(data_dir=self.tmpdir))

    def test_verify_checksum_fails_on_tampered_file(self):
        """
        This is the enforcement mechanism the evaluation harness relies on
        (Part H point 5): 'evaluation/run.py refuses to run if the live
        file's checksum doesn't match the checksum on record.'
        """
        freeze(seed=SEED, data_dir=self.tmpdir)
        test_path = os.path.join(self.tmpdir, "test_set_frozen.jsonl")
        with open(test_path, "a") as f:
            f.write('{"tampered": true}\n')
        self.assertFalse(
            verify_checksum(data_dir=self.tmpdir),
            "checksum verification MUST fail after the frozen file is modified",
        )

    def test_verify_checksum_fails_when_files_missing(self):
        self.assertFalse(verify_checksum(data_dir=self.tmpdir))

    def test_ground_truth_file_not_readable_by_observable_dict(self):
        """
        Structural leakage check: the observable test set's JSON keys must
        never include ground-truth fields, even by accident of a shared
        serializer.
        """
        freeze(seed=SEED, data_dir=self.tmpdir)
        test_path = os.path.join(self.tmpdir, "test_set_frozen.jsonl")
        with open(test_path) as f:
            first_row = json.loads(f.readline())
        forbidden_keys = {"hidden_archetype", "p_true_by_intervention", "sampled_outcome_by_intervention"}
        self.assertEqual(set(first_row.keys()) & forbidden_keys, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
