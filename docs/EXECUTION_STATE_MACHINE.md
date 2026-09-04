# Execution State Machine — Phase 5

```
                    CLAIMED   <-- atomically written by the DB
                       |          UNIQUE(idempotency_key) INSERT,
                       |          BEFORE any external call
          adapter.execute() attempted
                       |
        +--------------+-------------------+
        |              |                   |
  clean, confirmed  ambiguous result   clean, confirmed
  non-side-effecting (timeout,          side-effecting
  failure (e.g.       connection        dispatch occurred
  auth error before   dropped mid-      (adapter call
  any network call)   call, etc.)       returned SOMETHING)
        |                  |                   |
        v                  v                   v
  DISPATCH_FAILED    UNCERTAIN            DISPATCHED
  (safe to retry     (NEVER auto-              |
   under a NEW        retried --          verification step
   idempotency         requires human           |
   key/run)            review)          +-------+-------+
                                         |               |
                                         v               v
                                  VERIFIED_SUCCESS  VERIFIED_FAILED

  idempotency claim loses --> DUPLICATE_EXECUTION_BLOCKED
     (no DB row for this process; the existing row's state is
      reported, but this process never transitions anything)
```

## The invariant that makes this safe

**Once a row is `CLAIMED`, no other process can ever claim the same
`idempotency_key` again** — enforced by a database `UNIQUE` constraint,
not application logic (see `execution/idempotency.py`). All state
transitions FROM `CLAIMED` onward are made exclusively by the process
that won the claim, using its own row's primary key, never by a second
`INSERT`.

## Crash safety — the scenario the spec calls out explicitly

**"Process claims execution, then crashes; external action may or may
not have happened."**

- If the crash happens **before** `adapter.execute()` is even called,
  the row is stuck in `CLAIMED` forever unless a separate reconciliation
  process inspects it. This is **safe to hand to a fresh attempt** —
  nothing was ever sent externally. A reconciliation job can detect a
  `CLAIMED` row older than a configured staleness threshold with no
  `dispatched_at` timestamp and safely re-open it for a new dispatch
  attempt using the SAME row (not a new idempotency key — no external
  action to duplicate).
- If the crash happens **during or after** `adapter.execute()`, whether
  the external side effect actually occurred is **genuinely unknown**
  to this system unless the external system itself provides a
  reconciliation query (e.g., "did payment link X actually get
  created?"). This is why `UNCERTAIN` exists as its own state, distinct
  from a stale `CLAIMED` row: **the system must not pretend to know
  what it does not know, and must never auto-retry an `UNCERTAIN`
  financial action.** An `UNCERTAIN` row requires either (a) a manual
  reconciliation check against the external system's own records, or
  (b) explicit human sign-off to proceed.

This system does **not** claim exactly-once delivery to Razorpay's API.
It claims exactly-once **internal ownership** of an idempotency key, and
honest, auditable uncertainty when the external outcome can't be
confirmed — which is the maximum honest guarantee an internal system can
make without relying on the external API's own idempotency semantics.

## Reconciliation is a deliberately separate, narrow operation

`execution/service.py` intentionally does NOT auto-resolve `UNCERTAIN`
or stale `CLAIMED` rows as part of normal request handling — that logic
lives in a distinct `reconcile_stale_claims()` function, called out of
band (e.g. a periodic job), so the request path itself stays simple and
auditable, and a demo can show a stale claim as a visibly different,
deliberately-not-auto-fixed state.
