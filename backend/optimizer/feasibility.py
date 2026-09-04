"""
check_allocation_feasibility() — RECOVER-ALLOC, Locked spec Part J / Phase 3
Critical Test #2.

Deliberately implemented WITHOUT any dependency on optimizer/mcmkp.py's
internal variable-construction code, so it can verify the solver's output
without testing the solver against itself. Any of the three allocation
producers (mcmkp.py, naive_sort.py, brute_force_reference_solver.py) can
be checked with the exact same function.
"""
from dataclasses import dataclass

from domain.enums import InterventionType, ItemType, VALID_INTERVENTIONS_BY_ITEM_TYPE


@dataclass
class FeasibilityViolation:
    kind: str
    detail: str


def check_allocation_feasibility(
    *,
    assignments: dict[str, InterventionType | None],
    items_by_id: dict,  # item_id -> object with .type, .amount, .historical_attempts, .contact_count_7d
    resources_budget: dict[str, int],
    interventions_catalog: dict,  # InterventionType -> Intervention (resources_consumed, max_frequency_per_item, etc.)
    min_intervention_amount: float = 100.0,
    max_contacts_per_week: int = 3,
) -> list[FeasibilityViolation]:
    """
    Returns an empty list if `assignments` is fully feasible; otherwise a
    list of violations describing exactly what's wrong. This function
    performs NO optimization — it only checks a given assignment.
    """
    violations: list[FeasibilityViolation] = []
    resource_usage: dict[str, int] = {r: 0 for r in resources_budget}

    for item_id, intervention in assignments.items():
        if intervention is None:
            continue
        item = items_by_id.get(item_id)
        if item is None:
            violations.append(FeasibilityViolation("unknown_item", item_id))
            continue

        # 1. Valid (item_type, intervention) pair.
        valid = VALID_INTERVENTIONS_BY_ITEM_TYPE.get(item.type, ())
        if intervention not in valid:
            violations.append(
                FeasibilityViolation(
                    "invalid_intervention_for_item_type",
                    f"{item_id}: {intervention} not valid for {item.type}",
                )
            )
            continue

        catalog_entry = interventions_catalog.get(intervention)
        if catalog_entry is None:
            violations.append(FeasibilityViolation("unknown_intervention", str(intervention)))
            continue

        # 2. Resource consumption accumulation (checked in full below).
        for resource, amount_consumed in catalog_entry.resources_consumed.items():
            resource_usage[resource] = resource_usage.get(resource, 0) + amount_consumed

        # 3. Retry ceiling.
        if item.historical_attempts >= catalog_entry.max_frequency_per_item:
            violations.append(
                FeasibilityViolation(
                    "frequency_ceiling_exceeded",
                    f"{item_id}: historical_attempts={item.historical_attempts} >= "
                    f"max_frequency_per_item={catalog_entry.max_frequency_per_item} for {intervention}",
                )
            )

        # 4. Contact-frequency ceiling (only applies to contact-based interventions).
        if intervention in (InterventionType.WHATSAPP_REMINDER, InterventionType.HUMAN_ESCALATION):
            if item.contact_count_7d >= max_contacts_per_week:
                violations.append(
                    FeasibilityViolation(
                        "contact_fatigue_ceiling_exceeded",
                        f"{item_id}: contact_count_7d={item.contact_count_7d} >= {max_contacts_per_week}",
                    )
                )

        # 5. Monetary floor.
        if float(item.amount) < min_intervention_amount:
            violations.append(
                FeasibilityViolation(
                    "below_monetary_floor",
                    f"{item_id}: amount={item.amount} < floor={min_intervention_amount}",
                )
            )

    # 6. At-most-one intervention per item (structurally guaranteed by dict
    #    shape here since assignments is item_id -> single value, but kept
    #    as an explicit check for callers that might pass a list of
    #    (item_id, intervention) pairs with accidental duplicates upstream).
    if len(assignments) != len(set(assignments.keys())):
        violations.append(FeasibilityViolation("duplicate_item_key", "assignments dict had duplicate item_id keys"))

    # 7. Resource budgets never exceeded.
    for resource, used in resource_usage.items():
        budget = resources_budget.get(resource, 0)
        if used > budget:
            violations.append(
                FeasibilityViolation(
                    "resource_budget_exceeded",
                    f"{resource}: used={used} > budget={budget}",
                )
            )

    return violations


def is_feasible(**kwargs) -> bool:
    return len(check_allocation_feasibility(**kwargs)) == 0
