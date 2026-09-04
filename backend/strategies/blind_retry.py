"""
Blind Retry - RECOVER-ALLOC, Phase 7 / locked spec Part Q.
Assigns PAYMENT_RETRY to every PAYMENT_FAILURE item (arrival order, no
diagnosis, no probability model) until retry_slots exhausted;
B2B_RECEIVABLE items get WHATSAPP_REMINDER until whatsapp_quota
exhausted. This mirrors how naive dunning tools actually behave.
"""
import time
from decimal import Decimal

from domain.enums import InterventionType, ItemType, SolverStatus
from strategies.base import StrategyAllocationResult


def allocate(items_by_id, resources_budget, probabilities=None, interventions_catalog=None, **kwargs):
    start = time.monotonic()
    resource_usage = {r: 0 for r in resources_budget}
    assignments = {item_id: None for item_id in items_by_id}

    for item_id, item in items_by_id.items():
        if item.type == ItemType.PAYMENT_FAILURE:
            intervention = InterventionType.PAYMENT_RETRY
        elif item.type == ItemType.B2B_RECEIVABLE:
            intervention = InterventionType.WHATSAPP_REMINDER
        else:
            continue

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
        strategy_name="blind_retry",
        assignments=assignments,
        expected_objective=expected_objective,
        solver_status=SolverStatus.OPTIMAL.value,
        solve_time_ms=elapsed_ms,
    )
