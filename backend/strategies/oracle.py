"""
Oracle - RECOVER-ALLOC, Phase 7 / locked spec Part R.
Same MCMKP formulation, same constraints, same interventions, same
costs as RECOVER-ALLOC - the ONLY difference is the probability input
source: TRUE hidden p_true instead of the trained model's predictions.

CRITICAL PROPERTY, made structural, not just documented: this module
takes a `true_probabilities` dict as an explicit parameter (p_true per
(item_id, intervention), supplied by the caller from
evaluation.scorer.HiddenGroundTruthScorer.p_true()) - it NEVER reads a
realized outcome, and has no parameter through which one could be
passed. The distinction between "Oracle may use hidden p_true" and
"Oracle must NOT use the realized outcome" is enforced by this module's
signature having no outcome parameter at all, verified in
tests/test_evaluation_leakage.py.

STATUS: same CP-SAT dependency as recover_alloc.py - marked UNAVAILABLE
under identical conditions, for the identical honest reason.
"""
import time

from strategies.base import StrategyAllocationResult


def allocate(items_by_id, resources_budget, true_probabilities=None, interventions_catalog=None, **kwargs):
    start = time.monotonic()

    try:
        import ortools  # noqa
        ortools_available = True
    except ModuleNotFoundError:
        ortools_available = False

    if not ortools_available:
        return StrategyAllocationResult(
            strategy_name="oracle",
            assignments={item_id: None for item_id in items_by_id},
            expected_objective=0,
            solver_status="UNAVAILABLE",
            solve_time_ms=(time.monotonic() - start) * 1000,
            unavailable=True,
            unavailable_reason=(
                "Oracle requires the real CP-SAT solver for final evaluation "
                "(same formulation as RECOVER-ALLOC, per Part R). OR-Tools is "
                "not installed in this build sandbox."
            ),
            unavailable_dependency="ortools",
            unavailable_command="pip install ortools",
        )

    # Real path (unreachable here) — literally the SAME solve_mcmkp
    # function RECOVER-ALLOC calls, per Part R's explicit requirement.
    from optimizer.mcmkp import solve_mcmkp

    result = solve_mcmkp(
        items_by_id=items_by_id, probabilities=true_probabilities,
        resources_budget=resources_budget, interventions_catalog=interventions_catalog,
    )
    return StrategyAllocationResult(
        strategy_name="oracle", assignments=result.assignments,
        expected_objective=result.objective_value, solver_status=result.status.value,
        solve_time_ms=result.solve_time_ms,
    )
