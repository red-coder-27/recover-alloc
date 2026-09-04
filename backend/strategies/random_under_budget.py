"""
Random Under Budget - RECOVER-ALLOC, Phase 7 / locked spec Part Q.
Fixed seed for reproducibility; shuffles valid (item, intervention)
candidates and greedily assigns while resource budgets and per-item
constraints allow.
"""
import time
import uuid
from decimal import Decimal
import random as _random

from domain.enums import InterventionType, SolverStatus, VALID_INTERVENTIONS_BY_ITEM_TYPE
from strategies.base import StrategyAllocationResult

FIXED_SEED = 424242


def allocate(items_by_id, resources_budget, probabilities=None, interventions_catalog=None, seed=FIXED_SEED, **kwargs) -> StrategyAllocationResult:
    start = time.monotonic()
    rng = _random.Random(seed)

    candidates = []
    for item_id, item in items_by_id.items():
        for intervention in VALID_INTERVENTIONS_BY_ITEM_TYPE.get(item.type, ()):
            candidates.append((item_id, intervention))
    rng.shuffle(candidates)

    resource_usage = {r: 0 for r in resources_budget}
    assignments = {item_id: None for item_id in items_by_id}
    assigned = set()

    for item_id, intervention in candidates:
        if item_id in assigned:
            continue
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
        assigned.add(item_id)
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
        strategy_name="random_under_budget",
        assignments=assignments,
        expected_objective=expected_objective,
        solver_status=SolverStatus.OPTIMAL.value,
        solve_time_ms=elapsed_ms,
    )
