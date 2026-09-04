"""
Synthetic data generator — RECOVER-ALLOC, Locked spec Part G.

Produces 1,200 RecoverableItems (60% PAYMENT_FAILURE, 40% B2B_RECEIVABLE)
across 3 merchant archetypes, with correlated bank-outage failure bursts,
fraud-adjacent adversarial cases, and noisy/contradictory evidence text.

Uses only Python stdlib (`random`, `math`) — no numpy — because this
sandbox has no package-install access. `random.lognormvariate` is stdlib
and gives the same log-normal amount distribution the spec calls for.
"""
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from domain.enums import ItemType, InterventionType
from domain.models_stdlib_mirror import RecoverableItem
from simulation.ground_truth import (
    ReliabilityArchetype,
    compute_p_true,
    sample_outcome,
    sample_true_diagnostic_class,
)

SEED = 20260901  # fixed, checked into the repo per Part H freeze procedure

MERCHANTS = [
    {"id": "merchant_d2c_sub", "name": "D2C Subscription Co", "tier": "standard", "leak_bias": "payment"},
    {"id": "merchant_b2b_saas", "name": "B2B SaaS Co", "tier": "strict", "leak_bias": "receivable"},
    {"id": "merchant_marketplace", "name": "Marketplace Co", "tier": "lenient", "leak_bias": "mixed"},
]

FAILURE_CODE_WEIGHTS = [
    ("insufficient_funds", 0.30),
    ("issuer_soft_decline", 0.25),
    ("bank_server_error", 0.15),
    ("risk_threshold_hold", 0.10),
    ("expired_card", 0.10),
    ("do_not_honor", 0.10),
]

ARCHETYPE_WEIGHTS = [
    (ReliabilityArchetype.CHRONIC_GOOD_PAYER_GLITCH, 0.35),
    (ReliabilityArchetype.GENUINELY_DISTRESSED, 0.35),
    (ReliabilityArchetype.FRAUD_ADJACENT, 0.05),
    (ReliabilityArchetype.SLOW_BUT_RELIABLE_B2B, 0.25),
]

EVIDENCE_TEMPLATES_PAYMENT = [
    "Issuer note: {failure_code} reported on attempt #{attempt}. Customer contacted support on {date}.",
    "Support log: customer states card should be valid, {failure_code} decline reason from issuer unclear.",
    "Automated retry log: {failure_code}, no customer contact yet.",
    "Support ticket #{ticket}: customer confirmed card issue, but account flagged for review previously.",
]

EVIDENCE_TEMPLATES_RECEIVABLE = [
    "Collections note: invoice {days_overdue} days overdue, client requested extension via email on {date}.",
    "AR note: client cited cashflow delay, previously always paid within terms.",
    "Collections call summary: no response after 3 attempts, email bounced once.",
    "AR note: client disputes invoice amount, escalation may be required.",
]


def _weighted_choice(rng: random.Random, weighted: list[tuple]):
    total = sum(w for _, w in weighted)
    r = rng.uniform(0, total)
    upto = 0.0
    for item, w in weighted:
        upto += w
        if upto >= r:
            return item
    return weighted[-1][0]


@dataclass
class GeneratedItemBundle:
    """
    Internal generator-only wrapper. `hidden_archetype`, `p_true_by_intervention`,
    `sampled_outcome_by_intervention`, and `true_diagnostic_class` are the
    ground truth — they are written ONLY to test_set_ground_truth.jsonl,
    never to the RecoverableItem itself and never to any file the
    model/LLM/app code reads.
    """
    item: RecoverableItem
    hidden_archetype: ReliabilityArchetype
    p_true_by_intervention: dict
    sampled_outcome_by_intervention: dict
    true_diagnostic_class: str


def _valid_interventions(item_type: ItemType) -> list[InterventionType]:
    if item_type == ItemType.PAYMENT_FAILURE:
        return [InterventionType.PAYMENT_RETRY, InterventionType.WHATSAPP_REMINDER, InterventionType.HUMAN_ESCALATION]
    return [InterventionType.WHATSAPP_REMINDER, InterventionType.HUMAN_ESCALATION]


def generate_pool(n_total: int = 1200, seed: int = SEED) -> list[GeneratedItemBundle]:
    rng = random.Random(seed)
    n_payment = round(n_total * 0.60)
    n_receivable = n_total - n_payment

    bundles: list[GeneratedItemBundle] = []
    base_date = datetime(2026, 6, 1)

    # --- correlated bank-outage window: a burst of bank_server_error items
    # sharing one synthetic issuer BIN prefix, clustered in one 6h window ---
    outage_start = base_date + timedelta(days=rng.randint(5, 40), hours=rng.randint(0, 18))
    outage_bin_prefix = "417834"
    n_outage_items = max(1, round(n_payment * 0.08))

    for idx in range(n_total):
        is_outage_item = idx < n_outage_items
        item_type = ItemType.PAYMENT_FAILURE if idx < n_payment else ItemType.B2B_RECEIVABLE
        merchant = _weighted_choice(rng, [(m, 1.0) for m in MERCHANTS])
        archetype = _weighted_choice(rng, ARCHETYPE_WEIGHTS)

        # ~3% adversarial fraud-suspect cases, deliberately high amount
        is_fraud_suspect = rng.random() < 0.03
        if is_fraud_suspect:
            archetype = ReliabilityArchetype.FRAUD_ADJACENT

        customer_id = f"cust_{idx:05d}"
        item_id = f"item_{idx:05d}"

        if item_type == ItemType.PAYMENT_FAILURE:
            amount = round(rng.lognormvariate(mu=7.5, sigma=1.0), 2)
            amount = max(150.0, min(amount, 85000.0))
            if is_fraud_suspect:
                amount = round(rng.uniform(40000, 85000), 2)  # tempting to a naive optimizer

            if is_outage_item:
                failure_code = "bank_server_error"
                created_at = outage_start + timedelta(minutes=rng.randint(0, 360))
                payment_method = "card"
            else:
                failure_code = _weighted_choice(rng, FAILURE_CODE_WEIGHTS)
                created_at = base_date + timedelta(days=rng.randint(0, 80), hours=rng.randint(0, 23))
                payment_method = rng.choice(["card", "upi", "netbanking", "wallet"])

            days_overdue = 0
            due_at = None
            historical_attempts = rng.choices([0, 1, 2], weights=[0.6, 0.3, 0.1])[0]
            template = rng.choice(EVIDENCE_TEMPLATES_PAYMENT)
            evidence_text = template.format(
                failure_code=failure_code,
                attempt=historical_attempts + 1,
                date=created_at.strftime("%Y-%m-%d"),
                ticket=rng.randint(10000, 99999),
            )
            # Contradictory-evidence injection: for a chunk of fraud-adjacent
            # items, the support note reads as sympathetic/legitimate even
            # though the hidden archetype says otherwise — this is what a
            # rule table (keyed only on failure_code) cannot see, and what
            # the LLM-vs-rule-table ablation is designed to test.
            if is_fraud_suspect and rng.random() < 0.5:
                evidence_text += " Customer was polite and confirmed billing details matched exactly."

        else:  # B2B_RECEIVABLE
            amount = round(rng.lognormvariate(mu=10.5, sigma=1.1), 2)
            amount = max(8000.0, min(amount, 600000.0))
            failure_code = None
            payment_method = None
            created_at = base_date + timedelta(days=rng.randint(0, 60))
            aging_bucket = rng.choices(["routine", "at_risk", "near_writeoff"], weights=[0.65, 0.28, 0.07])[0]
            if aging_bucket == "routine":
                days_overdue = rng.randint(1, 30)
            elif aging_bucket == "at_risk":
                days_overdue = rng.randint(60, 120)
            else:
                days_overdue = rng.randint(150, 210)
            due_at = created_at + timedelta(days=days_overdue)
            historical_attempts = rng.choices([0, 1, 2, 3], weights=[0.4, 0.3, 0.2, 0.1])[0]
            template = rng.choice(EVIDENCE_TEMPLATES_RECEIVABLE)
            evidence_text = template.format(
                days_overdue=days_overdue,
                date=(created_at + timedelta(days=days_overdue)).strftime("%Y-%m-%d"),
            )

        risk_flags = ["fraud_suspect"] if is_fraud_suspect else []
        contact_count_7d = rng.choices([0, 1, 2, 3], weights=[0.5, 0.3, 0.15, 0.05])[0]

        item = RecoverableItem(
            id=item_id,
            type=item_type,
            merchant_id=merchant["id"],
            customer_id=customer_id,
            amount=amount,
            created_at=created_at,
            due_at=due_at,
            days_overdue=days_overdue,
            payment_method=payment_method,
            failure_code=failure_code,
            historical_attempts=historical_attempts,
            contact_count_7d=contact_count_7d,
            evidence_text=evidence_text,
            risk_flags=risk_flags,
            merchant_recovery_policy_tier=merchant["tier"],
        )

        p_true_by_intervention = {}
        outcome_by_intervention = {}
        for interv in _valid_interventions(item_type):
            item_rng = random.Random(f"{seed}:{item_id}:{interv.value}")
            p_true = compute_p_true(
                item_type=item_type,
                intervention=interv,
                reliability_archetype=archetype,
                days_overdue=days_overdue,
                historical_attempts=historical_attempts,
                failure_code=failure_code,
                day_of_year=created_at.timetuple().tm_yday,
                noise_seed_material=f"{item_id}:{interv.value}",
                rng=item_rng,
            )
            outcome = sample_outcome(p_true, item_rng)
            p_true_by_intervention[interv.value] = round(p_true, 5)
            outcome_by_intervention[interv.value] = outcome

        # Independent hidden diagnostic-truth label (Phase 7) — derived
        # from the archetype directly, via its own RNG stream, NEVER
        # from failure_code/days_overdue (that would make it tautological
        # against the rule diagnoser's own bucketing, exactly the flaw
        # found and disclosed in docs/LLM_ABLATION.md).
        true_class_rng = random.Random(f"{seed}:{item_id}:true_diagnostic_class")
        true_diagnostic_class = sample_true_diagnostic_class(archetype, true_class_rng)

        bundles.append(
            GeneratedItemBundle(
                item=item,
                hidden_archetype=archetype,
                p_true_by_intervention=p_true_by_intervention,
                sampled_outcome_by_intervention=outcome_by_intervention,
                true_diagnostic_class=true_diagnostic_class,
            )
        )

    rng.shuffle(bundles)
    return bundles


def split_pool(
    bundles: list[GeneratedItemBundle],
) -> tuple[list[GeneratedItemBundle], list[GeneratedItemBundle], list[GeneratedItemBundle]]:
    """
    Stratified 700/200/300 split by item type, per Part H freeze procedure.
    Stratification keeps the 60/40 PAYMENT_FAILURE/B2B_RECEIVABLE ratio
    consistent across train/val/test rather than letting the shuffle
    accidentally skew one split.
    """
    payment = [b for b in bundles if b.item.type == ItemType.PAYMENT_FAILURE]
    receivable = [b for b in bundles if b.item.type == ItemType.B2B_RECEIVABLE]

    def split_group(group, n_train, n_val, n_test):
        return group[:n_train], group[n_train:n_train + n_val], group[n_train + n_val:n_train + n_val + n_test]

    # 700/200/300 overall, at a 60/40 type ratio => payment: 420/120/180, receivable: 280/80/120
    p_train, p_val, p_test = split_group(payment, 420, 120, 180)
    r_train, r_val, r_test = split_group(receivable, 280, 80, 120)

    train = p_train + r_train
    val = p_val + r_val
    test = p_test + r_test
    return train, val, test
