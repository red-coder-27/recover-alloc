"""
Freeze test set — RECOVER-ALLOC, Locked spec Part H freeze procedure.

Run ONCE. Writes:
    data/test_set_frozen.jsonl          (observable fields only — what the
                                          app/model/LLM are allowed to see)
    data/test_set.checksum              (sha256 of the frozen file)
    data/test_set_ground_truth.jsonl    (hidden p_true + sampled outcome —
                                          readable ONLY by oracle.py and the
                                          evaluation scorer, per Part H)

Also writes data/train_set.jsonl and data/val_set.jsonl (no checksum freeze
needed for these — only the test set is frozen/immutable).

Usage:
    python -m simulation.freeze_test_set
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulation.generator import generate_pool, split_pool, SEED

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _item_to_observable_dict(bundle) -> dict:
    item = bundle.item
    return {
        "id": item.id,
        "type": item.type.value,
        "merchant_id": item.merchant_id,
        "customer_id": item.customer_id,
        "amount": str(item.amount),
        "currency": item.currency,
        "created_at": item.created_at.isoformat(),
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "days_overdue": item.days_overdue,
        "payment_method": item.payment_method,
        "failure_code": item.failure_code,
        "historical_attempts": item.historical_attempts,
        "contact_count_7d": item.contact_count_7d,
        "evidence_text": item.evidence_text,
        "risk_flags": item.risk_flags,
        "status": item.status.value,
        "merchant_recovery_policy_tier": item.merchant_recovery_policy_tier,
        # NOTE: hidden_archetype, p_true_by_intervention, and
        # sampled_outcome_by_intervention are DELIBERATELY excluded here.
    }


def _bundle_to_ground_truth_dict(bundle) -> dict:
    return {
        "item_id": bundle.item.id,
        "hidden_archetype": bundle.hidden_archetype.value,
        "p_true_by_intervention": bundle.p_true_by_intervention,
        "sampled_outcome_by_intervention": bundle.sampled_outcome_by_intervention,
        "true_diagnostic_class": bundle.true_diagnostic_class,
    }


def _bundle_to_training_label_dict(bundle) -> dict:
    """
    ADDITION (Phase 2 necessity, not in the original Part H text verbatim):
    the probability model needs *some* labels to train on. Part H only
    specifies withholding ground truth for the FROZEN TEST split; it does
    not separately address train/val labeling, so this is a deliberate,
    documented modeling decision made here rather than left implicit:

    For train/val ONLY, we expose the realized (sampled) 0/1 outcome per
    valid intervention — this is the synthetic stand-in for "what actually
    happened historically when this intervention was tried," which a real
    system would have in its logs. We do NOT expose `p_true` (the latent
    probability itself) for train/val either — only the test split's
    p_true is used anywhere, and only inside oracle.py / the evaluation
    scorer, never inside model training. This keeps a single, consistent
    leakage rule across all three splits: the model only ever sees
    observable features and realized binary outcomes, never a probability
    that was used to generate those outcomes.
    """
    return {
        "item_id": bundle.item.id,
        "outcome_by_intervention": {
            k: int(v) for k, v in bundle.sampled_outcome_by_intervention.items()
        },
    }


def _write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def freeze(seed: int = SEED, data_dir: str = DATA_DIR) -> dict:
    os.makedirs(data_dir, exist_ok=True)

    bundles = generate_pool(1200, seed=seed)
    train, val, test = split_pool(bundles)

    train_path = os.path.join(data_dir, "train_set.jsonl")
    val_path = os.path.join(data_dir, "val_set.jsonl")
    test_path = os.path.join(data_dir, "test_set_frozen.jsonl")
    checksum_path = os.path.join(data_dir, "test_set.checksum")
    gt_path = os.path.join(data_dir, "test_set_ground_truth.jsonl")
    train_labels_path = os.path.join(data_dir, "train_labels.jsonl")
    val_labels_path = os.path.join(data_dir, "val_labels.jsonl")

    _write_jsonl(train_path, [_item_to_observable_dict(b) for b in train])
    _write_jsonl(val_path, [_item_to_observable_dict(b) for b in val])
    _write_jsonl(test_path, [_item_to_observable_dict(b) for b in test])
    _write_jsonl(gt_path, [_bundle_to_ground_truth_dict(b) for b in test])
    _write_jsonl(train_labels_path, [_bundle_to_training_label_dict(b) for b in train])
    _write_jsonl(val_labels_path, [_bundle_to_training_label_dict(b) for b in val])

    checksum = _sha256_of_file(test_path)
    with open(checksum_path, "w") as f:
        f.write(checksum + "\n")

    return {
        "train_count": len(train),
        "val_count": len(val),
        "test_count": len(test),
        "test_checksum": checksum,
        "seed": seed,
    }


def verify_checksum(data_dir: str = DATA_DIR) -> bool:
    """
    The enforcement mechanism referenced throughout the spec: evaluation
    MUST refuse to run if this returns False.
    """
    test_path = os.path.join(data_dir, "test_set_frozen.jsonl")
    checksum_path = os.path.join(data_dir, "test_set.checksum")
    if not (os.path.exists(test_path) and os.path.exists(checksum_path)):
        return False
    with open(checksum_path) as f:
        recorded = f.read().strip()
    live = _sha256_of_file(test_path)
    return recorded == live


if __name__ == "__main__":
    result = freeze()
    print(f"Frozen test set written. seed={result['seed']}")
    print(f"  train: {result['train_count']} items -> data/train_set.jsonl")
    print(f"  val:   {result['val_count']} items -> data/val_set.jsonl")
    print(f"  test:  {result['test_count']} items -> data/test_set_frozen.jsonl")
    print(f"  checksum (sha256): {result['test_checksum']}")
    print(f"  ground truth (hidden): data/test_set_ground_truth.jsonl")
