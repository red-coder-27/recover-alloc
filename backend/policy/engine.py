"""
Deterministic policy engine — RECOVER-ALLOC, Locked spec Part L.

Evaluated AFTER the optimizer, BEFORE the executor, for every non-null
allocation. Rules run in FIXED ORDER; the first rule to fire determines
the outcome — no rule stacking/overriding ambiguity, per the spec.

    1. fraud flag                          -> BLOCK
    2. low diagnosis confidence             -> ESCALATE
    3. below monetary floor                 -> BLOCK
    4. unmet intervention requirements      -> MODIFY (one re-entry max)
    5. frequency ceiling reached            -> BLOCK
    6. contact-fatigue ceiling reached      -> BLOCK
    7. otherwise                            -> ALLOW

A BLOCKED or ESCALATED allocation must NEVER reach the executor — that
invariant is enforced by strategies/recover_alloc.py's control flow
(only ALLOW-outcome allocations are passed to the executor at all), and
is independently tested in tests/test_policy_engine.py via an
integration-style check on the full decision list, not just per-rule
unit tests.
"""
from dataclasses import dataclass

from domain.enums import InterventionType, ItemType, PolicyOutcome
from policy.config import PolicyConfig, DEFAULT_POLICY_CONFIG


@dataclass
class PolicyDecision:
    item_id: str
    outcome: PolicyOutcome
    reason: str
    policy_version: str
    original_intervention: InterventionType | None
    final_intervention: InterventionType | None  # differs from original only on MODIFY


def evaluate_policy(
    *,
    item,  # RecoverableItem-shaped: .amount, .risk_flags, .historical_attempts, .contact_count_7d
    intervention: InterventionType | None,
    diagnosis,  # Diagnosis-shaped: .confidence
    interventions_catalog: dict,
    consent_on_file: bool = True,
    config: PolicyConfig = DEFAULT_POLICY_CONFIG,
    _is_reentry: bool = False,
) -> PolicyDecision:
    """
    Evaluates a single proposed (item, intervention) allocation against
    the fixed-order rule list. `_is_reentry` guards the MODIFY rule's
    single re-evaluation per Part L ("max one re-entry to prevent
    loops") — external callers should never pass this explicitly.
    """
    if intervention is None:
        return PolicyDecision(
            item_id=item.id, outcome=PolicyOutcome.ALLOW,
            reason="no intervention proposed (unserved item, not a policy matter)",
            policy_version=config.version, original_intervention=None, final_intervention=None,
        )

    # Rule 1: fraud flag -> BLOCK
    if "fraud_suspect" in getattr(item, "risk_flags", []):
        return PolicyDecision(
            item_id=item.id, outcome=PolicyOutcome.BLOCK,
            reason="fraud flag present, no automated intervention permitted",
            policy_version=config.version, original_intervention=intervention, final_intervention=None,
        )

    # Rule 2: low diagnosis confidence -> ESCALATE
    if diagnosis.confidence < config.confidence_escalation_threshold:
        return PolicyDecision(
            item_id=item.id, outcome=PolicyOutcome.ESCALATE,
            reason=f"diagnosis confidence {diagnosis.confidence:.2f} below threshold "
                   f"{config.confidence_escalation_threshold:.2f}, human review required",
            policy_version=config.version, original_intervention=intervention, final_intervention=None,
        )

    # Rule 3: below monetary floor -> BLOCK
    if float(item.amount) < config.min_intervention_amount:
        return PolicyDecision(
            item_id=item.id, outcome=PolicyOutcome.BLOCK,
            reason=f"amount {item.amount} below monetary floor {config.min_intervention_amount}",
            policy_version=config.version, original_intervention=intervention, final_intervention=None,
        )

    catalog_entry = interventions_catalog[intervention]

    # Rule 4: unmet intervention requirements -> MODIFY (max one re-entry)
    if "consent_on_file" in catalog_entry.policy_requirements and not consent_on_file:
        if _is_reentry:
            # Already tried a downgrade once; no further alternative -> ESCALATE.
            return PolicyDecision(
                item_id=item.id, outcome=PolicyOutcome.ESCALATE,
                reason="no valid alternative intervention after MODIFY re-entry; consent still unmet",
                policy_version=config.version, original_intervention=intervention, final_intervention=None,
            )
        alternative = _next_best_alternative(item, intervention, interventions_catalog)
        if alternative is None:
            return PolicyDecision(
                item_id=item.id, outcome=PolicyOutcome.ESCALATE,
                reason="consent not on file and no valid alternative intervention exists",
                policy_version=config.version, original_intervention=intervention, final_intervention=None,
            )
        # Re-run the FULL rule chain against the alternative exactly once.
        reentry_decision = evaluate_policy(
            item=item, intervention=alternative, diagnosis=diagnosis,
            interventions_catalog=interventions_catalog, consent_on_file=consent_on_file,
            config=config, _is_reentry=True,
        )
        if reentry_decision.outcome == PolicyOutcome.ALLOW:
            return PolicyDecision(
                item_id=item.id, outcome=PolicyOutcome.MODIFY,
                reason=f"downgraded from {intervention.value} to {alternative.value} "
                       f"(consent not on file for original)",
                policy_version=config.version, original_intervention=intervention,
                final_intervention=alternative,
            )
        return reentry_decision

    # Rule 5: frequency ceiling reached -> BLOCK
    if item.historical_attempts >= catalog_entry.max_frequency_per_item:
        return PolicyDecision(
            item_id=item.id, outcome=PolicyOutcome.BLOCK,
            reason=f"historical_attempts={item.historical_attempts} >= "
                   f"max_frequency_per_item={catalog_entry.max_frequency_per_item}",
            policy_version=config.version, original_intervention=intervention, final_intervention=None,
        )

    # Rule 6: contact-fatigue ceiling reached -> BLOCK (contact-based interventions only)
    if intervention in (InterventionType.WHATSAPP_REMINDER, InterventionType.HUMAN_ESCALATION):
        if item.contact_count_7d >= config.max_contacts_per_week:
            return PolicyDecision(
                item_id=item.id, outcome=PolicyOutcome.BLOCK,
                reason=f"contact_count_7d={item.contact_count_7d} >= {config.max_contacts_per_week}",
                policy_version=config.version, original_intervention=intervention, final_intervention=None,
            )

    # Rule 7: otherwise -> ALLOW
    return PolicyDecision(
        item_id=item.id, outcome=PolicyOutcome.ALLOW,
        reason="all policy checks passed",
        policy_version=config.version, original_intervention=intervention, final_intervention=intervention,
    )


def _next_best_alternative(item, original: InterventionType, interventions_catalog: dict) -> InterventionType | None:
    """
    Minimal, deterministic fallback ladder for the MODIFY rule.

    HUMAN_ESCALATION is preferred as the fallback target whenever it's
    valid for the item's type: a consent failure on a contact-based
    intervention (WhatsApp) means "we cannot safely message this
    customer," which is a reason to get a human involved, not a reason
    to silently pivot to an unrelated action like retrying a payment.
    PAYMENT_RETRY is only offered as a fallback for item types where
    HUMAN_ESCALATION isn't a valid option at all (not currently possible
    given Part D's catalog, but kept as a documented, deliberate
    ordering rather than an accident of iteration order over
    VALID_INTERVENTIONS_BY_ITEM_TYPE's tuple).
    """
    from domain.enums import VALID_INTERVENTIONS_BY_ITEM_TYPE

    valid = VALID_INTERVENTIONS_BY_ITEM_TYPE.get(item.type, ())
    preference_order = [InterventionType.HUMAN_ESCALATION, InterventionType.PAYMENT_RETRY, InterventionType.WHATSAPP_REMINDER]
    for candidate in preference_order:
        if candidate == original or candidate not in valid:
            continue
        if "consent_on_file" not in interventions_catalog[candidate].policy_requirements:
            return candidate
    return None


def batch_block_rate_exceeded(decisions: list[PolicyDecision], config: PolicyConfig = DEFAULT_POLICY_CONFIG) -> bool:
    """
    Part L batch-level stopping rule: if BLOCK outcomes exceed the
    configured threshold of the batch, the caller (strategies/
    recover_alloc.py) must halt further execution for the run and raise
    a RUN_HALTED_POLICY_ANOMALY audit event, rather than blocking most of
    a batch one item at a time silently.
    """
    if not decisions:
        return False
    n_blocked = sum(1 for d in decisions if d.outcome == PolicyOutcome.BLOCK)
    return (n_blocked / len(decisions)) > config.batch_block_rate_halt_threshold
