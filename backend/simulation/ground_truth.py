"""
Ground truth generation — RECOVER-ALLOC, Locked spec Part H.

Implements:
    logit(P_true(recover | item, intervention)) =
          β0
        + β1 · reliability_archetype_effect(customer)     # HIDDEN
        + β2 · intervention_effectiveness(item_type, intervention)
        + β3 · f(days_overdue)
        + β4 · f(historical_attempts)
        + β5 · interaction(failure_code, intervention)
        + β6 · seasonal_noise(created_at)
        + ε
    P_true = sigmoid(logit)
    outcome ~ Bernoulli(P_true)

CRITICAL LEAKAGE-PREVENTION INVARIANT (do not violate this):
`reliability_archetype` is used ONLY inside this module. Nothing outside
`simulation/` may import `reliability_archetype_effect` or read the
archetype off a generated customer record when building the *observable*
item fields the model/LLM will see. The generator (generator.py) enforces
this by never copying `customer.reliability_archetype` into the fields of
a RecoverableItem — it exists solely as an attribute on the internal
customer-generation object consumed by this module.
"""
import hashlib
import math
import random
from dataclasses import dataclass
from enum import Enum

from domain.enums import ItemType, InterventionType


class ReliabilityArchetype(str, Enum):
    CHRONIC_GOOD_PAYER_GLITCH = "chronic_good_payer_glitch"
    GENUINELY_DISTRESSED = "genuinely_distressed"
    FRAUD_ADJACENT = "fraud_adjacent"
    SLOW_BUT_RELIABLE_B2B = "slow_but_reliable_b2b"


# Phase 7 addition: an INDEPENDENT hidden "true diagnostic class" per item,
# used ONLY by the evaluation scorer (never by any model, diagnoser, or
# production code path) to fairly score diagnosis accuracy against a
# reference that is NOT derived from the rule diagnoser's own
# failure_code/days_overdue bucketing logic (Phase 6's
# `_ground_truth_failure_class()` was tautological for exactly this
# reason — flagged honestly in docs/LLM_ABLATION.md and fixed here).
#
# This label is drawn from a per-archetype probability distribution over
# the SAME vocabulary the diagnosers use (`ALLOWED_FAILURE_CLASSES`), so
# it's naturally correlated with the archetype (as a real root cause
# would be) WITHOUT being a deterministic function of the observable
# failure_code — two items with identical failure_code can have
# different true_diagnostic_class values if their hidden archetypes
# differ, and the derivation never reads failure_code at all.
_TRUE_CLASS_DISTRIBUTION_BY_ARCHETYPE = {
    ReliabilityArchetype.CHRONIC_GOOD_PAYER_GLITCH: [
        ("bank_server_error", 0.45), ("issuer_soft_decline", 0.35), ("administrative_delay_receivable", 0.20),
    ],
    ReliabilityArchetype.GENUINELY_DISTRESSED: [
        ("insufficient_funds", 0.40), ("genuine_hardship_receivable", 0.35),
        ("risk_threshold_hold", 0.15), ("do_not_honor", 0.10),
    ],
    ReliabilityArchetype.FRAUD_ADJACENT: [
        ("fraud_suspected", 0.75), ("dispute_risk_receivable", 0.15), ("do_not_honor", 0.10),
    ],
    ReliabilityArchetype.SLOW_BUT_RELIABLE_B2B: [
        ("administrative_delay_receivable", 0.55), ("genuine_hardship_receivable", 0.30), ("unclear", 0.15),
    ],
}


def sample_true_diagnostic_class(archetype: ReliabilityArchetype, rng: random.Random) -> str:
    """
    HIDDEN GROUND TRUTH ONLY — never call this from anywhere except
    simulation/generator.py (to write it to test_set_ground_truth.jsonl)
    and evaluation/scorer.py (to score against it). Never expose the
    return value as a feature, and never let a diagnoser see the
    archetype this was derived from.
    """
    options = _TRUE_CLASS_DISTRIBUTION_BY_ARCHETYPE[archetype]
    r = rng.random()
    cumulative = 0.0
    for label, weight in options:
        cumulative += weight
        if r <= cumulative:
            return label
    return options[-1][0]


# β1 — HIDDEN effect, never exposed as a feature.
_ARCHETYPE_EFFECT = {
    ReliabilityArchetype.CHRONIC_GOOD_PAYER_GLITCH: 1.8,
    ReliabilityArchetype.GENUINELY_DISTRESSED: -1.6,
    ReliabilityArchetype.FRAUD_ADJACENT: -3.5,
    ReliabilityArchetype.SLOW_BUT_RELIABLE_B2B: 0.9,
}

# β2 — intervention effectiveness varies by (item_type, intervention).
_INTERVENTION_EFFECTIVENESS = {
    (ItemType.PAYMENT_FAILURE, InterventionType.PAYMENT_RETRY): 0.6,
    (ItemType.PAYMENT_FAILURE, InterventionType.WHATSAPP_REMINDER): 0.2,
    (ItemType.PAYMENT_FAILURE, InterventionType.HUMAN_ESCALATION): 0.4,
    (ItemType.B2B_RECEIVABLE, InterventionType.WHATSAPP_REMINDER): 0.3,
    # Human escalation is disproportionately effective for aged B2B debt —
    # this is the interaction the worked example in Part J relies on.
    (ItemType.B2B_RECEIVABLE, InterventionType.HUMAN_ESCALATION): 1.1,
}

# β5 — some failure codes make certain interventions nearly useless.
# `do_not_honor` is a hard decline; retrying it is close to futile.
_FAILURE_CODE_INTERVENTION_INTERACTION = {
    ("do_not_honor", InterventionType.PAYMENT_RETRY): -2.2,
    ("expired_card", InterventionType.PAYMENT_RETRY): -1.8,
    ("insufficient_funds", InterventionType.PAYMENT_RETRY): 0.3,
    ("bank_server_error", InterventionType.PAYMENT_RETRY): 1.2,
    ("issuer_soft_decline", InterventionType.PAYMENT_RETRY): 0.7,
    ("risk_threshold_hold", InterventionType.PAYMENT_RETRY): -0.9,
}

BETA_0 = -0.4  # baseline logit (~40% base recovery before any effects)


def sigmoid(x: float) -> float:
    # Numerically stable sigmoid.
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _f_days_overdue(days_overdue: int) -> float:
    """
    β3 — nonlinear: mild decline early, sharp drop after ~90 days.
    Deliberately nonlinear so a plain linear-features model has to work
    to capture it, and a probability model without interaction terms
    will visibly underperform one that has them (feeds the ablation
    story about *why* a richer model matters, separate from the LLM
    ablation which is about diagnosis, not the probability model).
    """
    if days_overdue <= 0:
        return 0.0
    if days_overdue <= 30:
        return -0.01 * days_overdue
    if days_overdue <= 90:
        return -0.3 - 0.02 * (days_overdue - 30)
    return -1.5 - 0.05 * (days_overdue - 90)


def _f_historical_attempts(historical_attempts: int) -> float:
    """β4 — diminishing returns / fatigue: each additional attempt helps less."""
    if historical_attempts <= 0:
        return 0.0
    return -0.35 * math.log1p(historical_attempts)


def _seasonal_noise(day_of_year: int, seed_material: str) -> float:
    """
    β6 — small deterministic 'seasonal' wobble plus a per-item deterministic
    jitter derived from a hash (so it's reproducible given the same seed
    material, without needing numpy's RNG state).
    """
    seasonal = 0.15 * math.sin(2 * math.pi * day_of_year / 365.0)
    h = int(hashlib.sha256(seed_material.encode()).hexdigest(), 16)
    jitter = ((h % 2000) / 1000.0) - 1.0  # in [-1, 1]
    return seasonal + 0.1 * jitter


@dataclass
class GroundTruthResult:
    p_true: float
    outcome: bool


def compute_p_true(
    *,
    item_type: ItemType,
    intervention: InterventionType,
    reliability_archetype: ReliabilityArchetype,
    days_overdue: int,
    historical_attempts: int,
    failure_code: str | None,
    day_of_year: int,
    noise_seed_material: str,
    rng: random.Random,
) -> float:
    logit = BETA_0
    logit += _ARCHETYPE_EFFECT[reliability_archetype]
    logit += _INTERVENTION_EFFECTIVENESS.get((item_type, intervention), 0.0)
    logit += _f_days_overdue(days_overdue)
    logit += _f_historical_attempts(historical_attempts)
    if failure_code is not None:
        logit += _FAILURE_CODE_INTERVENTION_INTERACTION.get(
            (failure_code, intervention), 0.0
        )
    logit += _seasonal_noise(day_of_year, noise_seed_material)
    # ε — Gaussian noise, small enough not to swamp the structural signal.
    logit += rng.gauss(0.0, 0.35)
    return sigmoid(logit)


def sample_outcome(p_true: float, rng: random.Random) -> bool:
    """outcome ~ Bernoulli(P_true) — NEVER equal to p_true itself."""
    return rng.random() < p_true
