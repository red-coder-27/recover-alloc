"""
Ablation pipeline harness - RECOVER-ALLOC, Phase 6.

Wires a diagnoser (rule OR llm) through the shared downstream pipeline:
    diagnosis -> features -> probability model -> allocator -> policy -> simulator

ALLOCATOR CHOICE, stated honestly: uses optimizer.naive_sort_allocate,
NOT optimizer.mcmkp.solve_mcmkp (CP-SAT is unverified in this sandbox -
see docs/OPTIMIZER_VERIFICATION_STATUS.md) and NOT
optimizer.brute_force_optimal (capped at 12 items, too small for a
meaningful ablation batch). naive_sort_allocate is applied IDENTICALLY
to both diagnosis arms, which is what the experimental control actually
requires - isolating the diagnosis variable does not require the
allocator to be CP-SAT specifically, only that it be the SAME for both
arms. This substitution is documented here and in docs/LLM_ABLATION.md,
not silently made.
"""
import time
from dataclasses import dataclass

from domain.enums import InterventionType, ItemType, PolicyOutcome, VALID_INTERVENTIONS_BY_ITEM_TYPE
from domain.models_stdlib_mirror import INTERVENTION_CATALOG
from optimizer.naive_sort import naive_sort_allocate
from optimizer.feasibility import check_allocation_feasibility
from policy.config import DEFAULT_POLICY_CONFIG
from policy.engine import evaluate_policy
from probability.features import build_feature_dict
from probability.model import ProbabilityModel
from execution.simulator_executor import SimulatorExecutor
from execution.idempotency import compute_idempotency_key


@dataclass
class AblationRunResult:
    diagnosis_source: str
    n_items: int
    failure_class_accuracy: float | None  # against a defined ground-truth label, see below
    unclear_rate: float
    mean_confidence: float
    policy_allow_count: int
    policy_block_count: int
    policy_escalate_count: int
    policy_modify_count: int
    policy_violation_count: int  # must be 0 by construction if the pipeline is wired correctly
    expected_net_recovery: float
    actual_simulated_net_recovery: float
    execution_count: int
    escalation_count: int
    wall_clock_seconds: float


def _ground_truth_failure_class(item_row: dict) -> str:
    """
    A defined, deterministic 'reference label' for scoring diagnosis
    accuracy - NOT the hidden reliability_archetype (never used here),
    just the failure_code/days_overdue-implied class every diagnoser
    ideally should reach absent additional evidence. This is what
    "failure-class accuracy" is measured against; a diagnoser that
    reads evidence_text well may legitimately deviate from this label
    when the text reveals something the code/aging alone wouldn't
    (e.g. the fraud_suspect contradiction cases from Part G) - so this
    is a REFERENCE baseline, not an infallible oracle, and the ablation
    report says so explicitly.
    """
    if item_row["type"] == "PAYMENT_FAILURE":
        return item_row.get("failure_code") or "unclear"
    days = item_row.get("days_overdue", 0)
    if days <= 30:
        return "administrative_delay_receivable"
    if days <= 120:
        return "genuine_hardship_receivable"
    return "dispute_risk_receivable"


def run_ablation_arm(
    *,
    items: list[dict],
    diagnoser_fn,
    diagnosis_source_label: str,
    probability_model: ProbabilityModel,
    resources_budget: dict,
    policy_config=DEFAULT_POLICY_CONFIG,
    run_id: str = "ablation_run",
) -> AblationRunResult:
    start = time.monotonic()

    items_by_id = {}
    diagnoses = {}
    correct_failure_class = 0
    n_unclear = 0
    confidences = []
    all_probabilities: dict = {}

    for row in items:
        item_type = ItemType(row["type"])

        class _Item:
            pass
        item = _Item()
        item.id = row["id"]
        item.type = item_type
        item.amount = row["amount"]
        item.risk_flags = row.get("risk_flags", [])
        item.historical_attempts = row.get("historical_attempts", 0)
        item.contact_count_7d = row.get("contact_count_7d", 0)
        item.merchant_id = row.get("merchant_id", "m1")
        items_by_id[row["id"]] = item

        diagnosis = diagnoser_fn(
            evidence_text=row.get("evidence_text", ""),
            item_type=row["type"],
            failure_code=row.get("failure_code"),
            days_overdue=row.get("days_overdue", 0),
            historical_attempts=row.get("historical_attempts", 0),
        )
        diagnoses[row["id"]] = diagnosis
        confidences.append(diagnosis.confidence)
        if diagnosis.failure_class == "unclear":
            n_unclear += 1
        if diagnosis.failure_class == _ground_truth_failure_class(row):
            correct_failure_class += 1

        # Probability estimation for every valid intervention.
        for interv in VALID_INTERVENTIONS_BY_ITEM_TYPE[item_type]:
            fdict = build_feature_dict(
                days_overdue=row.get("days_overdue", 0),
                historical_attempts=row.get("historical_attempts", 0),
                contact_count_7d=row.get("contact_count_7d", 0),
                amount=float(row["amount"]),
                failure_code=row.get("failure_code"),
                item_type=row["type"],
                merchant_recovery_policy_tier=row.get("merchant_recovery_policy_tier", "standard"),
                diagnosis_failure_class=diagnosis.failure_class,
                diagnosis_confidence=diagnosis.confidence,
                risk_flags=row.get("risk_flags", []),
            )
            p = probability_model.predict_p_recover(fdict, interv)
            all_probabilities[(row["id"], interv)] = p

    allocation_result = naive_sort_allocate(
        items_by_id=items_by_id, probabilities=all_probabilities,
        resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
    )

    policy_counts = {PolicyOutcome.ALLOW: 0, PolicyOutcome.BLOCK: 0, PolicyOutcome.ESCALATE: 0, PolicyOutcome.MODIFY: 0}
    expected_net_recovery = 0.0
    actual_simulated_net_recovery = 0.0
    execution_count = 0
    escalation_count = 0
    simulator = SimulatorExecutor(forced_behavior="success")  # deterministic, for a controlled ablation comparison

    for item_id, intervention in allocation_result.assignments.items():
        if intervention is None:
            continue
        item = items_by_id[item_id]
        diagnosis = diagnoses[item_id]
        decision = evaluate_policy(
            item=item, intervention=intervention, diagnosis=diagnosis,
            interventions_catalog=INTERVENTION_CATALOG, config=policy_config,
        )
        policy_counts[decision.outcome] = policy_counts.get(decision.outcome, 0) + 1

        if decision.outcome == PolicyOutcome.ESCALATE:
            escalation_count += 1
            continue
        if decision.outcome != PolicyOutcome.ALLOW:
            continue  # BLOCKed - never reaches execution

        final_intervention = decision.final_intervention or intervention
        p = all_probabilities.get((item_id, final_intervention), 0.0)
        cost = float(INTERVENTION_CATALOG[final_intervention].cost_inr)
        expected_net_recovery += float(item.amount) * p - cost

        idempotency_key = compute_idempotency_key(run_id, item_id, final_intervention.value)
        outcome = simulator.execute(item=item, intervention=final_intervention, idempotency_key=idempotency_key)
        execution_count += 1
        if outcome.confirmed and outcome.succeeded:
            actual_simulated_net_recovery += float(item.amount) - cost

    # Policy-violation check: an ALLOW-outcome allocation must never be
    # for a fraud-flagged item or below the monetary floor - verify
    # directly against the independent feasibility checker as an extra
    # cross-check (belt-and-suspenders, since evaluate_policy already
    # enforces this).
    violations = 0
    for item_id, intervention in allocation_result.assignments.items():
        if intervention is None:
            continue
        v = check_allocation_feasibility(
            assignments={item_id: intervention}, items_by_id={item_id: items_by_id[item_id]},
            resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
        )
        violations += len(v)

    elapsed = time.monotonic() - start
    n = len(items)
    return AblationRunResult(
        diagnosis_source=diagnosis_source_label,
        n_items=n,
        failure_class_accuracy=correct_failure_class / n if n else None,
        unclear_rate=n_unclear / n if n else 0.0,
        mean_confidence=sum(confidences) / len(confidences) if confidences else 0.0,
        policy_allow_count=policy_counts[PolicyOutcome.ALLOW],
        policy_block_count=policy_counts[PolicyOutcome.BLOCK],
        policy_escalate_count=policy_counts[PolicyOutcome.ESCALATE],
        policy_modify_count=policy_counts[PolicyOutcome.MODIFY],
        policy_violation_count=violations,
        expected_net_recovery=expected_net_recovery,
        actual_simulated_net_recovery=actual_simulated_net_recovery,
        execution_count=execution_count,
        escalation_count=escalation_count,
        wall_clock_seconds=elapsed,
    )
