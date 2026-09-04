"""
MCMKP optimizer — RECOVER-ALLOC, Locked spec Part J (mathematical model)
and Part K (implementation). PRODUCTION CODE using Google OR-Tools CP-SAT.

STATUS: `ortools` cannot be installed in this build sandbox (no network
egress — confirmed by direct ModuleNotFoundError, not assumed). This file
has been syntax-validated (`python -m py_compile`) and structurally
reviewed against the Part J formulation, but the actual CP-SAT solve
calls in this module have NOT been executed. See
optimizer/brute_force_reference_solver.py for the independent exact
method used instead to validate the naive-sort counterexample and stress
tests in this sandbox, and tests/test_optimizer_counterexample.py for the
explicit statement of what remains unverified until OR-Tools is
installed in a real environment.

Decision variable: x[i,j] ∈ {0,1} for every valid (item i, intervention j)
pair with a known probability estimate.

Objective (maximize):
    Σ_i Σ_j  x[i,j] · ( amount[i] · p(recover | i, j) − cost[j] )

Constraints:
    1. resource budgets:      Σ x[i,j]·consumption[j][r] ≤ budget[r]  ∀r
    2. at-most-one per item:  Σ_j x[i,j] ≤ 1                           ∀i
    3. contact-frequency limit: pre-solve elimination (x[i,j]=0 fixed)
    4. retry ceiling:           pre-solve elimination
    5. monetary floor:          pre-solve elimination
    6. merchant policy tier:    extra summed constraint on the relevant subset

CP-SAT works over integers, so the objective (which involves amount ×
probability, both potentially fractional) is scaled to integer cents/
micro-units before being handed to the solver, and the returned
objective is scaled back down for reporting.
"""
import time
import uuid
from decimal import Decimal

from domain.enums import InterventionType, ItemType, SolverStatus, VALID_INTERVENTIONS_BY_ITEM_TYPE
from optimizer.result import AllocationResult

# Fixed-point scale for CP-SAT's integer-only objective (Part K note).
# amount * p_recover can have several decimal places of real economic
# meaning (₹ and probability to 5 dp); scale generously to avoid
# rounding materially changing the optimal choice between close options.
OBJECTIVE_SCALE = 100_000

DEFAULT_SOLVE_TIMEOUT_LIVE_SECONDS = 5.0
DEFAULT_SOLVE_TIMEOUT_EVAL_SECONDS = 30.0


def solve_mcmkp(
    *,
    items_by_id: dict,
    probabilities: dict,
    resources_budget: dict,
    interventions_catalog: dict,
    min_intervention_amount: float = 100.0,
    max_contacts_per_week: int = 3,
    merchant_human_escalation_caps: dict | None = None,  # merchant_id -> max human_hours for 'strict' tier
    timeout_seconds: float = DEFAULT_SOLVE_TIMEOUT_LIVE_SECONDS,
) -> AllocationResult:
    """
    Real CP-SAT implementation. Import is deferred inside the function
    body (rather than at module top) so that importing this module for
    documentation/type-checking purposes doesn't hard-fail in an
    environment without ortools installed — but calling this function
    without ortools installed will raise ModuleNotFoundError, which is
    the correct, honest failure mode (see Part K's SOLVER_ERROR handling
    in strategies/recover_alloc.py, which catches exactly this).
    """
    from ortools.sat.python import cp_model  # noqa: local import, see docstring

    start = time.monotonic()
    solver_run_id = str(uuid.uuid4())
    model = cp_model.CpModel()

    # --- Variable construction: only valid (item, intervention) pairs
    # with a known probability estimate get a variable at all. This is
    # the structural enforcement of constraint set item #... (valid
    # intervention per item type) — an invalid pair simply never has a
    # variable, so it is impossible for the solver to select it.
    x = {}
    valid_pairs = []
    for item_id, item in items_by_id.items():
        for intervention in VALID_INTERVENTIONS_BY_ITEM_TYPE.get(item.type, ()):
            key = (item_id, intervention)
            if key not in probabilities:
                continue

            catalog_entry = interventions_catalog[intervention]

            # Pre-solve elimination per Part J constraints 3/4/5:
            if item.historical_attempts >= catalog_entry.max_frequency_per_item:
                continue
            if intervention in (InterventionType.WHATSAPP_REMINDER, InterventionType.HUMAN_ESCALATION):
                if item.contact_count_7d >= max_contacts_per_week:
                    continue
            if float(item.amount) < min_intervention_amount:
                continue

            x[key] = model.NewBoolVar(f"x_{item_id}_{intervention.value}")
            valid_pairs.append(key)

    if not valid_pairs:
        elapsed_ms = (time.monotonic() - start) * 1000
        return AllocationResult(
            status=SolverStatus.OPTIMAL,
            assignments={iid: None for iid in items_by_id},
            objective_value=Decimal("0"),
            solve_time_ms=elapsed_ms,
            solver_run_id=solver_run_id,
            method="cp_sat",
        )

    # --- Constraint: at-most-one intervention per item.
    for item_id in items_by_id:
        item_vars = [x[key] for key in valid_pairs if key[0] == item_id]
        if item_vars:
            model.Add(sum(item_vars) <= 1)

    # --- Constraint: resource budgets (the multidimensional part).
    for resource, budget in resources_budget.items():
        terms = []
        for (item_id, intervention) in valid_pairs:
            consumption = interventions_catalog[intervention].resources_consumed.get(resource, 0)
            if consumption:
                terms.append(consumption * x[(item_id, intervention)])
        if terms:
            model.Add(sum(terms) <= budget)

    # --- Constraint: merchant policy tier cap on HUMAN_ESCALATION usage.
    if merchant_human_escalation_caps:
        by_merchant: dict[str, list] = {}
        for (item_id, intervention) in valid_pairs:
            if intervention != InterventionType.HUMAN_ESCALATION:
                continue
            merchant_id = items_by_id[item_id].merchant_id
            by_merchant.setdefault(merchant_id, []).append(x[(item_id, intervention)])
        for merchant_id, var_list in by_merchant.items():
            cap = merchant_human_escalation_caps.get(merchant_id)
            if cap is not None:
                model.Add(sum(var_list) <= cap)

    # --- Objective (scaled to integers for CP-SAT).
    objective_terms = []
    for (item_id, intervention) in valid_pairs:
        item = items_by_id[item_id]
        p = probabilities[(item_id, intervention)]
        cost = interventions_catalog[intervention].cost_inr
        value = float(item.amount) * p - float(cost)
        scaled_value = round(value * OBJECTIVE_SCALE)
        objective_terms.append(scaled_value * x[(item_id, intervention)])
    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_seconds
    status_code = solver.Solve(model)

    elapsed_ms = (time.monotonic() - start) * 1000

    if status_code == cp_model.INFEASIBLE:
        return AllocationResult(
            status=SolverStatus.INFEASIBLE,
            assignments={iid: None for iid in items_by_id},
            objective_value=Decimal("0"),
            solve_time_ms=elapsed_ms,
            solver_run_id=solver_run_id,
            method="cp_sat",
        )

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return AllocationResult(
            status=SolverStatus.SOLVER_ERROR,
            assignments={iid: None for iid in items_by_id},
            objective_value=Decimal("0"),
            solve_time_ms=elapsed_ms,
            solver_run_id=solver_run_id,
            method="cp_sat",
        )

    assignments: dict[str, InterventionType | None] = {iid: None for iid in items_by_id}
    for (item_id, intervention) in valid_pairs:
        if solver.Value(x[(item_id, intervention)]) == 1:
            # Assertion per Part S #10 — invalid intervention pairs must
            # be structurally impossible to reach this point at all,
            # since `valid_pairs` was built exclusively from
            # VALID_INTERVENTIONS_BY_ITEM_TYPE. This assert exists so a
            # future refactor that breaks that invariant fails loudly
            # here rather than silently producing an unsafe allocation.
            assert intervention in VALID_INTERVENTIONS_BY_ITEM_TYPE[items_by_id[item_id].type], (
                f"INVARIANT VIOLATION: {intervention} assigned to {item_id} "
                f"of type {items_by_id[item_id].type} — this must never happen"
            )
            assignments[item_id] = intervention

    objective_value = Decimal(str(solver.ObjectiveValue() / OBJECTIVE_SCALE))
    result_status = SolverStatus.OPTIMAL if status_code == cp_model.OPTIMAL else SolverStatus.FEASIBLE

    return AllocationResult(
        status=result_status,
        assignments=assignments,
        objective_value=objective_value,
        solve_time_ms=elapsed_ms,
        solver_run_id=solver_run_id,
        method="cp_sat",
    )
