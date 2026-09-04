"""
Policy configuration — RECOVER-ALLOC, Locked spec Part L.
Versioned so every PolicyDecision/AuditEvent can reference exactly which
config produced it, per the spec's requirement that a demo can say
"policy v1.0.0 blocked this" and reproduce the exact same decision later.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyConfig:
    version: str
    min_intervention_amount: float = 100.0
    confidence_escalation_threshold: float = 0.35
    max_contacts_per_week: int = 3
    batch_block_rate_halt_threshold: float = 0.40  # Part L stopping rule


DEFAULT_POLICY_CONFIG = PolicyConfig(version="v1.0.0")
