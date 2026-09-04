"""
Probability model training — RECOVER-ALLOC, Locked spec Part H.

Trains ONE HistGradientBoostingClassifier + CalibratedClassifierCV
(isotonic, cv=5) PER intervention type, per the locked spec's explicit
choice to keep intervention-conditioning explicit rather than folding it
into a single model as a categorical feature.

Uses the rule-table diagnosis path (diagnosis/rule_diagnoser.py) to
generate the `diagnosis_failure_class`/`diagnosis_confidence` features for
train/val — NOT the LLM path, since there is no Anthropic API access in
this build environment and, more importantly, the model must be trainable
independent of LLM availability (Part I: "Local rule-table path is always
fully functional independent of LLM availability" — same principle
applies to training, not just runtime).

Run: python -m probability.train
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction import DictVectorizer

from diagnosis.rule_diagnoser import diagnose as rule_diagnose
from domain.enums import InterventionType, ItemType, VALID_INTERVENTIONS_BY_ITEM_TYPE
from probability.features import build_feature_dict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "artifacts")
MODEL_VERSION = "v1.0.0"


def _load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def _build_training_rows(items: list[dict], labels: list[dict], intervention: InterventionType):
    """
    Returns (feature_dicts, y) for items where `intervention` is valid
    for that item's type AND a realized outcome label exists for it.
    """
    labels_by_id = {row["item_id"]: row["outcome_by_intervention"] for row in labels}
    feature_dicts = []
    y = []
    for item_row in items:
        item_type = ItemType(item_row["type"])
        valid = VALID_INTERVENTIONS_BY_ITEM_TYPE[item_type]
        if intervention not in valid:
            continue
        outcome_map = labels_by_id.get(item_row["id"])
        if outcome_map is None or intervention.value not in outcome_map:
            continue

        diagnosis = rule_diagnose(
            failure_code=item_row.get("failure_code"),
            days_overdue=item_row.get("days_overdue", 0),
            item_type=item_row["type"],
            evidence_text=item_row.get("evidence_text", ""),
        )
        fdict = build_feature_dict(
            days_overdue=item_row.get("days_overdue", 0),
            historical_attempts=item_row.get("historical_attempts", 0),
            contact_count_7d=item_row.get("contact_count_7d", 0),
            amount=float(item_row["amount"]),
            failure_code=item_row.get("failure_code"),
            item_type=item_row["type"],
            merchant_recovery_policy_tier=item_row.get("merchant_recovery_policy_tier", "standard"),
            diagnosis_failure_class=diagnosis.failure_class,
            diagnosis_confidence=diagnosis.confidence,
            risk_flags=item_row.get("risk_flags", []),
        )
        feature_dicts.append(fdict)
        y.append(outcome_map[intervention.value])
    return feature_dicts, np.array(y, dtype=int)


def train_one_intervention(intervention: InterventionType, train_items, train_labels):
    feature_dicts, y = _build_training_rows(train_items, train_labels, intervention)
    if len(feature_dicts) == 0:
        raise RuntimeError(f"no training rows found for {intervention}")
    if len(set(y.tolist())) < 2:
        raise RuntimeError(
            f"training labels for {intervention} are single-class "
            f"({set(y.tolist())}) — cannot fit a classifier. This usually "
            f"means the synthetic ground truth for this intervention is "
            f"too extreme; adjust simulation/ground_truth.py betas."
        )

    vectorizer = DictVectorizer(sparse=False)
    X = vectorizer.fit_transform(feature_dicts)

    base_model = HistGradientBoostingClassifier(random_state=42)
    # cv=5 per spec; guard against tiny per-intervention training sets
    # (e.g. HUMAN_ESCALATION rows are a minority of the batch) where 5-fold
    # CV could starve a fold of positive examples — fall back to a smaller
    # cv count in that case and RECORD that this happened, rather than
    # crashing or silently using an under-specified default.
    n_pos = int(y.sum())
    n_neg = int(len(y) - n_pos)
    min_class_count = min(n_pos, n_neg)
    cv_folds = min(5, min_class_count) if min_class_count >= 2 else 2
    calibrated = CalibratedClassifierCV(base_model, method="isotonic", cv=cv_folds)
    calibrated.fit(X, y)

    return {
        "vectorizer": vectorizer,
        "model": calibrated,
        "n_train_rows": len(y),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "cv_folds_used": cv_folds,
    }


def train_all(data_dir: str = DATA_DIR, artifact_dir: str = ARTIFACT_DIR) -> dict:
    train_items = _load_jsonl(os.path.join(data_dir, "train_set.jsonl"))
    train_labels = _load_jsonl(os.path.join(data_dir, "train_labels.jsonl"))

    os.makedirs(artifact_dir, exist_ok=True)
    summary = {"model_version": MODEL_VERSION, "interventions": {}}

    for intervention in InterventionType:
        result = train_one_intervention(intervention, train_items, train_labels)
        artifact_path = os.path.join(
            artifact_dir, f"model_{intervention.value}_{MODEL_VERSION}.joblib"
        )
        joblib.dump(
            {"vectorizer": result["vectorizer"], "model": result["model"]}, artifact_path
        )
        summary["interventions"][intervention.value] = {
            "n_train_rows": result["n_train_rows"],
            "n_positive": result["n_positive"],
            "n_negative": result["n_negative"],
            "cv_folds_used": result["cv_folds_used"],
            "artifact_path": artifact_path,
        }

    summary_path = os.path.join(artifact_dir, f"train_summary_{MODEL_VERSION}.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    return summary


if __name__ == "__main__":
    summary = train_all()
    print(f"Trained model version {summary['model_version']}")
    for interv, info in summary["interventions"].items():
        print(
            f"  {interv}: {info['n_train_rows']} rows "
            f"({info['n_positive']} positive / {info['n_negative']} negative), "
            f"cv_folds={info['cv_folds_used']} -> {info['artifact_path']}"
        )
