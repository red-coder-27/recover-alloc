"""
Calibration utilities — RECOVER-ALLOC, Locked spec Part H.

Computes Brier score, log loss, ROC-AUC, and a calibration curve
(predicted-probability-bucket vs. observed frequency), and can render the
calibration curve as a PNG for the evaluation report (Part P).
"""
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


def compute_calibration_metrics(y_true, y_prob) -> dict:
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)

    metrics = {
        "brier_score": float(brier_score_loss(y_true, y_prob)),
        "n_samples": int(len(y_true)),
        "positive_rate": float(y_true.mean()),
    }

    # log_loss and roc_auc_score both require both classes present.
    if len(set(y_true.tolist())) < 2:
        metrics["log_loss"] = None
        metrics["roc_auc"] = None
        metrics["note"] = "single-class y_true — log_loss/roc_auc undefined"
    else:
        metrics["log_loss"] = float(log_loss(y_true, y_prob))
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))

    prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=10, strategy="quantile")
    metrics["calibration_curve"] = {
        "predicted_bucket_mean": prob_pred.tolist(),
        "observed_frequency": prob_true.tolist(),
    }
    return metrics


def render_calibration_chart(metrics: dict, title: str, output_path: str) -> str:
    """
    Renders a reliability diagram (predicted vs. observed) to a PNG.
    Uses matplotlib's non-interactive Agg backend so this works headless
    in evaluation/report.py without a display.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pred = metrics["calibration_curve"]["predicted_bucket_mean"]
    obs = metrics["calibration_curve"]["observed_frequency"]

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="perfect calibration")
    ax.plot(pred, obs, marker="o", label="model")
    ax.set_xlabel("predicted probability (bucket mean)")
    ax.set_ylabel("observed frequency")
    ax.set_title(title)
    ax.legend()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path
