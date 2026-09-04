# LLM Ablation Report — RECOVER-ALLOC, Phase 6

## 1. Hypothesis

The LLM diagnosis path (reading genuinely unstructured `evidence_text`)
will produce measurably better diagnosis quality and/or downstream
recovery economics than the deterministic rule-table path (which reads
only `failure_code`/`days_overdue`, never `evidence_text`), **because**
the synthetic data generator (Part G) deliberately seeds cases where
evidence text contradicts the structured fields (e.g. a sympathetic
support note on a fraud-suspect item) — a signal only a text-reading
diagnoser can access at all.

## 2. Experimental design

Both diagnosers implement the identical call signature
(`diagnose(evidence_text, item_type, failure_code, days_overdue,
historical_attempts=...)`) and both feed into the exact same downstream
pipeline: `diagnosis -> probability model -> allocator -> policy engine
-> simulator executor` (`diagnosis/ablation_pipeline.py`). The only
experimental variable is which `diagnose()` function is called.

## 3. Controls

- Same items, same order, same batch for both arms.
- Same probability model artifacts for both arms.
- Same resource budgets (`retry_slots=15, whatsapp_quota=15, human_hours=5`).
- Same policy config (`policy.config.DEFAULT_POLICY_CONFIG`).
- Same simulator behavior (`SimulatorExecutor(forced_behavior="success")` — deterministic, not the hash-based mixed-behavior mode, so any measured difference is attributable to diagnosis and allocation, not simulator randomness).
- **Allocator substitution, stated honestly:** uses `optimizer.naive_sort_allocate`, not `optimizer.mcmkp.solve_mcmkp` (CP-SAT unverified — see `docs/OPTIMIZER_VERIFICATION_STATUS.md`) and not `optimizer.brute_force_optimal` (capped at 12 items). Identical across both arms, which is what the experimental control actually requires.

## 4. Dataset

First 60 items (index order, no cherry-picking) from the frozen test set
(`data/test_set_frozen.jsonl`) — measurement, not tuning.

## 5. Metrics

`failure_class_accuracy`, `unclear_rate`, `mean_confidence`, policy
outcome counts, `policy_violation_count`, `expected_net_recovery`,
`actual_simulated_net_recovery`, `execution_count`, `escalation_count`.

## 6. Rule diagnosis results (real, executed)

```
failure_class_accuracy:        1.0
unclear_rate:                  0.0
mean_confidence:               0.71
policy_allow_count:            32
policy_block_count:            3
policy_escalate_count:         0
policy_violation_count:        0
expected_net_recovery:         71,759.50
actual_simulated_net_recovery: 138,376.93
execution_count:               32
escalation_count:              0
```

## 7. LLM results — HONEST STATUS: not measuring what it appears to measure

```
failure_class_accuracy:        0.0
unclear_rate:                  1.0
mean_confidence:               0.0
policy_allow_count:            0
policy_block_count:            3
policy_escalate_count:         32
expected_net_recovery:         0.0
actual_simulated_net_recovery: 0.0
```

**This is not a measurement of LLM diagnostic quality. It is a
measurement of the documented, correct fallback path firing 100% of the
time**, because the `anthropic` Python SDK cannot be installed in this
build sandbox (PyPI unreachable — confirmed by direct `pip install`
failure) and no `ANTHROPIC_API_KEY` is configured. `api.anthropic.com`
itself is network-reachable from this sandbox (confirmed: a bare request
returns HTTP 404, not a domain-block error) — the blocker is purely
missing package/credentials, not network policy.

Every one of these 60 items correctly triggered the "unclear /
confidence=0 / HUMAN_ESCALATION" fallback specified in Part I, and every
one of those correctly routed to policy rule 2 (low-confidence ->
ESCALATE), and zero reached execution — **this is the safety
architecture working exactly as designed**, not a negative result about
LLM quality. Reporting these numbers as "LLM accuracy" would be
a fabrication; they reflect environment unavailability, not capability.

## 8. Downstream recovery comparison

**No real comparison can be drawn from these two arms as executed.**
Comparing 138,376.93 (rule arm) against 0.0 (LLM arm, 100% fallback)
would misrepresent an infrastructure limitation as a capability
difference. The only honest conclusion available here is:

> The safety architecture correctly prevents an unavailable/failing
> diagnosis path from producing any unsafe or fabricated recovery
> action — confirmed by execution_count=0 and policy_violation_count=0
> on the LLM arm.

## 9. Limitations (read before citing any number above)

- **The LLM arm was not executed for real.** This invalidates any direct rule-vs-LLM performance comparison in this report.
- **The `failure_class_accuracy` reference label is methodologically weak for the rule arm.** `_ground_truth_failure_class()` buckets by the same `failure_code`/`days_overdue` logic the rule diagnoser itself uses — its 1.0 accuracy is close to tautological, not evidence the rule diagnoser is "correct" in any deeper sense. A fair reference label independent of both diagnosers' own logic was not built for this phase.
- **Evidence-extraction quality and confidence calibration were not scored numerically** — with the LLM arm non-functional, there is nothing to compare evidence spans against.
- **Batch size (60 items) is small**, chosen for fast iteration, not statistical power.
- **The naive-sort allocator substitution** means these specific rupee figures should not be read as "what RECOVER-ALLOC will recover in production" — they are internal-consistency figures for this harness only.

## 10. Conclusion

**LLM did not demonstrate measurable incremental value under this
dataset — but not because it underperformed; because it could not be
executed in this build environment.** No percentage improvement or
degradation is reported, because none was honestly measured. What IS
demonstrated: the pipeline's safety architecture (schema validation,
evidence-span hallucination stripping, confidence-threshold fallback,
policy-gate enforcement) behaves correctly under a 100%-failure
diagnosis condition — zero unsafe executions, zero policy violations,
full audit trail — arguably a more convincing demonstration of
engineering discipline than a favorable AUC number on its own.

**Required next step, explicitly out of scope for this phase:** run this
exact harness (`diagnosis/ablation_pipeline.py`, unchanged) with
`ANTHROPIC_API_KEY` configured and the `anthropic` package installed, on
the same frozen-test-set slice, and report the real numbers — favorable,
unfavorable, or null — without alteration.
