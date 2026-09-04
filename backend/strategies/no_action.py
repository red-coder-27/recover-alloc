"""No Action strategy - the floor. Selects nothing, by construction."""
import time
import uuid
from decimal import Decimal

from domain.enums import SolverStatus
from strategies.base import StrategyAllocationResult


def allocate(items_by_id, resources_budget, **kwargs) -> StrategyAllocationResult:
    start = time.monotonic()
    assignments = {item_id: None for item_id in items_by_id}
    elapsed_ms = (time.monotonic() - start) * 1000
    return StrategyAllocationResult(
        strategy_name="no_action",
        assignments=assignments,
        expected_objective=Decimal("0"),
        solver_status=SolverStatus.OPTIMAL.value,
        solve_time_ms=elapsed_ms,
    )
