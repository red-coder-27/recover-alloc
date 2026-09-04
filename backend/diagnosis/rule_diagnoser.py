"""
Rule-table diagnosis — RECOVER-ALLOC, Path B of the mandatory LLM ablation
(Part 13/M/Q). Deterministic, no external dependencies, always available.

This is deliberately dumb relative to the LLM path: it looks ONLY at
`failure_code` / `days_overdue` / `item_type`, never at `evidence_text`.
That gap is the entire point of the ablation — if a case's true failure
class can only be inferred from the unstructured text (e.g. a
contradiction between a clean failure_code and a support note describing
suspicious behavior), the rule table cannot see it and the LLM might.
"""
from dataclasses import dataclass, field

from domain.enums import DiagnosisSource, InterventionType


@dataclass
class Diagnosis:
    item_id: str = ""
    source: str = DiagnosisSource.RULE_TABLE.value
    failure_class: str = "unclear"
    evidence_spans: list = field(default_factory=list)
    confidence: float = 0.5
    recommended_interventions: list = field(default_factory=list)


# failure_code -> (failure_class, confidence, recommended_interventions)
_PAYMENT_LOOKUP = {
    "insufficient_funds": ("insufficient_funds", 0.75, [InterventionType.PAYMENT_RETRY, InterventionType.WHATSAPP_REMINDER]),
    "issuer_soft_decline": ("issuer_soft_decline", 0.70, [InterventionType.PAYMENT_RETRY]),
    "bank_server_error": ("bank_server_error", 0.80, [InterventionType.PAYMENT_RETRY]),
    "risk_threshold_hold": ("risk_threshold_hold", 0.55, [InterventionType.HUMAN_ESCALATION]),
    "expired_card": ("expired_card", 0.85, [InterventionType.WHATSAPP_REMINDER]),
    "do_not_honor": ("do_not_honor", 0.60, [InterventionType.HUMAN_ESCALATION]),
}


def diagnose(*, failure_code: str | None, days_overdue: int, item_type: str, evidence_text: str = "", historical_attempts: int = 0) -> Diagnosis:
    """
    `evidence_text` and `historical_attempts` are accepted in the
    signature only so callers can use a single shared interface for both
    diagnosers (see diagnosis/ablation_pipeline.py), but they are
    deliberately UNUSED here — see module docstring.
    """
    if item_type == "PAYMENT_FAILURE":
        if failure_code in _PAYMENT_LOOKUP:
            failure_class, confidence, recs = _PAYMENT_LOOKUP[failure_code]
            return Diagnosis(
                failure_class=failure_class,
                confidence=confidence,
                recommended_interventions=recs,
            )
        return Diagnosis(failure_class="unclear", confidence=0.2, recommended_interventions=[InterventionType.HUMAN_ESCALATION])

    # B2B_RECEIVABLE — bucketed purely on aging, per Part G's aging buckets.
    if days_overdue <= 30:
        return Diagnosis(
            failure_class="administrative_delay_receivable",
            confidence=0.65,
            recommended_interventions=[InterventionType.WHATSAPP_REMINDER],
        )
    if days_overdue <= 120:
        return Diagnosis(
            failure_class="genuine_hardship_receivable",
            confidence=0.55,
            recommended_interventions=[InterventionType.HUMAN_ESCALATION, InterventionType.WHATSAPP_REMINDER],
        )
    return Diagnosis(
        failure_class="dispute_risk_receivable",
        confidence=0.40,
        recommended_interventions=[InterventionType.HUMAN_ESCALATION],
    )
