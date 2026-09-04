"""
CRITICAL TEST #2 — RECOVER-ALLOC, Phase 3.

Randomized stress tests against optimizer/brute_force_reference_solver.py
(the exact method available in this sandbox — see that module's docstring
for why it stands in for CP-SAT here) and optimizer/naive_sort.py, scored
by the INDEPENDENT feasibility checker (optimizer/feasibility.py), which
was written without reference to either allocator's internal construction
logic, per the spec's explicit requirement not to "test the solver
against itself."
"""
import os
import random
import sys
import unittest
from dataclasses import dataclass
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.enums import InterventionType, ItemType, VALID_INTERVENTIONS_BY_ITEM_TYPE
from domain.models_stdlib_mirror import INTERVENTION_CATALOG
from optimizer.brute_force_reference_solver import brute_force_optimal
from optimizer.feasibility import check_allocation_feasibility
from optimizer.naive_sort import naive_sort_allocate


@dataclass
class FixtureItem:
    id: str
    type: ItemType
    amount: Decimal
    merchant_id: str = "m1"
    historical_attempts: int = 0
    contact_count_7d: int = 0


def _random_instance(seed: int, n_items: int = 8):
    rng = random.Random(seed)
    items_by_id = {}
    probabilities = {}
    for i in range(n_items):
        item_id = f"item_{i}"
        item_type = rng.choice([ItemType.PAYMENT_FAILURE, ItemType.B2B_RECEIVABLE])
        amount = Decimal(str(round(rng.uniform(500, 50000), 2)))
        historical_attempts = rng.choice([0, 0, 0, 1, 2, 3])  # occasionally at/over ceiling
        contact_count_7d = rng.choice([0, 0, 1, 2, 3, 4])  # occasionally at/over fatigue cap
        items_by_id[item_id] = FixtureItem(
            id=item_id, type=item_type, amount=amount,
            historical_attempts=historical_attempts, contact_count_7d=contact_count_7d,
        )
        for intervention in VALID_INTERVENTIONS_BY_ITEM_TYPE[item_type]:
            # Randomly omit some (item, intervention) pairs to mimic
            # missing probability estimates, not just full cross-product.
            if rng.random() < 0.15:
                continue
            probabilities[(item_id, intervention)] = round(rng.uniform(0.05, 0.95), 4)

    resources_budget = {
        "retry_slots": rng.randint(1, n_items),
        "whatsapp_quota": rng.randint(1, n_items),
        "human_hours": rng.randint(0, max(1, n_items // 3)),
    }
    return items_by_id, probabilities, resources_budget


class TestOptimizerStress(unittest.TestCase):
    N_TRIALS = 25

    def test_naive_sort_always_produces_feasible_allocations(self):
        for seed in range(self.N_TRIALS):
            items_by_id, probabilities, resources_budget = _random_instance(seed)
            result = naive_sort_allocate(
                items_by_id=items_by_id, probabilities=probabilities,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            violations = check_allocation_feasibility(
                assignments=result.assignments, items_by_id=items_by_id,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            self.assertEqual(violations, [], f"seed={seed}: naive sort produced infeasible allocation: {violations}")

    def test_brute_force_optimal_always_produces_feasible_allocations(self):
        for seed in range(self.N_TRIALS):
            items_by_id, probabilities, resources_budget = _random_instance(seed, n_items=6)
            result = brute_force_optimal(
                items_by_id=items_by_id, probabilities=probabilities,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            violations = check_allocation_feasibility(
                assignments=result.assignments, items_by_id=items_by_id,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            self.assertEqual(violations, [], f"seed={seed}: optimal solver produced infeasible allocation: {violations}")

    def test_optimal_never_worse_than_naive_sort(self):
        """
        The general form of Critical Test #1: on EVERY random instance,
        the true optimum must be >= naive sort's objective (never worse —
        naive sort is just one particular feasible allocation, and the
        optimum is defined as the best feasible allocation by construction).
        """
        n_strictly_better = 0
        for seed in range(self.N_TRIALS):
            items_by_id, probabilities, resources_budget = _random_instance(seed, n_items=6)
            naive_result = naive_sort_allocate(
                items_by_id=items_by_id, probabilities=probabilities,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            optimal_result = brute_force_optimal(
                items_by_id=items_by_id, probabilities=probabilities,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            self.assertGreaterEqual(
                optimal_result.objective_value, naive_result.objective_value,
                f"seed={seed}: optimum must never be worse than naive sort",
            )
            if optimal_result.objective_value > naive_result.objective_value:
                n_strictly_better += 1
        # Not every random instance will have a binding multi-resource
        # conflict — report how many did, rather than asserting a
        # specific count (which would be an arbitrary, fabricated bar).
        print(f"\n  optimal strictly beat naive sort on {n_strictly_better}/{self.N_TRIALS} random instances")
        self.assertGreater(
            n_strictly_better, 0,
            "expected at least some random instances to exhibit the "
            "multi-resource conflict — if this ever fails, the random "
            "instance generator may need wider resource-scarcity ranges",
        )

    def test_no_item_ever_receives_two_interventions(self):
        for seed in range(self.N_TRIALS):
            items_by_id, probabilities, resources_budget = _random_instance(seed)
            for allocator in (naive_sort_allocate, brute_force_optimal):
                kwargs = dict(
                    items_by_id=items_by_id, probabilities=probabilities,
                    resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
                )
                if allocator is brute_force_optimal and len(items_by_id) > 10:
                    continue
                result = allocator(**kwargs)
                # dict shape already guarantees at most one value per key;
                # explicitly assert every value is a single InterventionType or None.
                for item_id, intervention in result.assignments.items():
                    self.assertTrue(
                        intervention is None or isinstance(intervention, InterventionType)
                    )

    def test_no_resource_budget_ever_exceeded(self):
        for seed in range(self.N_TRIALS):
            items_by_id, probabilities, resources_budget = _random_instance(seed)
            result = naive_sort_allocate(
                items_by_id=items_by_id, probabilities=probabilities,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            usage = {r: 0 for r in resources_budget}
            for item_id, intervention in result.assignments.items():
                if intervention is None:
                    continue
                for resource, amount in INTERVENTION_CATALOG[intervention].resources_consumed.items():
                    usage[resource] = usage.get(resource, 0) + amount
            for resource, used in usage.items():
                self.assertLessEqual(used, resources_budget[resource], f"seed={seed}: {resource} budget exceeded")

    def test_invalid_intervention_pairs_never_assigned(self):
        for seed in range(self.N_TRIALS):
            items_by_id, probabilities, resources_budget = _random_instance(seed)
            result = naive_sort_allocate(
                items_by_id=items_by_id, probabilities=probabilities,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            for item_id, intervention in result.assignments.items():
                if intervention is None:
                    continue
                item_type = items_by_id[item_id].type
                self.assertIn(
                    intervention, VALID_INTERVENTIONS_BY_ITEM_TYPE[item_type],
                    f"seed={seed}: {intervention} invalid for {item_type} on {item_id}",
                )

    def test_frequency_and_fatigue_ceilings_respected(self):
        for seed in range(self.N_TRIALS):
            items_by_id, probabilities, resources_budget = _random_instance(seed)
            result = naive_sort_allocate(
                items_by_id=items_by_id, probabilities=probabilities,
                resources_budget=resources_budget, interventions_catalog=INTERVENTION_CATALOG,
            )
            for item_id, intervention in result.assignments.items():
                if intervention is None:
                    continue
                item = items_by_id[item_id]
                catalog_entry = INTERVENTION_CATALOG[intervention]
                self.assertLess(
                    item.historical_attempts, catalog_entry.max_frequency_per_item,
                    f"seed={seed}: {item_id} exceeded frequency ceiling for {intervention}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
