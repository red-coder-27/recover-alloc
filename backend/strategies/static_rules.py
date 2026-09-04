"""
Static Rules - RECOVER-ALLOC, Phase 7 / locked spec Part Q.
Uses rule_diagnoser output + a fixed lookup priority order by
failure_class severity (not intentionally stupid - a real ops team would
plausibly prioritize this way: fresh, high-recoverability codes first).
No probability model, no optimizer.
"""
import time
from decimal import Decimal

from diagnosis.rule_diagnoser import diagnose as rule_diagnose
from domain.enums import InterventionType, ItemType, SolverStatus
from strategies.base import StrategyAllocationResult

# Priority order, most-worth-serving-first, by failure_class - a
# deliberately reasonable ranking, not an arbitrary one: codes with
# historically higher recoverability (per the strategy report's cited
# industry figures) are prioritized first when resources are scarce.
FAILURE_CLASS_PRIORITY = [
    "bank_server_error", "insufficient_funds", "issuer_soft_decline",
    "administrative_delay_receivable", "genuine_hardship_receivable",
    "risk_threshold_hold", "expired_card", "dispute_risk_receivable",
    "do_not_honor", "unclear",
]


def allocate(items_by_id, resources_budget, probabilities=None, interventions_catalog=None, **kwargs):
    start = time.monotonic()
    diagnoses = {}
    candidates = []
    for item_id, item in items_by_id.items():
        diagnosis = rule_diagnose(
            failure_code=getattr(item, "failure_code", None),
            days_overdue=getattr(item, "days_overdue", 0),
            item_type=item.type.value,
        )
        diagnoses[item_id] = diagnosis.failure_class
        if diagnosis.recommended_interventions:
            candidates.append((item_id, diagnosis.recommended_interventions[0], diagnosis.failure_class))

    priority_index = {cls: i for i, cls in enumerate(FAILURE_CLASS_PRIORITY)}
    candidates.sort(key=lambda c: (priority_index.get(c[2], len(FAILURE_CLASS_PRIORITY)), c[0]))

    resource_usage = {r: 0 for r in resources_budget}
    assignments = {item_id: None for item_id in items_by_id}

    for item_id, intervention, _ in candidates:
        item = items_by_id[item_id]
        catalog_entry = interventions_catalog[intervention]
        if item.historical_attempts >= catalog_entry.max_frequency_per_item:
            continue
        if intervention in (InterventionType.WHATSAPP_REMINDER, InterventionType.HUMAN_ESCALATION):
            if item.contact_count_7d >= 3:
                continue
        would_exceed = False
        for resource, amount_needed in catalog_entry.resources_consumed.items():
            if resource_usage.get(resource, 0) + amount_needed > resources_budget.get(resource, 0):
                would_exceed = True
                break
        if would_exceed:
            continue
        assignments[item_id] = intervention
        for resource, amount_needed in catalog_entry.resources_consumed.items():
            resource_usage[resource] = resource_usage.get(resource, 0) + amount_needed

    expected_objective = Decimal("0")
    for item_id, intervention in assignments.items():
        if intervention is None:
            continue
        item = items_by_id[item_id]
        p = probabilities.get((item_id, intervention), 0.0) if probabilities else 0.0
        cost = interventions_catalog[intervention].cost_inr
        expected_objective += Decimal(str(item.amount)) * Decimal(str(p)) - cost

    elapsed_ms = (time.monotonic() - start) * 1000
    return StrategyAllocationResult(
        strategy_name="static_rules",
        assignments=assignments,
        expected_objective=expected_objective,
        solver_status=SolverStatus.OPTIMAL.value,
        solve_time_ms=elapsed_ms,
        diagnoses=diagnoses,
    )
