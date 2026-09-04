"""
Strategy base interface - RECOVER-ALLOC, Phase 7 / locked spec Part Q.
"""
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class StrategyAllocationResult:
    strategy_name: str
    assignments: dict
    expected_objective: Decimal
    solver_status: str
    solve_time_ms: float
    diagnoses: dict = field(default_factory=dict)
    unavailable: bool = False
    unavailable_reason: str = ""
    unavailable_dependency: str = ""
    unavailable_command: str = ""
