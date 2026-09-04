"""
LLM diagnosis output schema + validation — RECOVER-ALLOC, Locked spec
Part I.

Implemented with stdlib `dataclasses` + manual validation, matching the
pattern established in domain/models_stdlib_mirror.py — `pydantic` is not
installable in this build sandbox (confirmed, see Phase 1/2 reports).
This is NOT a throwaway mirror: the validation logic here is exactly
what a pydantic model would enforce, and is exercised by real, executed
tests (unlike domain/models.py, which genuinely needs pydantic and is
syntax-checked only). A thin pydantic wrapper can be added later without
changing any of this logic.

CRITICAL SAFETY PROPERTY, made structural, not just documented: this
module has ZERO imports from execution/, policy/, or optimizer/. This is
verified by tests/test_llm_diagnoser.py::test_llm_cannot_execute_financial_action
via direct source inspection, not just by convention.
"""
from dataclasses import dataclass, field

from domain.enums import DiagnosisSource, InterventionType

SCHEMA_VERSION = "llm-diagnosis-schema-v1"

ALLOWED_FAILURE_CLASSES = frozenset({
    "issuer_soft_decline", "insufficient_funds", "bank_server_error",
    "risk_threshold_hold", "expired_card", "do_not_honor",
    "genuine_hardship_receivable", "administrative_delay_receivable",
    "dispute_risk_receivable", "fraud_suspected", "unclear",
})

CONFIDENCE_ESCALATION_THRESHOLD = 0.35  # matches policy/config.py's default; kept as a separate named constant here since the LLM diagnoser's own fallback path must apply this BEFORE the allocation even reaches the policy engine (Part I: "If ... confidence below threshold ... route through policy to ESCALATE" — the diagnoser sets confidence=0 as its OWN fallback trigger; the policy engine's rule 2 is what actually enforces the escalation downstream. Two separate, redundant checks, deliberately.)


@dataclass
class LLMDiagnosisOutput:
    failure_class: str
    evidence_spans: list = field(default_factory=list)
    confidence: float = 0.0
    recommended_interventions: list = field(default_factory=list)
    reasoning_summary: str = ""
    # Determinism/audit metadata (Part 6's "record model identifier,
    # prompt/schema version, diagnosis version, timestamp" requirement).
    model_identifier: str = ""
    schema_version: str = SCHEMA_VERSION
    diagnosis_version: str = "v1.0.0"
    timestamp: float = 0.0
    # Populated by validation, not by the LLM itself.
    validation_issues: list = field(default_factory=list)


UNCLEAR_FALLBACK_KWARGS = dict(
    failure_class="unclear",
    evidence_spans=[],
    confidence=0.0,
    recommended_interventions=[InterventionType.HUMAN_ESCALATION],
    reasoning_summary="fallback: diagnosis could not be safely produced",
)


def validate_llm_output(raw: dict, source_evidence_text: str) -> LLMDiagnosisOutput:
    """
    Takes the RAW parsed JSON dict returned by the model (untrusted,
    potentially malformed or adversarial) and returns a validated
    LLMDiagnosisOutput. NEVER raises on bad input — always returns a
    safe object, falling back to the "unclear" state per Part I,
    recording exactly what was wrong in `validation_issues` for the
    audit trail.

    SECURITY PROPERTY: only the explicitly-named fields below are ever
    read from `raw`. Any additional/unexpected keys in `raw` (e.g. an
    injected `{"bypass_policy": true}` or `{"outcome": "ALLOW"}`) are
    silently ignored — there is no code path anywhere that reads an
    arbitrary key from the model's output and acts on it. This is what
    makes prompt injection structurally inert here, not just unlikely.
    """
    issues: list[str] = []

    if not isinstance(raw, dict):
        return LLMDiagnosisOutput(**UNCLEAR_FALLBACK_KWARGS, validation_issues=["raw output is not a JSON object"])

    failure_class = raw.get("failure_class")
    if failure_class not in ALLOWED_FAILURE_CLASSES:
        issues.append(f"failure_class '{failure_class}' not in allowed set; coerced to 'unclear'")
        failure_class = "unclear"

    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        issues.append(f"confidence '{confidence}' invalid or out of [0,1]; coerced to 0.0")
        confidence = 0.0

    raw_spans = raw.get("evidence_spans", [])
    if not isinstance(raw_spans, list):
        issues.append("evidence_spans is not a list; treated as empty")
        raw_spans = []

    validated_spans = []
    for span in raw_spans:
        if not isinstance(span, str):
            issues.append(f"evidence span {span!r} is not a string; dropped")
            continue
        if span not in source_evidence_text:
            issues.append(f"evidence span {span!r} not found verbatim in source text (possible hallucination); dropped")
            continue
        validated_spans.append(span)

    # Confidence penalty for hallucinated spans, per Part I — even if
    # some spans were valid, ANY hallucinated span downgrades confidence.
    n_hallucinated = len(raw_spans) - len(validated_spans)
    if n_hallucinated > 0:
        confidence = max(0.0, confidence - 0.25 * n_hallucinated)
        issues.append(f"{n_hallucinated} hallucinated evidence span(s) reduced confidence")

    raw_interventions = raw.get("recommended_interventions", [])
    if not isinstance(raw_interventions, list):
        raw_interventions = []
    validated_interventions = []
    valid_names = {i.value for i in InterventionType}
    for interv in raw_interventions:
        if interv in valid_names:
            validated_interventions.append(InterventionType(interv))
        else:
            issues.append(f"unrecognized intervention '{interv}' dropped")

    reasoning_summary = raw.get("reasoning_summary", "")
    if not isinstance(reasoning_summary, str):
        reasoning_summary = ""

    # Final fallback gate: if confidence (after any hallucination
    # penalty) is below threshold, force the full "unclear" fallback —
    # never let a partially-valid but low-confidence diagnosis through
    # with a specific failure_class attached.
    if confidence < CONFIDENCE_ESCALATION_THRESHOLD:
        issues.append(f"final confidence {confidence:.2f} below escalation threshold; forced to unclear/HUMAN_ESCALATION")
        return LLMDiagnosisOutput(**UNCLEAR_FALLBACK_KWARGS, validation_issues=issues)

    return LLMDiagnosisOutput(
        failure_class=failure_class,
        evidence_spans=validated_spans,
        confidence=confidence,
        recommended_interventions=validated_interventions or [InterventionType.HUMAN_ESCALATION],
        reasoning_summary=reasoning_summary,
        validation_issues=issues,
    )
