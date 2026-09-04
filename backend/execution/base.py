"""
ExecutorAdapter interface — RECOVER-ALLOC, Phase 5.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExecutionOutcome:
    """
    `confirmed` distinguishes a definite result (success or failure) from
    an ambiguous one (timeout / unknown) — the execution service uses
    this, NOT just success/failure, to decide between DISPATCHED->
    VERIFIED_* and DISPATCHED->UNCERTAIN.
    """
    confirmed: bool
    succeeded: bool  # meaningless if confirmed=False
    external_ref: str | None
    detail: str


class ExecutorAdapter(Protocol):
    def execute(self, *, item, intervention, idempotency_key: str) -> ExecutionOutcome:
        ...
