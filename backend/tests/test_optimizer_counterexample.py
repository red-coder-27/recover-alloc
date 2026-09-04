"""
CRITICAL TEST #1 — RECOVER-ALLOC, Locked spec Part 27 / Phase 3.

Proves, with an actually-executed fixture (not illustrative arithmetic),
that the exact optimal allocation strictly beats naive expected-value
sorting under multiple competing resource constraints.

HONESTY NOTE (read before trusting this test as "the ILP result"):
`brute_force_optimal` is an exact, independently-implemented enumeration
method — NOT OR-Tools CP-SAT, which cannot be installed in this sandbox.
It is mathematically guaranteed to find the same global optimum CP-SAT
would find on any instance small enough to enumerate (both are exact
methods; there is only one true optimum for a given instance). What this
test proves for certain: "the true optimal allocation strictly beats
naive sort on this fixture." What it does NOT prove: "OR-Tools CP-SAT,
as coded in optimizer/mcmkp.py, actually reproduces that same number" —
that specific claim is marked UNVERIFIED below and must be checked with
a real `ortools` install before being reported as confirmed.
"""
import os
import sys
import unittest
from dataclasses import dataclass
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.enums import InterventionType, ItemType
from domain.models_stdlib_mirror import INTERVENTION_CATALOG
from optimizer.brute_force_reference_solver import brute_force_optimal
from optimizer.feasibility import check_allocation_feasibility
from optimizer.naive_sort import naive_sort_allocate


@dataclass
class FixtureItem:
    """Minimal stand-in exposing exactly the attributes the optimizer/
    feasibility checker/naive sort need — avoids depending on the full
    RecoverableItem constructor for a hand-crafted numeric fixture."""
    id: str
    type: ItemType
    amount: Decimal
    merchant_id: str = "m1"
    historical_attempts: int = 0
    contact_count_7d: int = 0


class TestNaiveSortVsOptimalCounterexample(unittest.TestCase):
    """
    Fixture: 5 accounts, 3 interventions, 3 resources.

    CORRECTION NOTE: the locked spec's Part J prose worked example (with
    a single item E "made unusually WhatsApp-effective") was checked here
    against a genuinely fair, non-strawman global-value-sort greedy — and
    it does NOT produce a strict gap. Sorting ALL (item, intervention)
    candidates together (not per-resource) naturally lets E's WhatsApp
    option get picked before retry slots are exhausted, so naive sort
    reaches the same allocation as the true optimum on that fixture. This
    is exactly the risk flagged in advance in the locked spec itself
    (Part Z, risk #13: "illustrative numbers won't match generated data
    exactly... not proof against real solver output").

    The mechanism that actually defeats a fair greedy is different from
    what the prose described: it is a genuine ASSIGNMENT conflict, not a
    single-resource ranking artifact. Item D below has two options
    (WhatsApp is its best, Retry is its close second); Item E has only
    ONE option (WhatsApp) and no fallback. If D is greedily given its
    *own* best option (WhatsApp) because it globally outranks E's only
    option, D locks WhatsApp away from E — even though moving D to its
    second-best option (Retry, for which there is ample separate budget)
    would free WhatsApp for E and produce far more total value than
    letting D keep its individually-best choice. This is the textbook
    generalized-assignment-problem greedy failure mode, verified below
    with real numbers, not asserted.
    """

    @classmethod
    def setUpClass(cls):
        cls.items_by_id = {
            "A": FixtureItem(id="A", type=ItemType.B2B_RECEIVABLE, amount=Decimal("20000")),
            "B": FixtureItem(id="B", type=ItemType.PAYMENT_FAILURE, amount=Decimal("5000")),
            "C": FixtureItem(id="C", type=ItemType.PAYMENT_FAILURE, amount=Decimal("4800")),
            "D": FixtureItem(id="D", type=ItemType.PAYMENT_FAILURE, amount=Decimal("10000")),
            "E": FixtureItem(id="E", type=ItemType.B2B_RECEIVABLE, amount=Decimal("12000")),
        }

        cls.probabilities = {
            ("A", InterventionType.HUMAN_ESCALATION): 0.85,
            ("B", InterventionType.PAYMENT_RETRY): 0.50,
            ("C", InterventionType.PAYMENT_RETRY): 0.50,
            # D is the "switcher": WhatsApp is individually best, Retry a
            # close-but-real second choice.
            ("D", InterventionType.WHATSAPP_REMINDER): 0.32,
            ("D", InterventionType.PAYMENT_RETRY): 0.29,
            # E has NO fallback — WhatsApp is its only valid option with a
            # known estimate (it is a B2B_RECEIVABLE; PAYMENT_RETRY is not
            # even a valid intervention for this item type, per Part D).
            ("E", InterventionType.WHATSAPP_REMINDER): 0.2584,
        }

        # whatsapp_quota=1 is the deliberately scarce resource D and E
        # both compete for; retry_slots=3 is exactly enough for B, C, and
        # D's fallback simultaneously (never a binding constraint by
        # itself — the conflict is purely about who gets WhatsApp).
        cls.resources_budget = {"retry_slots": 3, "whatsapp_quota": 1, "human_hours": 1}
        cls.catalog = INTERVENTION_CATALOG  # cost_inr: retry=2, whatsapp=0.5, human=250

    def test_naive_and_optimal_both_produce_feasible_allocations(self):
        naive_result = naive_sort_allocate(
            items_by_id=self.items_by_id, probabilities=self.probabilities,
            resources_budget=self.resources_budget, interventions_catalog=self.catalog,
        )
        optimal_result = brute_force_optimal(
            items_by_id=self.items_by_id, probabilities=self.probabilities,
            resources_budget=self.resources_budget, interventions_catalog=self.catalog,
        )
        for result, label in [(naive_result, "naive"), (optimal_result, "optimal")]:
            violations = check_allocation_feasibility(
                assignments=result.assignments, items_by_id=self.items_by_id,
                resources_budget=self.resources_budget, interventions_catalog=self.catalog,
            )
            self.assertEqual(violations, [], f"{label} allocation infeasible: {violations}")

    def test_optimal_strictly_beats_naive_sort(self):
        """THE mandatory assertion: exact optimum > naive sort, strictly."""
        naive_result = naive_sort_allocate(
            items_by_id=self.items_by_id, probabilities=self.probabilities,
            resources_budget=self.resources_budget, interventions_catalog=self.catalog,
        )
        optimal_result = brute_force_optimal(
            items_by_id=self.items_by_id, probabilities=self.probabilities,
            resources_budget=self.resources_budget, interventions_catalog=self.catalog,
        )
        print(f"\n  naive_sort objective   = {naive_result.objective_value}")
        print(f"  naive_sort assignments = {naive_result.assignments}")
        print(f"  optimal objective      = {optimal_result.objective_value}")
        print(f"  optimal assignments    = {optimal_result.assignments}")
        self.assertGreater(
            optimal_result.objective_value,
            naive_result.objective_value,
            "REQUIRED: exact optimal allocation must strictly beat naive sort "
            "on this multi-resource fixture — if this fails, the fixture no "
            "longer demonstrates the claimed counterexample.",
        )

    def test_naive_sort_starves_E_by_giving_D_its_individually_best_option(self):
        """Documents naive sort's specific failure: D takes WhatsApp (its
        own best option), locking E out entirely since E has no fallback."""
        naive_result = naive_sort_allocate(
            items_by_id=self.items_by_id, probabilities=self.probabilities,
            resources_budget=self.resources_budget, interventions_catalog=self.catalog,
        )
        self.assertEqual(naive_result.assignments["D"], InterventionType.WHATSAPP_REMINDER)
        self.assertIsNone(naive_result.assignments["E"], "naive sort should leave E completely unserved")

    def test_optimal_reallocates_D_to_retry_freeing_whatsapp_for_E(self):
        """
        Documents the SPECIFIC mechanism the optimum exploits: give up D's
        individually-best option (WhatsApp) in favor of its close second
        (Retry, for which there is ample separate budget), freeing
        WhatsApp for E — which naive sort structurally cannot do, since
        it never reconsiders an already-assigned item's choice.
        """
        optimal_result = brute_force_optimal(
            items_by_id=self.items_by_id, probabilities=self.probabilities,
            resources_budget=self.resources_budget, interventions_catalog=self.catalog,
        )
        self.assertEqual(optimal_result.assignments["D"], InterventionType.PAYMENT_RETRY)
        self.assertEqual(optimal_result.assignments["E"], InterventionType.WHATSAPP_REMINDER)

    @unittest.skip(
        "UNVERIFIED IN THIS SANDBOX: requires `ortools` installed. Once "
        "available, this test must assert "
        "cp_sat_result.objective_value == brute_force_result.objective_value "
        "on this exact fixture, proving CP-SAT reproduces the true optimum "
        "computed independently above."
    )
    def test_cp_sat_matches_brute_force_optimum(self):
        from optimizer.mcmkp import solve_mcmkp  # would raise ModuleNotFoundError today
        cp_sat_result = solve_mcmkp(
            items_by_id=self.items_by_id, probabilities=self.probabilities,
            resources_budget=self.resources_budget, interventions_catalog=self.catalog,
        )
        optimal_result = brute_force_optimal(
            items_by_id=self.items_by_id, probabilities=self.probabilities,
            resources_budget=self.resources_budget, interventions_catalog=self.catalog,
        )
        self.assertEqual(cp_sat_result.objective_value, optimal_result.objective_value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
