"""
LLM Only - RECOVER-ALLOC, Phase 7 / locked spec Part Q.
LLM diagnosis + probability model + optimizer, but SKIPS the policy
engine entirely (never wired to a real executor - evaluation only).

STATUS: marked UNAVAILABLE if either (a) the LLM diagnosis path cannot
produce real output (SDK/credentials missing) or (b) CP-SAT cannot
execute. Since LLM diagnosis collapses to 100% fallback in this
environment, running this strategy to completion would only re-measure
environment unavailability, not real "LLM Only" behavior - so it is
deliberately marked UNAVAILABLE rather than reporting a degenerate
all-fallback result as if it were meaningful.
"""
import os
import time

from strategies.base import StrategyAllocationResult


def allocate(items_by_id, resources_budget, probabilities=None, interventions_catalog=None, **kwargs):
    start = time.monotonic()

    try:
        import anthropic  # noqa
        sdk_available = True
    except ModuleNotFoundError:
        sdk_available = False

    api_key_present = bool(os.environ.get("ANTHROPIC_API_KEY"))

    try:
        import ortools  # noqa
        ortools_available = True
    except ModuleNotFoundError:
        ortools_available = False

    if not sdk_available or not api_key_present:
        return StrategyAllocationResult(
            strategy_name="llm_only",
            assignments={item_id: None for item_id in items_by_id},
            expected_objective=0,
            solver_status="UNAVAILABLE",
            solve_time_ms=(time.monotonic() - start) * 1000,
            unavailable=True,
            unavailable_reason=(
                "LLM diagnosis path is not executable in this environment "
                f"(anthropic SDK installed: {sdk_available}, "
                f"ANTHROPIC_API_KEY configured: {api_key_present}); running this "
                "strategy would only measure the fallback path, not real "
                "LLM-only allocation behavior."
            ),
            unavailable_dependency="anthropic (package + ANTHROPIC_API_KEY)",
            unavailable_command="pip install anthropic && export ANTHROPIC_API_KEY=...",
        )

    if not ortools_available:
        return StrategyAllocationResult(
            strategy_name="llm_only",
            assignments={item_id: None for item_id in items_by_id},
            expected_objective=0,
            solver_status="UNAVAILABLE",
            solve_time_ms=(time.monotonic() - start) * 1000,
            unavailable=True,
            unavailable_reason="LLM diagnosis is available but CP-SAT (OR-Tools) is not.",
            unavailable_dependency="ortools",
            unavailable_command="pip install ortools",
        )

    # Real path (unreachable in this build environment; included so the
    # strategy is genuinely ready to run once both dependencies exist).
    from diagnosis.llm_diagnoser import diagnose as llm_diagnose
    from optimizer.mcmkp import solve_mcmkp

    diagnoses = {}
    for item_id, item in items_by_id.items():
        d = llm_diagnose(
            evidence_text=getattr(item, "evidence_text", ""), item_type=item.type.value,
            failure_code=getattr(item, "failure_code", None), days_overdue=getattr(item, "days_overdue", 0),
        )
        diagnoses[item_id] = d.failure_class

    result = solve_mcmkp(
        items_by_id=items_by_id, probabilities=probabilities,
        resources_budget=resources_budget, interventions_catalog=interventions_catalog,
    )
    return StrategyAllocationResult(
        strategy_name="llm_only", assignments=result.assignments,
        expected_objective=result.objective_value, solver_status=result.status.value,
        solve_time_ms=result.solve_time_ms, diagnoses=diagnoses,
    )
