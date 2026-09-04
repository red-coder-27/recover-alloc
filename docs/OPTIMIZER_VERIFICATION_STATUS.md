# Optimizer Verification Status — CP-SAT vs. Brute-Force Reference

## Component Roles

- **`optimizer/mcmkp.py` (OR-Tools CP-SAT) = THE PRODUCTION OPTIMIZER.**
  This is the production optimizer used across all recovery allocation strategies. It scales to large batch sizes (hundreds–thousands of items) that brute force cannot solve.

- **`optimizer/brute_force_reference_solver.py` = CORRECTNESS ORACLE FOR SMALL INSTANCES ONLY.**
  It is an independent reference component used exclusively for correctness verification. It raises `ValueError` on any instance larger than 12 items by design. Its sole purpose is to independently compute the true global optimum on small fixtures, allowing CP-SAT's output to be checked against an algorithmically independent solver.

---

## Initial Verification Blocker

Earlier sandbox verification could not execute CP-SAT because OR-Tools was unavailable in the initial build environment.

---

## Final Verification Status

- **CP-SAT executes successfully.**
- **CP-SAT matched the independent brute-force reference on 100/100 randomized small instances.**
- **0 feasibility violations across all verified instances.**
- **Counterexample CP-SAT objective matched the exact brute-force optimum** (₹27,644.30).
- **CP-SAT objective was $\ge$ naive-sort objective** on the counterexample (+₹2,798.80 / +11.26% gain).
- **Brute-force solver remains the independent correctness oracle for small instances only.**
- **CP-SAT remains the production optimizer.**
