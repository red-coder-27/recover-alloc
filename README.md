# RECOVER-ALLOC — Intelligent Revenue Operations & Recovery Allocation System

> **Decision-Aware Multi-Choice Multi-Dimensional Knapsack (MCMKP) Engine for Merchant Revenue Recovery**  
> *Razorpay AI Buildathon 2026 — Revenue Recovery Track Submission*

---

## Executive Summary & Business Problem

When merchants face failed payments, overdue invoices, or subscription churn, recovery operations depend on strictly bounded capacity:
- **Payment Retry API Limits**: Constrained daily transaction retries.
- **Messaging Quotas**: Bounded WhatsApp/SMS communication limits.
- **Human Operations Hours**: Limited manual escalation agent hours.

### Why Naive Greedy Allocation Fails
Standard recovery systems sort accounts greedily by monetary amount or raw recovery probability and assign the highest-cost intervention to top-ranked items. This creates severe **resource starvation**: high-value accounts hog scarce multi-resource channels (like WhatsApp or Human Escalation), locking out accounts that have zero alternative fallback options. The result is depleted budgets, contact fatigue, policy violations, and unrecovered revenue.

### The RECOVER-ALLOC Solution
**RECOVER-ALLOC** formulates revenue recovery as a **Multi-Choice Multi-Dimensional Knapsack Problem (MCMKP)** solved via **Google OR-Tools CP-SAT**. It globally maximizes expected net recovery across all accounts and resource constraints simultaneously, guided by a decision-aware, isotonic-calibrated probability model and enforced by a 100% deterministic policy engine.

---

## AI Judgment: Where AI Helps — and Where It Doesn't

> **"AI proposes evidence. Deterministic systems decide what is allowed to happen."**

```
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                            AI PROPOSES EVIDENCE                           │
 ├─────────────────────────────────────────┬─────────────────────────────────┤
 │ LLM (Claude / Anthropic)                │ Machine Learning (Isotonic HGB) │
 │ • Unstructured evidence extraction      │ • Conditioned recovery prob p   │
 │ • Categorizes failure reasons           │ • Decision-aware calibration    │
 └─────────────────────────────────────────┴─────────────────────────────────┘
                                     │
                                     ▼
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                    DETERMINISTIC SYSTEMS DECIDE EXECUTION                 │
 ├───────────────────────────────────────────────────────────────────────────┤
 │ • Policy Engine: 100% rule-based (consent, caps, retry ceilings, floor)   │
 │ • MCMKP CP-SAT Optimizer: Hard linear constraint feasibility & bounds     │
 │ • Execution & Idempotency: DB UNIQUE key prevents duplicate dispatches    │
 │ • Audit Trail: Immutable SQLite append-only event logging                 │
 └───────────────────────────────────────────────────────────────────────────┘
```

- **LLM Has ZERO Execution Authority**: The LLM output is strictly schema-validated for diagnostic classification. It cannot trigger dispatches, modify policy rules, or allocate resources.
- **Deterministic Control Gate is Authoritative**: Operational rules and resource budgets are strictly enforced by CP-SAT and the deterministic policy engine.

---

## Formally Validated Economic Benchmark Results

> **Note on Evaluation Data**: All recovery amounts below reflect **SIMULATED evaluation results** evaluated across 20 random outcome seeds on the frozen 100-item benchmark dataset (`data/test_set_frozen.jsonl`, SHA-256: `7ca70f5e32614f61d43a9a7986169c666b39b556bf21d92b759a7463fe4a06df`).

### 1. Strategy Comparison (20-Seed Frozen Benchmark)

| Strategy | Realized Net Recovery (20-Seed Mean) | Expected Ratio vs Oracle | Realized Ratio vs Oracle | vs Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Oracle Benchmark** | **₹1,92,135.66** | 100.00% | 100.00% | — |
| **RECOVER-ALLOC (Isotonic)** | **₹1,74,817.99** | **93.89%** | **90.99%** | **Base** |
| **Random Under Budget** | ₹1,38,861.66 | 74.57% | 72.27% | **+25.89%** |
| **Static Rules** | ₹91,972.61 | 49.38% | 47.87% | **+90.07%** |
| **Blind Retry** | ₹79,478.46 | 42.66% | 41.37% | **+120.00%** |
| **No Action** | ₹0.00 | 0.00% | 0.00% | — |

*Clarification on Oracle Benchmark*: The **Oracle Benchmark** evaluates performance using hidden true recovery probabilities under identical resource budgets. It is a simulator-ground-truth reference benchmark, NOT a theoretical maximum of real-world Razorpay revenue.

---

### 2. Verified Mathematical Optimization Counterexample

A documented 5-item counterexample fixture demonstrates why naive sorting fails under multi-resource competition:

```
Naive Value-Greedy Sort: ₹24,845.50
CP-SAT MCMKP Optimal   : ₹27,644.30
Net Optimization Gain  : +₹2,798.80 (+11.26%)
```
*CP-SAT solver matches exact brute-force optimum across 100 / 100 randomized test instances with 0 feasibility violations.*

---

### 3. Decision-Aware Probability Calibration & Optimizer's Curse

When uncalibrated probabilities are passed to an optimization solver, the solver selectively picks over-predicted items (**Optimizer's Curse**). Isotonic calibration eliminates this tail bias:

| Model | Selected Portfolio $\hat{p}$ | Selected Portfolio $p_{\text{true}}$ | Selection Bias |
| :--- | :---: | :---: | :---: |
| **Raw Uncalibrated HGB** | 67.10% | 39.50% | **+27.60 pp** |
| **Isotonic Calibrated Model** | 40.18% | 39.50% | **+0.68 pp** |

- **Raw HGB**: Suffers from **+27.60 percentage points** of selection optimism bias ($\hat{p} = 67.10\%$ vs $p_{\text{true}} = 39.50\%$).
- **Isotonic Model**: Reduces bias to **+0.68 pp** ($\hat{p} = 40.18\%$ vs $p_{\text{true}} = 39.50\%$), enabling CP-SAT to select a higher-value portfolio (+₹6,026.67 net value gain).

---

## What Broke — and How the System Recovers

Engineering and stress testing uncovered key edge cases, handled as follows:

1. **Contact Fatigue Allocator Conflict**: Reallocating unconstrained items freed capacity for constrained accounts, enforcing contact caps across 100% of allocations.
2. **WhatsApp Consent Fallback Bug**: Policy gate strictly blocks WhatsApp actions when consent is unverified, falling back to Retry or Escalation.
3. **$\hat{p}$ vs $p_{\text{true}}$ Mismatch**: Kept model predictions ($\hat{p}$) separated from hidden ground-truth scoring ($p_{\text{true}}$), preventing evaluation leakage.
4. **Missing Anthropic Credentials**: Handled via deterministic `rule_diagnoser.py` fallback without breaking the pipeline.
5. **External Timeout**: Mapped to `UNCERTAIN` execution status without automatic retries.
6. **Concurrent Duplicate Execution**: Prevented via database `idempotency_key` `UNIQUE` constraint returning `DUPLICATE_BLOCKED`.
7. **Solver Failure**: Returns `SOLVER_FAILED` status with 0 unverified dispatches attempted.

---

## What to Look For in the Demo

When exploring the Control Center dashboard at `http://localhost:8000/app/index.html`:

1. **MCMKP Allocation Plan**: Click **Run MCMKP Allocation Plan** on the *Revenue Allocation* tab. Observe the spinner (`⟳ Running MCMKP Allocation...`), inspect the `OPTIMAL` CP-SAT solver result modal, and view capacity utilization bars.
2. **Greedy vs MCMKP Comparison**: On the *Allocation Intelligence* tab, view the live side-by-side comparison illustrating the +11.26% optimization gain over naive sort.
3. **Policy Gate Action Semantics**:
   - `ALLOW` → **Execute** button active
   - `BLOCK` → **Blocked 🔒**
   - `ESCALATE` → **Review Req ⚠️**
   - `UNSERVED` → **No Capacity ⏸️**
4. **Controlled Failure Scenarios** (on *Audit Trail & Idempotency* tab):
   - **Duplicate Execution → Block**: Rejects duplicate dispatches under the same idempotency key (`DUPLICATE_EXECUTION_BLOCKED`).
   - **Low Confidence → Escalate**: Deliberately triggers low confidence, policy outcome `ESCALATE`, automatic execution `BLOCKED`, safety action `human review required`.
   - **Budget Exhaustion → Stop**: Solves under tight budget (2 Retries, 2 WhatsApp, 0 Human Hours), displaying 96 unserved items.
   - **Solver Failure → Safe Stop**: Triggers `SOLVER_FAILED` status with 0 dispatches attempted.
   - **Razorpay Test Payment Link**: Demonstrates credential-guarded execution (`NOT_EXECUTED` when test credentials are absent).
5. **Audit Trail**: View real-time append-only event traces (`EXECUTION_REQUESTED` → `EXECUTION_CLAIMED` → `EXECUTION_DISPATCHED` → `EXECUTION_VERIFIED`).
6. **Evaluation Leaderboard**: View the 20-seed frozen evaluation benchmark table.

---

## System Architecture & Pipeline

```
[ Evidence Collection ] ──> [ Failure Diagnosis ] ──> [ Probability Model ] 
                                                              │
[ Audit Log & Executions ] <── [ Idempotent Executor ] <── [ Policy Gate ] <── [ MCMKP CP-SAT ]
```

1. **Evidence Collection**: Gathers account features, overdue days, historical attempts, and failure codes.
2. **Evidence Diagnosis**: Categorizes failure reasons via `rule_diagnoser.py` (or optional LLM evidence classifier).
3. **Probability Model**: Isotonic-calibrated HGB predicts recovery probability $p(\text{recovery} \mid \text{item}, \text{intervention})$.
4. **MCMKP Optimizer**: OR-Tools CP-SAT maximizes total net recovery value subject to multi-resource constraints.
5. **Policy Gate**: 100% deterministic rule chain enforces consent, floor limits, retry ceilings, and fatigue caps.
6. **Idempotent Execution & Verification**: Executes dispatches via simulator or Razorpay test adapter guarded by SQLite DB `UNIQUE(idempotency_key)`.

---

## Deploy on Render

### Verified Application Specs
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python -m uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- **Working Directory**: `backend/`
- **Health Check Path**: `/health` (HTTP 200)
- **Frontend Path**: `/app/index.html` (mounted automatically at `/app`)
- **Required Environment Variables**:
  - `PORT`: (Provided dynamically by host environment)
- **Optional Environment Variables**:
  - `RAZORPAY_TEST_KEY_ID`: Razorpay test key ID
  - `RAZORPAY_TEST_KEY_SECRET`: Razorpay test secret
  - `ANTHROPIC_API_KEY`: Anthropic Claude API key
- **SQLite Database Behavior**:
  The SQLite database file (`data/recover_alloc_demo.db`) is automatically initialized on application startup. In ephemeral container environments (such as Render Web Services), SQLite operates as disposable demo state that resets cleanly on container restarts.

---

## If This Went to Production

The following steps outline future production-hardening requirements for live deployment:
1. **Validated Production Data Pipelines**: Connect directly to merchant core databases and Razorpay Webhook streams.
2. **Persistent Production Database**: Replace local SQLite with managed PostgreSQL (e.g. AWS RDS or Render Postgres).
3. **Merchant Custom Policy Engine**: Expose merchant-specific rule overrides (custom retry delays, brand-specific fatigue caps).
4. **Calibration Drift Monitoring**: Automated background re-calibration on new transaction outcomes.
5. **Human Escalation Workflow**: Integrated operator dashboard for manually reviewing `ESCALATE` accounts.
6. **Production Observability**: OpenTelemetry tracing and Prometheus metrics.
7. **Razorpay Live-Mode Integration**: Transition test-mode payment link executor to live production Payment Links API with webhook reconciliation.

---

## Quickstart & Local Setup

```bash
# 1. Install dependencies
pip install -r backend/requirements.txt

# 2. Run unit test suite (168 tests)
python -m unittest discover -s backend/tests -p "test_*.py"

# 3. Start FastAPI dev server
cd backend
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```
Open browser to: `http://localhost:8000/app/index.html`

---

## Project Structure

```
recover-alloc/
├── render.yaml                 # Render deployment configuration
├── Makefile                    # Developer tasks
├── README.md                   # System documentation & verification report
├── backend/
│   ├── api/                    # FastAPI endpoints & SQLite database helpers
│   │   ├── main.py
│   │   └── db.py
│   ├── diagnosis/              # Failure diagnosis (rule diagnoser & LLM evidence classifier)
│   ├── domain/                 # Enums, catalog models, and domain data structures
│   ├── evaluation/             # 20-seed benchmark runner & ground-truth scorer
│   ├── execution/              # Idempotent execution service & Razorpay test adapter
│   ├── optimizer/              # OR-Tools CP-SAT MCMKP formulation & brute-force reference
│   ├── policy/                 # Deterministic policy engine
│   ├── probability/            # HGB model, feature extraction & isotonic calibration
│   └── tests/                  # 168 unit tests & economic sanity checks
├── data/
│   ├── test_set_frozen.jsonl   # Frozen evaluation test set
│   └── test_set.checksum      # Dataset SHA-256 integrity checksum
├── docs/                       # Architectural design & verification documentation
└── frontend/                   # Control Center dashboard (HTML, CSS, JS)
    ├── index.html
    ├── styles.css
    └── app.js
```
