"""
RECOVER-ALLOC - the real product strategy. Diagnosis (rule-table, since
LLM is unavailable) -> probability model -> MCMKP/CP-SAT -> policy
engine -> execution.

STATUS: marked UNAVAILABLE if CP-SAT (OR-Tools) cannot execute - per
Phase 7's explicit instruction, the naive-sort substitution used for the
Phase 6 ablation harness must NOT be carried into final evaluation.
Diagnosis uses the rule-table path (genuinely available and executed for
real) since that's a legitimate, honest choice independent of the
CP-SAT gap.
"""
import time

from diagnosis.rule_diagnoser import diagnose as rule_diagnose
from strategies.base import StrategyAllocationResult


def allocate(items_by_id, resources_budget, probabilities=None, interventions_catalog=None,
             diagnosis_source="rule_table", policy_config=None, **kwargs):
    start = time.monotonic()

    try:
        import ortools  # noqa
        ortools_available = True
    except ModuleNotFoundError:
        ortools_available = False

    if not ortools_available:
        return StrategyAllocationResult(
            strategy_name="recover_alloc",
            assignments={item_id: None for item_id in items_by_id},
            expected_objective=0,
            solver_status="UNAVAILABLE",
            solve_time_ms=(time.monotonic() - start) * 1000,
            unavailable=True,
            unavailable_reason=(
                "RECOVER-ALLOC requires the real CP-SAT solver for final "
                "evaluation (the Phase 6 naive-sort substitution is explicitly "
                "not carried into final evaluation per instructions). OR-Tools "
                "is not installed in this build sandbox (confirmed via direct "
                "ModuleNotFoundError, not assumed)."
            ),
            unavailable_dependency="ortools",
            unavailable_command="pip install ortools",
        )

    # Real path (unreachable in this build environment).
    from domain.enums import VALID_INTERVENTIONS_BY_ITEM_TYPE
    from optimizer.mcmkp import solve_mcmkp

    diagnoses = {}
    computed_probabilities = {}
    for item_id, item in items_by_id.items():
        d = rule_diagnose(
            failure_code=getattr(item, "failure_code", None), days_overdue=getattr(item, "days_overdue", 0),
            item_type=item.type.value,
        )
        diagnoses[item_id] = d.failure_class
        for interv in VALID_INTERVENTIONS_BY_ITEM_TYPE[item.type]:
            key = (item_id, interv)
            if probabilities and key in probabilities:
                computed_probabilities[key] = probabilities[key]

    result = solve_mcmkp(
        items_by_id=items_by_id, probabilities=computed_probabilities,
        resources_budget=resources_budget, interventions_catalog=interventions_catalog,
    )
    return StrategyAllocationResult(
        strategy_name="recover_alloc", assignments=result.assignments,
        expected_objective=result.objective_value, solver_status=result.status.value,
        solve_time_ms=result.solve_time_ms, diagnoses=diagnoses,
    )
