"""
Chart generation - RECOVER-ALLOC, Phase 7. All charts render directly
from evaluation JSON - never manually edited images.
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def generate_charts(report, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    paths = []

    names, means, stds, statuses = [], [], [], []
    for name, d in report["strategies"].items():
        names.append(name)
        if d["status"] == "OK":
            means.append(d["realized_net_recovered"]["mean"])
            stds.append(d["realized_net_recovered"]["stddev"])
            statuses.append("OK")
        else:
            means.append(0)
            stds.append(0)
            statuses.append("UNAVAILABLE")

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#4C72B0" if s == "OK" else "#CCCCCC" for s in statuses]
    ax.bar(names, means, yerr=stds, color=colors, capsize=4)
    for i, s in enumerate(statuses):
        if s == "UNAVAILABLE":
            ax.text(i, 0, "UNAVAILABLE", ha="center", va="bottom", rotation=90, fontsize=8, color="red")
    ax.set_ylabel("Realized net recovered (mean +/- stddev, INR)")
    ax.set_title("Net Recovery by Strategy")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    p = os.path.join(output_dir, "net_recovery_by_strategy.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(4, 5))
    if isinstance(report["oracle_capture_percent"], (int, float)):
        ax.bar(["Oracle Capture %"], [report["oracle_capture_percent"]], color="#55A868")
        ax.set_ylim(0, 100)
    else:
        ax.text(0.5, 0.5, "UNAVAILABLE\n(recover_alloc/oracle\ndid not run)",
                 ha="center", va="center", fontsize=10, color="red")
        ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Oracle Capture %")
    fig.tight_layout()
    p = os.path.join(output_dir, "oracle_capture_percent.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)

    resources = ["retry_slots", "whatsapp_quota", "human_hours"]
    fig, ax = plt.subplots(figsize=(9, 5))
    width = 0.25
    x = range(len(names))
    for i, r in enumerate(resources):
        vals = [
            report["strategies"][n].get("realized_resource_usage_seed0", {}).get(r, 0)
            if report["strategies"][n]["status"] == "OK" else 0
            for n in names
        ]
        ax.bar([xi + i * width for xi in x], vals, width=width, label=r)
    ax.set_xticks([xi + width for xi in x])
    ax.set_xticklabels(names, rotation=30, ha="right")
    ax.set_title("Resource Utilization by Strategy (seed 0)")
    ax.legend()
    fig.tight_layout()
    p = os.path.join(output_dir, "resource_utilization.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(9, 4))
    violation_counts = [
        len(report["strategies"][n]["feasibility_violations"]) if report["strategies"][n]["status"] == "OK" else 0
        for n in names
    ]
    ax.bar(names, violation_counts, color="#C44E52")
    ax.set_title("Feasibility/Policy Violations by Strategy (must be 0)")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    p = os.path.join(output_dir, "policy_violations.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)

    n_total = report["config"]["n_items"]
    served = [
        report["strategies"][n]["n_items_served"] / n_total if report["strategies"][n]["status"] == "OK" else 0
        for n in names
    ]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(names, served, color="#8172B2")
    ax.set_ylabel("Fraction of batch served")
    ax.set_title("Recovery Rate (Items Served) by Strategy")
    ax.set_ylim(0, 1)
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    p = os.path.join(output_dir, "recovery_rate.png")
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)

    calib_dir = os.path.join(os.path.dirname(__file__), "..", "probability", "artifacts", "charts")
    if os.path.isdir(calib_dir):
        for fname in os.listdir(calib_dir):
            paths.append(os.path.join(calib_dir, fname))

    return paths


if __name__ == "__main__":
    import glob
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    latest = sorted(glob.glob(os.path.join(results_dir, "*.json")))[-1]
    with open(latest) as f:
        report = json.load(f)
    charts_dir = os.path.join(results_dir, "charts")
    paths = generate_charts(report, charts_dir)
    print(f"Generated {len(paths)} charts in {charts_dir}")
    for p in paths:
        print(f"  {p}")
