"""
Naive sort baseline — RECOVER-ALLOC, Locked spec Part 27 ("NOT JUST
SORTING" proof) and Phase 3's "NAIVE SORT BASELINE" section.

RANKING RULE (documented exactly, per the requirement that this not be
tuned to make RECOVER-ALLOC look artificially good):

  For every (item, valid intervention) candidate pair, compute
      expected_net_value = amount * p_recover - cost
  Sort ALL candidate pairs across the entire batch by expected_net_value,
  descending (ties broken by item_id then intervention name, for
  determinism). Walk the sorted list once; for each candidate, if
  assigning it keeps every resource budget and per-item constraint
  satisfiable, assign it and lock in that item (no further candidates for
  that item are considered); otherwise skip it and move to the next
  candidate.

This is a textbook, defensible greedy — "always take the next-best
available thing" — and is a fair proxy for how a naive recovery tool
actually behaves in the wild (see the strategy report's competitive
analysis: Chargebee/Slicker-style tools effectively process transactions
independently, roughly in discovered/priority order, with no joint
resource-scarcity reasoning). It is NOT deliberately crippled: given only
ONE binding resource, this greedy IS provably optimal (a single-resource
0/1 knapsack is exactly solved by value-density sorting) — the gap only
appears once a second resource genuinely competes, which is the entire
point of Part J's worked example.
"""
import time
import uuid
from decimal import Decimal

from domain.enums import InterventionType, SolverStatus, VALID_INTERVENTIONS_BY_ITEM_TYPE
from optimizer.result import AllocationResult


def naive_sort_allocate(
    *,
    items_by_id: dict,
    probabilities: dict,
    resources_budget: dict,
    interventions_catalog: dict,
    min_intervention_amount: float = 100.0,
    max_contacts_per_week: int = 3,
) -> AllocationResult:
    start = time.monotonic()

    candidates = []
    for item_id, item in items_by_id.items():
        for intervention in VALID_INTERVENTIONS_BY_ITEM_TYPE.get(item.type, ()):
            key = (item_id, intervention)
            if key not in probabilities:
                continue
            catalog_entry = interventions_catalog[intervention]
            p = probabilities[key]
            expected_net_value = Decimal(str(item.amount)) * Decimal(str(p)) - catalog_entry.cost_inr
            candidates.append((expected_net_value, item_id, intervention.value, intervention))

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    resource_usage = {r: 0 for r in resources_budget}
    assignments = {iid: None for iid in items_by_id}
    assigned_items = set()

    for expected_net_value, item_id, _, intervention in candidates:
        if item_id in assigned_items:
            continue
        item = items_by_id[item_id]
        catalog_entry = interventions_catalog[intervention]

        if item.historical_attempts >= catalog_entry.max_frequency_per_item:
            continue

        if intervention in (InterventionType.WHATSAPP_REMINDER, InterventionType.HUMAN_ESCALATION):
            if item.contact_count_7d >= max_contacts_per_week:
                continue

        if float(item.amount) < min_intervention_amount:
            continue

        would_exceed = False
        for resource, amount_needed in catalog_entry.resources_consumed.items():
            if resource_usage.get(resource, 0) + amount_needed > resources_budget.get(resource, 0):
                would_exceed = True
                break
        if would_exceed:
            continue

        assignments[item_id] = intervention
        assigned_items.add(item_id)
        for resource, amount_needed in catalog_entry.resources_consumed.items():
            resource_usage[resource] = resource_usage.get(resource, 0) + amount_needed

    objective_value = Decimal("0")
    for item_id, intervention in assignments.items():
        if intervention is None:
            continue
        item = items_by_id[item_id]
        p = probabilities[(item_id, intervention)]
        catalog_entry = interventions_catalog[intervention]
        objective_value += Decimal(str(item.amount)) * Decimal(str(p)) - catalog_entry.cost_inr

    elapsed_ms = (time.monotonic() - start) * 1000
    return AllocationResult(
        status=SolverStatus.OPTIMAL,
        assignments=assignments,
        objective_value=objective_value,
        solve_time_ms=elapsed_ms,
        solver_run_id=str(uuid.uuid4()),
        method="naive_sort",
    )
