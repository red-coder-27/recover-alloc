"""
SimulatorExecutor — RECOVER-ALLOC, Phase 5.

DETERMINISTIC by design: given the same (item_id, intervention,
idempotency_key), always produces the same behavior. This is what makes
the demo reproducible instead of flaky.

Behavior is selected by hashing the idempotency_key into one of four
buckets (success / recoverable_failure / timeout / invalid_response),
weighted so success is the common case. An explicit `forced_behavior`
override is accepted for tests that need a SPECIFIC scenario on demand.
"""
import hashlib
from enum import Enum

from execution.base import ExecutionOutcome

_BEHAVIOR_WEIGHTS = [
    ("success", 70),
    ("recoverable_failure", 15),
    ("timeout", 10),
    ("invalid_response", 5),
]


class SimulatedBehavior(str, Enum):
    SUCCESS = "success"
    RECOVERABLE_FAILURE = "recoverable_failure"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"


def _deterministic_behavior(idempotency_key: str) -> str:
    h = int(hashlib.sha256(idempotency_key.encode()).hexdigest(), 16)
    total = sum(w for _, w in _BEHAVIOR_WEIGHTS)
    bucket = h % total
    cumulative = 0
    for name, weight in _BEHAVIOR_WEIGHTS:
        cumulative += weight
        if bucket < cumulative:
            return name
    return _BEHAVIOR_WEIGHTS[-1][0]


class SimulatorExecutor:
    def __init__(self, forced_behavior: str | None = None):
        self.forced_behavior = forced_behavior

    def execute(self, *, item, intervention, idempotency_key: str) -> ExecutionOutcome:
        behavior = self.forced_behavior or _deterministic_behavior(idempotency_key)

        if behavior == SimulatedBehavior.SUCCESS.value:
            return ExecutionOutcome(
                confirmed=True, succeeded=True,
                external_ref=f"sim_{idempotency_key[:12]}",
                detail="simulated dispatch succeeded",
            )
        if behavior == SimulatedBehavior.RECOVERABLE_FAILURE.value:
            return ExecutionOutcome(
                confirmed=True, succeeded=False,
                external_ref=None,
                detail="simulated dispatch executed but did not recover the item",
            )
        if behavior == SimulatedBehavior.TIMEOUT.value:
            return ExecutionOutcome(
                confirmed=False, succeeded=False,
                external_ref=None,
                detail="simulated timeout - outcome unknown, do not assume success or failure",
            )
        if behavior == SimulatedBehavior.INVALID_RESPONSE.value:
            return ExecutionOutcome(
                confirmed=False, succeeded=False,
                external_ref=None,
                detail="simulated malformed/invalid response from downstream system",
            )
        raise ValueError(f"unknown simulated behavior: {behavior}")
