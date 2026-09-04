"""
AllocationResult — RECOVER-ALLOC, Locked spec Part K.
Pure stdlib, shared by mcmkp.py, naive_sort.py, and (sandbox-only)
brute_force_reference_solver.py so all three produce a comparable shape.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from domain.enums import InterventionType, SolverStatus


@dataclass
class AllocationResult:
    status: SolverStatus
    assignments: dict[str, InterventionType | None]  # item_id -> intervention or None (unserved)
    objective_value: Decimal
    solve_time_ms: float
    solver_run_id: str
    method: str = ""  # e.g. "cp_sat", "naive_sort", "brute_force_reference" — for audit/debug clarity
