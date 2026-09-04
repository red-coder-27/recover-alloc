# Optimizer Verification Status — CP-SAT vs. Brute-Force Reference

## Roles (do not conflate these two, ever)

- **`optimizer/mcmkp.py` (OR-Tools CP-SAT) = THE PRODUCTION OPTIMIZER.**
  This is what ships. It is the only allocator strategies/recover_alloc.py
  and strategies/oracle.py are permitted to call in production. It scales
  to real batch sizes (hundreds–thousands of items) that brute force
  cannot touch.

- **`optimizer/brute_force_reference_solver.py` = CORRECTNESS ORACLE FOR
  SMALL INSTANCES ONLY.** It is not a production component, is never
  imported by any strategy, and refuses (raises `ValueError`) on any
  instance larger than 12 items by design. Its sole purpose is to
  independently compute the *true* global optimum on small, hand-crafted
  or randomly-generated fixtures, so CP-SAT's output can be checked
  against a method that does not share any code path with CP-SAT's
  search — the two are not the same algorithm and do not fail the same
  way, which is exactly what makes agreement between them meaningful.

## Current status (as of this build)

`ortools` is not installed in this build environment (confirmed via
direct `ModuleNotFoundError`, not assumed — see Phase 3 report). This
means:

| Claim | Status |
|---|---|
| `optimizer/mcmkp.py` is syntactically valid Python | VERIFIED (`py_compile`) |
| `optimizer/mcmkp.py`'s constraint/objective construction matches Part J structurally | VERIFIED (manual review against Part J, cross-checked against the same objective/constraint code the brute-force solver and naive-sort baseline independently implement) |
| CP-SAT actually executes and returns a solution | **UNVERIFIED** |
| CP-SAT's objective equals the brute-force exact optimum on the counterexample fixture | **UNVERIFIED** — `test_cp_sat_matches_brute_force_optimum` exists and is `@unittest.skip`-marked with this exact assertion, ready to un-skip |
| CP-SAT's allocation passes the independent feasibility checker | **UNVERIFIED** — same test also asserts this once un-skipped |
| CP-SAT objective ≥ naive-sort objective | **UNVERIFIED** — trivially expected to hold if the above two hold, since CP-SAT is an exact solver and naive sort is one particular feasible allocation, but must still be checked, not assumed |

## Required steps once `ortools` is installed (do these in order, do not skip)

1. `pip install ortools` (or via `requirements.txt`).
2. Un-skip `test_cp_sat_matches_brute_force_optimum` in
   `tests/test_optimizer_counterexample.py`.
3. Run it. Required outcome: `cp_sat_result.objective_value ==
   brute_force_result.objective_value` on the exact D/E counterexample
   fixture (see that file for the fixture and the honest correction note
   about why the original Part J prose example doesn't produce a strict
   gap).
4. Additionally assert, on the same fixture:
   `check_allocation_feasibility(cp_sat_result.assignments, ...) == []`
   and `cp_sat_result.objective_value >= naive_result.objective_value`.
5. Extend `tests/test_optimizer_stress.py`'s randomized instances to also
   run `solve_mcmkp` (not just `brute_force_optimal` and
   `naive_sort_allocate`) on instances small enough to brute-force
   (≤12 items), asserting the two exact methods agree on every seed. This
   is the real, at-scale version of step 3 — one fixture passing is
   necessary but not sufficient confidence for a production claim.
6. Only after steps 1–5 pass may Phase 3's gate be reported as fully
   closed (currently it is reported as PASSED for the feasibility/
   counterexample requirements via the brute-force method, with CP-SAT
   execution explicitly carved out as the one remaining unverified item —
   see the Phase 3 report).

Do not replace the brute-force solver once OR-Tools is available. It
remains the permanent correctness oracle for small instances — CP-SAT
should be validated against it in CI going forward, not just once.
