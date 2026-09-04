"""
Recovery probability inference wrapper — RECOVER-ALLOC, Locked spec Part H.

Loads the joblib artifacts produced by train.py and exposes
predict_p_recover(item_features, intervention) -> float in [0,1].

This is the ONLY module the optimizer (Part J/K) is meant to import from
`probability/` at request time — it never sees raw training data or the
rule/LLM diagnoser directly; it takes an already-built feature dict.
"""
import os

import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer

from domain.enums import InterventionType

ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "artifacts")


class ProbabilityModel:
    def __init__(self, model_version: str, artifact_dir: str = ARTIFACT_DIR):
        self.model_version = model_version
        self._artifacts: dict[InterventionType, dict] = {}
        for intervention in InterventionType:
            path = os.path.join(
                artifact_dir, f"model_{intervention.value}_{model_version}.joblib"
            )
            if os.path.exists(path):
                self._artifacts[intervention] = joblib.load(path)

    def available_interventions(self) -> list[InterventionType]:
        return list(self._artifacts.keys())

    def predict_p_recover(self, feature_dict: dict, intervention: InterventionType) -> float:
        if intervention not in self._artifacts:
            raise ValueError(
                f"no trained model for intervention {intervention} "
                f"(available: {self.available_interventions()})"
            )
        artifact = self._artifacts[intervention]
        vectorizer: DictVectorizer = artifact["vectorizer"]
        model = artifact["model"]
        X = vectorizer.transform([feature_dict])
        # predict_proba returns [[P(class=0), P(class=1)]]; class 1 = recovered.
        proba = model.predict_proba(X)[0]
        classes = list(model.classes_)
        p_recover = float(proba[classes.index(1)]) if 1 in classes else 0.0
        # Defensive clamp — CalibratedClassifierCV should already respect
        # [0,1], but the domain model's Field(ge=0.0, le=1.0) will reject
        # any float-precision overshoot (e.g. 1.0000000000000002), so clamp
        # here rather than let a downstream validation error surface from
        # a floating-point artifact instead of a real bug.
        return max(0.0, min(1.0, p_recover))
