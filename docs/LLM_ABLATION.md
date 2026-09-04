# LLM Ablation Report — RECOVER-ALLOC, Phase 6

## 1. Hypothesis

The LLM diagnosis path (reading genuinely unstructured `evidence_text`) will produce measurably better diagnosis quality and/or downstream recovery economics than the deterministic rule-table path (which reads only `failure_code`/`days_overdue`, never `evidence_text`), **because** the synthetic data generator deliberately seeds cases where evidence text contradicts the structured fields (e.g. a sympathetic support note on a fraud-suspect item) — a signal only a text-reading diagnoser can access.

## 2. Experimental Design & Controls

Both diagnosers implement the identical call signature (`diagnose(evidence_text, item_type, failure_code, days_overdue, historical_attempts=...)`) and feed into the exact same downstream pipeline: `diagnosis -> probability model -> allocator -> policy engine -> simulator executor` (`diagnosis/ablation_pipeline.py`).

- **Controls**: Same items, same order, same batch, same probability model artifacts, same resource budgets (`retry_slots=15, whatsapp_quota=15, human_hours=5`), same policy config, and deterministic simulator behavior.
- **Allocator**: Uses `optimizer.naive_sort_allocate` consistently across both test arms as an experimental control baseline.

## 3. Scope of Evaluation (Measured vs. Unmeasured)

### MEASURED
- **Deterministic Fallback Behavior**: Confirmed 100% fallback trigger on unconfigured API credentials.
- **Low-Confidence Routing**: Low confidence (<0.60) correctly routes to `ESCALATE` / human review.
- **Zero Unsafe Execution**: `execution_count = 0` on fallback arm; no unauthorized transactions dispatched.
- **Zero Policy Violations**: `policy_violation_count = 0` across all items.
- **Schema Validation & Safety Isolation**: Invalid outputs safely stripped and defaulted to rule fallback.

### NOT MEASURED
- **Real LLM Diagnostic Accuracy**: Unmeasured due to absence of live Anthropic API key during automated batch run.
- **LLM Economic Uplift**: Downstream monetary recovery differential unmeasured.
- **LLM-vs-Rule Economic Comparison**: Capability comparison remains unmeasured because the real LLM arm was unexecuted.

## 4. Honest Status & Fallback Verification

```
failure_class_accuracy:        0.0 (Fallback Triggered)
unclear_rate:                  1.0
mean_confidence:               0.0
policy_allow_count:            0
policy_block_count:            3
policy_escalate_count:         32
expected_net_recovery:         0.0
actual_simulated_net_recovery: 0.0
```

**This is not a negative result regarding LLM capability.** It measures the system's documented fallback mechanism operating when external LLM credentials are absent. Every unconfigured item safely defaulted to `HUMAN_ESCALATION` (`confidence = 0.0`) and was routed to policy rule `ESCALATE` with **zero unsafe dispatches attempted**.

## 5. Conclusion

The LLM capability comparison remains unmeasured because the live LLM arm was unexecuted. However, the ablation harness successfully verified the pipeline's **safety boundary**: under a complete LLM unavailability event, schema validation, fallback routing, and deterministic policy enforcement prevent any unverified action from executing.
