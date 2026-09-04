"""
Evaluation harness - RECOVER-ALLOC, Phase 7.
Run: python -m evaluation.run [--n-items N] [--seeds N]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.enums import ItemType, VALID_INTERVENTIONS_BY_ITEM_TYPE
from domain.models_stdlib_mirror import INTERVENTION_CATALOG
from diagnosis.rule_diagnoser import diagnose as rule_diagnose
from evaluation.scorer import HiddenGroundTruthScorer, verify_and_load_frozen_test_set
from optimizer.feasibility import check_allocation_feasibility
from probability.features import build_feature_dict
from probability.model import ProbabilityModel
from probability.train import MODEL_VERSION
import strategies.no_action as no_action_strategy
import strategies.random_under_budget as random_strategy
import strategies.blind_retry as blind_retry_strategy
import strategies.static_rules as static_rules_strategy
import strategies.llm_only as llm_only_strategy
import strategies.recover_alloc as recover_alloc_strategy
import strategies.oracle as oracle_strategy

DEMO_RESOURCE_BUDGET = {"retry_slots": 35, "whatsapp_quota": 50, "human_hours": 8}
DEFAULT_N_ITEMS = 100
DEFAULT_N_SEEDS = 20
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


class _Item:
    pass


def _build_items_and_probabilities(rows, model):
    items_by_id = {}
    diagnoses = {}
    predicted_probabilities = {}
    for row in rows:
        item_type = ItemType(row["type"])
        item = _Item()
        item.id = row["id"]
        item.type = item_type
        item.amount = row["amount"]
        item.risk_flags = row.get("risk_flags", [])
        item.historical_attempts = row.get("historical_attempts", 0)
        item.contact_count_7d = row.get("contact_count_7d", 0)
        item.merchant_id = row.get("merchant_id", "m1")
        item.failure_code = row.get("failure_code")
        item.days_overdue = row.get("days_overdue", 0)
        item.evidence_text = row.get("evidence_text", "")
        items_by_id[row["id"]] = item

        diagnosis = rule_diagnose(
            failure_code=row.get("failure_code"), days_overdue=row.get("days_overdue", 0),
            item_type=row["type"],
        )
        diagnoses[row["id"]] = diagnosis.failure_class

        for interv in VALID_INTERVENTIONS_BY_ITEM_TYPE[item_type]:
            fdict = build_feature_dict(
                days_overdue=row.get("days_overdue", 0), historical_attempts=row.get("historical_attempts", 0),
                contact_count_7d=row.get("contact_count_7d", 0), amount=float(row["amount"]),
                failure_code=row.get("failure_code"), item_type=row["type"],
                merchant_recovery_policy_tier=row.get("merchant_recovery_policy_tier", "standard"),
                diagnosis_failure_class=diagnosis.failure_class, diagnosis_confidence=diagnosis.confidence,
                risk_flags=row.get("risk_flags", []),
            )
            predicted_probabilities[(row["id"], interv)] = model.predict_p_recover(fdict, interv)

    return items_by_id, diagnoses, predicted_probabilities


def _score_realized_recovery(assignments, items_by_id, scorer, eval_seed):
    gross = 0.0
    cost = 0.0
    n_interventions = 0
    resource_usage = {"retry_slots": 0, "whatsapp_quota": 0, "human_hours": 0}
    for item_id, intervention in assignments.items():
        if intervention is None:
            continue
        item = items_by_id[item_id]
        n_interventions += 1
        c = float(INTERVENTION_CATALOG[intervention].cost_inr)
        cost += c
        for resource, amount in INTERVENTION_CATALOG[intervention].resources_consumed.items():
            resource_usage[resource] = resource_usage.get(resource, 0) + amount
        realized = scorer.sample_realized_outcome(item_id, intervention.value, eval_seed)
        if realized:
            gross += float(item.amount)
    return {
        "gross_recovered": gross, "intervention_cost": cost, "net_recovered": gross - cost,
        "n_interventions": n_interventions, "resource_usage": resource_usage,
    }


def run_strategy(name, allocate_fn, *, items_by_id, resources_budget, predicted_probabilities,
                  true_probabilities, interventions_catalog):
    if name == "oracle":
        return allocate_fn(items_by_id=items_by_id, resources_budget=resources_budget,
                            true_probabilities=true_probabilities, interventions_catalog=interventions_catalog)
    return allocate_fn(items_by_id=items_by_id, resources_budget=resources_budget,
                        probabilities=predicted_probabilities, interventions_catalog=interventions_catalog)


def run_evaluation(n_items=DEFAULT_N_ITEMS, n_seeds=DEFAULT_N_SEEDS, resources_budget=None, run_id=None):
    resources_budget = resources_budget or DEMO_RESOURCE_BUDGET
    run_id = run_id or f"eval_{int(time.time())}"

    rows = verify_and_load_frozen_test_set(n_items=n_items)
    scorer = HiddenGroundTruthScorer()
    model = ProbabilityModel(MODEL_VERSION)
    items_by_id, rule_diagnoses, predicted_probabilities = _build_items_and_probabilities(rows, model)

    true_probabilities = {}
    for item_id, item in items_by_id.items():
        for interv in VALID_INTERVENTIONS_BY_ITEM_TYPE[item.type]:
            p = scorer.p_true(item_id, interv.value)
            if p is not None:
                true_probabilities[(item_id, interv)] = p

    strategy_registry = [
        ("no_action", no_action_strategy.allocate),
        ("random_under_budget", random_strategy.allocate),
        ("blind_retry", blind_retry_strategy.allocate),
        ("static_rules", static_rules_strategy.allocate),
        ("llm_only", llm_only_strategy.allocate),
        ("recover_alloc", recover_alloc_strategy.allocate),
        ("oracle", oracle_strategy.allocate),
    ]

    report = {
        "run_id": run_id,
        "config": {
            "n_items": len(rows), "n_seeds": n_seeds, "resources_budget": resources_budget,
            "model_version": MODEL_VERSION, "policy_version": "v1.0.0",
            "timestamp": time.time(),
        },
        "strategies": {},
    }

    diagnosis_accuracy_rule = scorer.diagnosis_accuracy(rule_diagnoses)
    report["diagnosis_accuracy"] = {
        "rule_table": diagnosis_accuracy_rule,
        "llm": "LLM EXECUTION UNAVAILABLE - anthropic SDK/API key not configured in this environment",
        "reference_label_note": (
            "Scored against an INDEPENDENT hidden true_diagnostic_class "
            "(simulation/ground_truth.py), not derived from the rule "
            "diagnoser's own bucketing logic - fixes the tautological "
            "reference-label issue identified after Phase 6."
        ),
    }

    for name, fn in strategy_registry:
        alloc_result = run_strategy(
            name, fn, items_by_id=items_by_id, resources_budget=resources_budget,
            predicted_probabilities=predicted_probabilities, true_probabilities=true_probabilities,
            interventions_catalog=INTERVENTION_CATALOG,
        )

        if alloc_result.unavailable:
            report["strategies"][name] = {
                "status": "UNAVAILABLE",
                "reason": alloc_result.unavailable_reason,
                "dependency": alloc_result.unavailable_dependency,
                "command": alloc_result.unavailable_command,
            }
            continue

        violations = check_allocation_feasibility(
            assignments=alloc_result.assignments, items_by_id=items_by_id,
            resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
        )

        realized_runs = []
        for seed in range(n_seeds):
            realized_runs.append(_score_realized_recovery(alloc_result.assignments, items_by_id, scorer, seed))

        net_values = [r["net_recovered"] for r in realized_runs]
        mean_net = sum(net_values) / len(net_values)
        variance = sum((v - mean_net) ** 2 for v in net_values) / len(net_values)
        stddev_net = variance ** 0.5
        sorted_vals = sorted(net_values)
        median_net = sorted_vals[len(sorted_vals) // 2]

        report["strategies"][name] = {
            "status": "OK",
            "expected_objective": float(alloc_result.expected_objective),
            "solver_status": alloc_result.solver_status,
            "solve_time_ms": alloc_result.solve_time_ms,
            "n_items_served": sum(1 for v in alloc_result.assignments.values() if v is not None),
            "n_items_unserved": sum(1 for v in alloc_result.assignments.values() if v is None),
            "feasibility_violations": [f"{v.kind}: {v.detail}" for v in violations],
            "realized_net_recovered": {"mean": mean_net, "median": median_net, "stddev": stddev_net, "n_seeds": n_seeds},
            "realized_resource_usage_seed0": realized_runs[0]["resource_usage"],
        }

    ra = report["strategies"].get("recover_alloc", {})
    orc = report["strategies"].get("oracle", {})
    if ra.get("status") == "OK" and orc.get("status") == "OK" and orc["expected_objective"] != 0:
        report["oracle_capture_percent"] = round(100 * ra["expected_objective"] / orc["expected_objective"], 2)
    else:
        report["oracle_capture_percent"] = "UNAVAILABLE - recover_alloc and/or oracle did not run (see strategies section)"

    return report


def write_report(report, results_dir=RESULTS_DIR):
    os.makedirs(results_dir, exist_ok=True)
    json_path = os.path.join(results_dir, f"{report['run_id']}.json")
    md_path = os.path.join(results_dir, f"{report['run_id']}.md")

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    lines = [f"# Evaluation Report - {report['run_id']}", ""]
    lines.append("## Configuration")
    for k, v in report["config"].items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Diagnosis Accuracy")
    for k, v in report["diagnosis_accuracy"].items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Strategies")
    for name, data in report["strategies"].items():
        lines.append(f"### {name}")
        if data["status"] == "UNAVAILABLE":
            lines.append("**STATUS: UNAVAILABLE**")
            lines.append(f"- reason: {data['reason']}")
            lines.append(f"- dependency: {data['dependency']}")
            lines.append(f"- command: `{data['command']}`")
        else:
            lines.append(f"- expected_objective: {data['expected_objective']:.2f}")
            lines.append(f"- solver_status: {data['solver_status']}")
            lines.append(f"- items served: {data['n_items_served']} / unserved: {data['n_items_unserved']}")
            lines.append(f"- feasibility_violations: {len(data['feasibility_violations'])} {data['feasibility_violations']}")
            r = data["realized_net_recovered"]
            lines.append(f"- realized net recovered over {r['n_seeds']} seeds: mean={r['mean']:.2f}, median={r['median']:.2f}, stddev={r['stddev']:.2f}")
        lines.append("")
    lines.append(f"## Oracle Capture %: {report['oracle_capture_percent']}")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    return json_path, md_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-items", type=int, default=DEFAULT_N_ITEMS)
    parser.add_argument("--seeds", type=int, default=DEFAULT_N_SEEDS)
    args = parser.parse_args()

    report = run_evaluation(n_items=args.n_items, n_seeds=args.seeds)
    json_path, md_path = write_report(report)
    print(f"Evaluation complete. Wrote {json_path} and {md_path}")
    print(json.dumps({k: v for k, v in report["strategies"].items()}, indent=2, default=str))
