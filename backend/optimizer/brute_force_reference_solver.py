"""
BRUTE-FORCE EXACT REFERENCE SOLVER — sandbox verification aid ONLY.

THIS IS NOT CP-SAT. THIS IS NOT A PRODUCTION COMPONENT. It is never
imported by optimizer/mcmkp.py, any strategy in strategies/, or any
production code path. It exists for exactly one reason, stated plainly:

    `ortools` cannot be installed in the current sandbox (no network
    egress; confirmed via direct import failure, not assumed). The
    locked spec's Critical Test #1 requires proving
    "MCMKP/ILP objective > naive objective" on a genuine counterexample.
    Since the real CP-SAT solver cannot be executed here, this module
    computes the EXACT global optimum by exhaustive enumeration over
    every possible assignment — a completely different, independently
    correct method (not an approximation, not a heuristic, not a
    reimplementation of CP-SAT's search) that is only tractable because
    the counterexample and stress-test instances are deliberately small
    (<= ~10 items). It is mathematically guaranteed to find the true
    optimum on any instance it can enumerate, which is exactly the
    property needed to validate the naive-sort counterexample and to
    sanity-check the feasibility checker.

Once OR-Tools is available in a real environment, `optimizer/mcmkp.py`
(the real CP-SAT implementation) must be run against the SAME fixtures,
and `tests/test_optimizer_counterexample.py` documents exactly which
assertion additionally needs to hold there:
    cp_sat_result.objective_value == brute_force_result.objective_value
on every instance small enough to brute-force, since both are exact
solvers and must agree. That comparison is UNVERIFIED in this sandbox.
"""
import itertools
import time
import uuid
from decimal import Decimal

from domain.enums import InterventionType, SolverStatus, VALID_INTERVENTIONS_BY_ITEM_TYPE
from optimizer.feasibility import check_allocation_feasibility
from optimizer.result import AllocationResult

MAX_ITEMS_FOR_BRUTE_FORCE = 12  # 4^12 ≈ 16.7M is already slow; keep instances well under this


def brute_force_optimal(
    *,
    items_by_id: dict,
    probabilities: dict,
    resources_budget: dict,
    interventions_catalog: dict,
    min_intervention_amount: float = 100.0,
    max_contacts_per_week: int = 3,
) -> AllocationResult:
    start = time.monotonic()
    item_ids = list(items_by_id.keys())
    if len(item_ids) > MAX_ITEMS_FOR_BRUTE_FORCE:
        raise ValueError(
            f"brute_force_optimal is a sandbox verification aid only and "
            f"refuses instances larger than {MAX_ITEMS_FOR_BRUTE_FORCE} items "
            f"(got {len(item_ids)}) — this is by design, not a bug. Use "
            f"optimizer/mcmkp.py (CP-SAT) for real batches."
        )

    # Build, for each item, its list of choices: None, or one of its valid
    # interventions THAT has a known probability estimate.
    choices_per_item = []
    for item_id in item_ids:
        item = items_by_id[item_id]
        options = [None]
        for intervention in VALID_INTERVENTIONS_BY_ITEM_TYPE.get(item.type, ()):
            if (item_id, intervention) in probabilities:
                options.append(intervention)
        choices_per_item.append(options)

    best_objective = None
    best_assignment = None

    for combo in itertools.product(*choices_per_item):
        assignment = dict(zip(item_ids, combo))
        violations = check_allocation_feasibility(
            assignments=assignment,
            items_by_id=items_by_id,
            resources_budget=resources_budget,
            interventions_catalog=interventions_catalog,
            min_intervention_amount=min_intervention_amount,
            max_contacts_per_week=max_contacts_per_week,
        )
        if violations:
            continue

        objective = Decimal("0")
        for item_id, intervention in assignment.items():
            if intervention is None:
                continue
            item = items_by_id[item_id]
            p = probabilities[(item_id, intervention)]
            cost = interventions_catalog[intervention].cost_inr
            objective += Decimal(str(item.amount)) * Decimal(str(p)) - cost

        if best_objective is None or objective > best_objective:
            best_objective = objective
            best_assignment = assignment

    elapsed_ms = (time.monotonic() - start) * 1000

    if best_assignment is None:
        # Even "assign nothing to everyone" is always feasible and has
        # objective 0, so this should be unreachable — defensive only.
        best_assignment = {iid: None for iid in item_ids}
        best_objective = Decimal("0")

    return AllocationResult(
        status=SolverStatus.OPTIMAL,
        assignments=best_assignment,
        objective_value=best_objective,
        solve_time_ms=elapsed_ms,
        solver_run_id=str(uuid.uuid4()),
        method="brute_force_reference",
    )
