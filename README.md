# RECOVER-ALLOC — Intelligent Revenue Operations & Recovery Allocation System

> **Decision-Aware Multi-Choice Multi-Dimensional Knapsack (MCMKP) Engine for B2B/Merchant Revenue Recovery**

---

## Executive Summary

When merchants face failed payments, invoices, or subscriptions, recovery capacity (retry API limits, WhatsApp quotas, human escalation hours) is strictly bounded. Generic recovery tools deploy naive rule-based retries or greedy sorting (highest amount first), which exhausts scarce resources on suboptimal items and triggers severe contact fatigue or policy violations.

**RECOVER-ALLOC** formulates merchant revenue recovery as a **Multi-Choice Multi-Dimensional Knapsack Problem (MCMKP)** solved via **Google OR-Tools CP-SAT**. Driven by a decision-aware, isotonic-calibrated machine learning probability model and guarded by a 100% deterministic policy engine, RECOVER-ALLOC optimizes expected net recovery value while enforcing hard resource budgets and operational constraints.

---

## System Architecture

```
                                  [ Input Failed Accounts / Items ]
                                                  │
                                                  ▼
                                      [ Diagnostic Engine ]
                          (Rule-based classification + LLM contextual evidence)
                                                  │
                                                  ▼
                                     [ Calibrated Probability Model ]
                          (Isotonic-calibrated HGB: p(recovery | item, intervention))
                                                  │
                                                  ▼
                                      [ Deterministic Policy Engine ]
                       (Consent, Contact Caps, Retry Ceilings, Fraud, Monetary Floor)
                                                  │
                                                  ▼
                                    [ MCMKP CP-SAT Optimization Solver ]
                    (Objective: Max ∑ p_hat * Amount - Cost  s.t.  Resource Budgets)
                                                  │
                                                  ▼
                                     [ Idempotent Execution Layer ]
                       (SQLite DB Transaction + Razorpay Test Adapter / Simulator)
                                                  │
                                                  ▼
                                   [ Immutable Audit Trail & Metrics ]
```

### Core Architecture Guarantee
- **LLM Has Zero Execution Authority**: The LLM is strictly used for unstructured evidence extraction and failure categorization. It cannot select actions, override policy gates, or trigger execution.
- **Deterministic Policy Engine is Final Authority**: Policy rules (consent, ceilings, contact frequency caps) act as hard constraints in the optimization solver.

---

## Formally Validated Economic Benchmark Results

*Validated on frozen test dataset (`data/test_set_frozen.jsonl`, checksum verified).*

### 1. Strategy Comparison (20-Seed Benchmark)

| Strategy | Realized Net Recovery (INR) | Expected Ratio vs Oracle | Realized Ratio vs Oracle | vs Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Oracle (Upper Bound)** | **₹192,135.66** | 100.00% | 100.00% | — |
| **RECOVER-ALLOC (Isotonic)** | **₹174,817.99** | **93.89%** | **90.99%** | **Base** |
| **Random Under Budget** | ₹138,861.66 | 74.57% | 72.27% | **+25.89%** |
| **Static Rules** | ₹91,972.61 | 49.38% | 47.87% | **+90.07%** |
| **Blind Retry** | ₹79,478.46 | 42.66% | 41.37% | **+120.00%** |
| **No Action** | ₹0.00 | 0.00% | 0.00% | — |

---

### 2. Verified Mathematical Optimization Counterexample

A documented counterexample fixture proves that **Naive Greedy Sorting** (sorting items by amount or expected value individually) consumes scarce resources on suboptimal allocations:

```
Naive Greedy Value : ₹24,845.50
MCMKP Optimal Value: ₹27,644.30
Net Improvement    : +11.26% (+₹2,798.80)
```
*CP-SAT solver matches exact brute-force optimum across 100/100 randomized test instances with 0 feasibility violations.*

---

### 3. Model Calibration & Optimizer's Curse

| Model | Chosen Portfolio $p_{hat}$ | Chosen Portfolio $p_{true}$ | Portfolio Bias |
| :--- | :---: | :---: | :---: |
| **Raw Uncalibrated HGB** | 67.10% | 39.50% | **+9.80%** (Optimistic Tail Bias) |
| **Isotonic Calibrated Model** | 40.18% | 39.50% | **+0.68%** (Decision-Quality Winner) |

---

## FastAPI Backend Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `GET /health` | `GET` | System status, version, and database state |
| `GET /dashboard/summary` | `GET` | KPI metrics (Revenue at Risk, Recoverable Value, Resource Budgets) |
| `GET /recovery/items` | `GET` | Fetch revenue-at-risk accounts |
| `POST /recovery/plan` | `POST` | Execute MCMKP solver & generate optimal allocation plan |
| `POST /recovery/execute` | `POST` | Execute allocation with DB idempotency enforcement |
| `GET /recovery/executions` | `GET` | List past execution logs |
| `GET /audit/events` | `GET` | Retrieve structured audit events |
| `GET /evaluation/summary` | `GET` | Summary of 20-seed economic evaluation benchmark |
| `GET /evaluation/compare` | `GET` | MCMKP vs Naive Greedy counterexample comparison |

---

## Idempotency & Razorpay Integration

- **DB-Enforced Idempotency**: Executions are indexed by `idempotency_key` (`UNIQUE` constraint in SQLite). Duplicate requests return `DUPLICATE_BLOCKED` without re-triggering payment endpoints.
- **Razorpay Test-Mode Adapter**: Supports `RazorpayTestExecutor` when `RAZORPAY_TEST_KEY_ID` and `RAZORPAY_TEST_KEY_SECRET` are provided in `.env`.
- **Uncertain Outcome Handling**: In accordance with Razorpay Payment Link limitations, network timeouts surface `UNCERTAIN` state to operators without automatic retry loops.

---

## Quickstart & Installation

### 1. Prerequisites
- Python 3.10+
- Virtual environment (`venv` or `conda`)

### 2. Environment Setup
```bash
# Install dependencies
pip install -r backend/requirements.txt
```

### 3. Running Unit Tests
```bash
make test
# Or: python -m unittest discover -s backend/tests -p "test_*.py"
```

### 4. Running the Application & Web Dashboard
```bash
# Start FastAPI backend & static server
make server
# Or: python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```
Open browser to: `http://localhost:8000/app/index.html`

---

---

## Known Limitations

- **LLM Benchmark Availability**: The LLM evidence classifier relies on Anthropic's Claude API. If `ANTHROPIC_API_KEY` is unavailable or not set in `.env`, the system automatically falls back to deterministic rule-based diagnosis (`rule_diagnoser.py`) with zero impact on the CP-SAT optimizer, policy engine, or economic recovery performance. (Covered by 1 unit test skip in the test suite).

---

## Live Demo Walkthrough Instructions

1. **Start Server**: Run `make server` or `python -m uvicorn api.main:app --host 0.0.0.0 --port 8000` from the `backend/` directory.
2. **Open Dashboard**: Navigate to `http://localhost:8000/app/index.html` in your browser.
3. **MCMKP Allocation Plan**: On the **Revenue Allocation** tab, click **Run MCMKP Allocation Plan**. Observe the button loading spinner (`⟳ Running MCMKP Allocation...`), inspect the `OPTIMIMAL` CP-SAT solver result modal, and view the capacity utilization metrics.
4. **Execute Single Item**: Click **Execute** on any `ALLOW` item in the decision table. View the execution lifecycle audit trace in the modal.
5. **Test Controlled Scenarios** (on **Audit Trail & Idempotency** tab):
   - **Duplicate Execution → Block**: Exercises database `idempotency_key` constraint to block duplicate dispatch (`DUPLICATE_EXECUTION_BLOCKED`).
   - **Low Confidence → Escalate**: Deliberately triggers low-confidence diagnosis, policy outcome `ESCALATE`, automatic execution `BLOCKED`.
   - **Budget Exhaustion → Stop**: Applies tight capacity constraints (2 Retries, 2 WhatsApp, 0 Human Hours), demonstrating safe capacity exhaustion with 96 unserved items.
   - **Solver Failure → Safe Stop**: Triggers `SOLVER_FAILED` status with 0 unverified dispatches attempted.
   - **Razorpay Test Payment Link**: Demonstrates credential-guarded execution (`NOT_EXECUTED` when `RAZORPAY_TEST_KEY_ID`/`SECRET` are absent).
6. **Audit & Evaluation Tabs**: Inspect the append-only audit trail log and the 20-seed benchmark leaderboard.

---

## Project Structure

```
recover-alloc/
├── backend/
│   ├── api/                # FastAPI application, DB layer, CORS & static routing
│   │   ├── main.py
│   │   └── db.py
│   ├── diagnosis/          # Failure diagnosis (rule diagnoser + LLM evidence classifier)
│   ├── domain/             # Data models, intervention catalogs, and enums
│   ├── evaluation/         # Benchmark scoring, ground truth simulator, evaluation harness
│   ├── executor/           # Idempotent execution engine & Razorpay test-mode adapter
│   ├── optimizer/          # Google OR-Tools CP-SAT MCMKP formulation & feasibility engine
│   ├── policy/             # Deterministic operational policy engine
│   ├── probability/        # Feature extraction, HGB model, Isotonic calibration
│   └── tests/              # 168 unit tests & economic sanity checks
├── data/
│   ├── test_set_frozen.jsonl   # Frozen evaluation test set
│   └── test_set.checksum      # Dataset SHA-256 integrity checksum
├── docs/                   # System design & verification reports
├── frontend/               # Control center dashboard (HTML, CSS, JS)
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── docker-compose.yml
└── Makefile
```

