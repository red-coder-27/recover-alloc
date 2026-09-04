# ML Diagnostic Findings — Probability Model, Phase 4 Follow-up

Protocol followed strictly: TRAIN for development, VALIDATION for model
selection, **frozen TEST never touched**. All numbers below are real,
executed, and reproducible (`data/*` + `probability/train.py`).

## 1. What features are currently available?

`days_overdue`, `historical_attempts`, `contact_count_7d`, `log_amount`,
`diagnosis_confidence`, one-hot `failure_code` (6 values), one-hot
`item_type`, one-hot `merchant_recovery_policy_tier`, one-hot
`diagnosis_failure_class` (11 values), and — added during this
diagnostic — `risk_flag_fraud_suspect` (see finding below).

## 2. Which features have measurable predictive signal?

Measured directly against the hidden `p_true` (legitimate offline
analysis of the data-generating process itself, not fed into any model):

| Feature | Correlation with p_true | Notes |
|---|---|---|
| `failure_code` (PAYMENT_RETRY) | explains **21.1%** of variance | Real, substantial, already a feature |
| `days_overdue` (WhatsApp/Human) | r ~ **-0.30 to -0.34** | Already a feature; correctly zero-variance (uninformative) for PAYMENT_RETRY, since payment failures always have `days_overdue=0` |
| `risk_flags` (fraud_suspect) | r ~ **-0.20 to -0.26** overall; **within-group effect is massive** (0% vs ~48% realized recovery rate) but flag prevalence is only ~2.5% of the population | Was **completely missing** from `features.py` before this diagnostic — see finding below |
| `historical_attempts` | r ~ **-0.07 to -0.11** | Weak but real (diminishing-returns effect, Part H beta4) |

## 3. Positive rate for each intervention (train set, realized outcomes)

PAYMENT_RETRY: 227/420 = 54.0%. WHATSAPP_REMINDER: 301/700 = 43.0%.
HUMAN_ESCALATION: 333/700 = 47.6%.

## 4. Constant base-rate Brier/log-loss baseline

For a constant predictor at the base rate `p`: Brier = `p(1-p)`. At these
positive rates that's ~0.248-0.250 for all three interventions — **this
is almost exactly what the trained model achieves** (0.245-0.251,
reported in the Phase 2 report). This is the single most important honest
number in this diagnostic: **the trained model is barely distinguishable
from predicting the base rate**, despite genuine features being available.

## 5. Does the model beat the constant baseline?

Marginally. Brier score is nearly identical to the constant baseline;
ROC-AUC (0.540-0.577) is the more sensitive measure and shows the model
*is* extracting some real signal — but far less than what's available (see #6).

## 6. How much of p_true variance is explained by observable features?

Directly measured (not estimated): the hidden `reliability_archetype`
alone explains **69.1% (PAYMENT_RETRY), 80.1% (WhatsApp), 81.7% (Human
Escalation)** of `p_true` variance. This variable is, by design (Part H),
never exposed to the model. The remaining ~20-31% of variance is what
observable features can, in principle, capture — and even a small
fraction of that (failure_code's 21% share for PAYMENT_RETRY alone) is a
real, substantial, currently under-exploited signal (see finding below).

## 7. Is reliability_archetype intentionally too dominant?

Given the explicit design intent in Part H ("the probability model
should have to learn," "not trivially deterministic"), a dominant hidden
variable is the correct design — it's what makes the prediction task
non-trivial and prevents the model from trivially memorizing observable
lookup tables. **69-82% dominance is a reasonable, intentional design
outcome, not a flaw to fix.** A ceiling AUC meaningfully above ~0.65-0.70
would be the actual red flag (it would suggest the hidden variable is
leaking through observables after all).

## 8. Are intervention effects strong enough for intervention-conditioned prediction to be meaningful?

Yes — beta2 (Part H) makes `HUMAN_ESCALATION` disproportionately effective
for aged B2B receivables versus `WHATSAPP_REMINDER`, and this is exactly
the interaction the Part J worked example (and the corrected
counterexample fixture) depends on. Training three separate
intervention-conditioned models, per the locked spec's explicit choice,
remains the right call.

## 9. Does the generated evidence_text actually contain recoverability information?

**Mostly no, honestly.** Templates are keyed almost entirely on
`failure_code`/`days_overdue` — fields already present as structured
data — so `evidence_text` is largely a restatement, not new information.
The one deliberate exception (Part G): ~50% of `fraud_suspect` items get
an appended sentence ("Customer was polite and confirmed billing details
matched exactly") that **contradicts** the hidden ground truth. This is a
narrow, real signal a text-reading diagnoser could exploit (the LLM
ablation should be tested against exactly this), but it currently
touches only ~1.3% of the population (half of the ~2.5% fraud-suspect
share) — too small to move an aggregate AUC number by itself, but
directly relevant to the ablation's *qualitative* framing.

## 10. Is the current rule diagnoser intentionally blind to useful evidence?

Yes, and correctly so — `diagnosis/rule_diagnoser.py`'s docstring states
this explicitly: it never reads `evidence_text`, by design, so the
LLM-vs-rule-table ablation has a real gap to test against (the
contradiction sentences from #9). This is not a bug to fix in Phase 4.

---

## Concrete finding: a real, fixable gap (not a data-generator problem)

`probability/features.py` **omitted `risk_flags` entirely**, directly
contradicting the locked spec's explicit statement (Part H): *"risk_flags
is included deliberately so the model can learn to suppress fraud-suspect
items."* This was a genuine implementation gap, found by this diagnostic,
not a tuning decision.

**Fix applied:** added `risk_flag_fraud_suspect` as a feature (Feature Set
C). **Result, measured honestly on validation (test set untouched):**
**zero measurable change** in AUC/Brier for any of the three
interventions. Root-caused directly (not guessed): only 6 of 420
PAYMENT_RETRY training rows carry the flag; a fitted
`HistGradientBoostingClassifier`, confirmed by zeroing the feature
post-hoc and diffing predictions, **never once splits on it** — 1.4%
prevalence is too sparse for the default tree configuration to find,
especially compounded by 5-fold calibration further subdividing an
already-small per-intervention training set.

**Second hypothesis tested (single, bounded, per "diagnostic not tuning
marathon"):** dropping the `diagnosis_class`/`diagnosis_confidence`
one-hot block (provably redundant with `failure_code`/`days_overdue`
under the deterministic rule table, since the rule table maps failure
codes to classes 1:1) to reduce feature-count dilution on the small
training set. Result: **mixed, marginal** (PAYMENT_RETRY 0.543->0.548,
WHATSAPP_REMINDER 0.540->0.530, HUMAN_ESCALATION 0.577->0.590) — not a
clear win. **Stopped here, per instructions, rather than iterating
further.**

## Answer to the actual question asked

**"Does the synthetic prediction task contain enough observable signal to
support a credible intervention-conditioned probability model?"**

**Partial yes, with an important caveat.** Real, substantial signal
exists (`failure_code` alone reaches AUC 0.582 for PAYMENT_RETRY with a
plain logistic regression — verified directly, not estimated) and the
task's low achievable ceiling (roughly 20-31% of p_true variance is
observable at all) is an intentional, correct design choice per Part H,
not a flaw. **But the current training pipeline is not yet reliably
reaching even that modest ceiling** — the risk_flags fix was
spec-correct but insufficient at current data volume; the
feature-trimming hypothesis was inconclusive. This is a genuine, open
methodological question for later phases (larger synthetic batch size,
or a training approach less sensitive to rare-feature sparsity, such as
`min_samples_leaf` tuning, or a class-imbalance-aware sample weight on
fraud-suspect rows) — **not** something to force-fix by inflating rare
classes ad hoc or by touching the frozen test set.

## Data-generator correction: not justified at this time

Per the explicit instruction, if the answer were NO, the recommendation
would be a data-generator change, not a model hack. The answer here is
**partial yes** — real signal exists and one concrete implementation gap
(missing `risk_flags` feature) was found and fixed, even though its
measured effect is currently null. **No data-generator change is
recommended in this phase.** If a future phase revisits this, the
smallest defensible generator change would be increasing the
`fraud_suspect` prevalence slightly (e.g., 3%->8%) specifically to give
the risk_flags feature enough training examples to be learnable — but
that changes the synthetic population's realism trade-off and should be
a deliberate, separately-reviewed decision, not bundled into this
diagnostic.
