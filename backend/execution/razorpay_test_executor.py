"""
RazorpayTestExecutor — RECOVER-ALLOC, Phase 5.

STATUS: SKELETON / ADAPTER INTERFACE ONLY. NOT EXECUTED. NOT CLAIMED TO
WORK. Two independent reasons, both real, neither worked around:

  1. `api.razorpay.com` is not in this sandbox's allowed egress domain
     list (confirmed against the network configuration — only
     api.anthropic.com, api.github.com, and package registries are
     allowed). Even with valid test-mode credentials, this code cannot
     make a real network call from this environment.
  2. No `RAZORPAY_TEST_KEY_ID`/`RAZORPAY_TEST_KEY_SECRET` are configured
     in this build sandbox regardless.

Per the locked spec (Part N), the ONE real integration point is creating
a test-mode Payment Link for a `PAYMENT_RETRY` intervention. The
endpoint used below (`POST /v1/payment_links`) and auth scheme (HTTP
Basic Auth with the test key ID/secret) are taken directly from
Razorpay's own published API documentation cited in the earlier strategy
report — NOT invented here. No endpoint in this file has been guessed.

IMPORTANT IDEMPOTENCY CAVEAT (do not gloss over this): Razorpay's
Payment Links creation API does not document support for a
client-supplied idempotency key. This means retrying a failed/uncertain
`create_payment_link` call CANNOT be made safely idempotent at the
Razorpay API level — this system's own idempotency guarantee (Part 5's
UNIQUE(idempotency_key) on the internal `executions` table) prevents
RECOVER-ALLOC from calling Razorpay MORE THAN ONCE for the same
(run_id, item_id, intervention), but it cannot prevent Razorpay itself
from having silently created a duplicate Payment Link if the response to
a real call was lost in transit (network drop after Razorpay processed
the request but before we received the response). This is exactly the
UNCERTAIN state in the execution state machine, and it is the correct,
honest state for that scenario — NOT an automatic retry.
"""
import os
import time

import requests  # NOTE: not in requirements.txt yet; add before real use

from execution.base import ExecutionOutcome

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"
PAYMENT_LINKS_ENDPOINT = f"{RAZORPAY_API_BASE}/payment_links"
REQUEST_TIMEOUT_SECONDS = 5.0


class RazorpayTestExecutor:
    def __init__(self):
        self.key_id = os.environ.get("RAZORPAY_TEST_KEY_ID")
        self.key_secret = os.environ.get("RAZORPAY_TEST_KEY_SECRET")

    def execute(self, *, item, intervention, idempotency_key: str) -> ExecutionOutcome:
        if not self.key_id or not self.key_secret:
            # Clean, confirmed non-side-effecting failure — no network
            # call was ever attempted, so DISPATCH_FAILED (safe to retry
            # under a fresh attempt) is the correct state, NOT UNCERTAIN.
            return ExecutionOutcome(
                confirmed=True, succeeded=False, external_ref=None,
                detail="Razorpay test credentials not configured; no API call attempted",
            )

        payload = {
            "amount": int(round(float(item.amount) * 100)),  # Razorpay amounts are in paise
            "currency": "INR",
            "description": f"Recovery retry for item {item.id}",
            "reference_id": idempotency_key,  # NOT a documented idempotency mechanism —
            # this is stored purely for our own post-hoc reconciliation
            # lookups, not relied upon to prevent Razorpay-side duplication.
        }

        try:
            response = requests.post(
                PAYMENT_LINKS_ENDPOINT,
                json=payload,
                auth=(self.key_id, self.key_secret),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout:
            # Genuinely ambiguous: request may or may not have reached
            # Razorpay and been processed. Per the state machine, this
            # MUST be UNCERTAIN, never auto-retried.
            return ExecutionOutcome(
                confirmed=False, succeeded=False, external_ref=None,
                detail="Razorpay API call timed out; outcome unknown",
            )
        except requests.exceptions.ConnectionError as exc:
            return ExecutionOutcome(
                confirmed=False, succeeded=False, external_ref=None,
                detail=f"Razorpay API connection error; outcome unknown: {exc}",
            )

        if response.status_code == 200:
            data = response.json()
            return ExecutionOutcome(
                confirmed=True, succeeded=True,
                external_ref=data.get("id"),
                detail="Razorpay test-mode payment link created",
            )

        if response.status_code in (401, 400):
            # Confirmed rejection BEFORE any side effect on Razorpay's
            # side (auth/validation failure) — safe to treat as a clean
            # failure, not uncertain.
            return ExecutionOutcome(
                confirmed=True, succeeded=False, external_ref=None,
                detail=f"Razorpay API rejected request: {response.status_code} {response.text[:200]}",
            )

        # Any other status (5xx, unexpected) is genuinely ambiguous about
        # whether the link was created server-side before the error.
        return ExecutionOutcome(
            confirmed=False, succeeded=False, external_ref=None,
            detail=f"Razorpay API returned unexpected status {response.status_code}; outcome unknown",
        )
