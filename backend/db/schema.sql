-- RECOVER-ALLOC database schema — Locked spec Part E.
-- Target: PostgreSQL 15.
-- MIGRATION HISTORY: db/migrations/0001_initial_schema.sql (Phase 1) +
-- db/migrations/0002_execution_state_machine.sql (Phase 5). This file
-- represents the CUMULATIVE current schema for convenience (used by
-- docker-compose's init-on-first-boot mount); db/migrations/ is the
-- authoritative history. Do not hand-edit this file's executions table
-- shape again without also writing a new numbered migration — see
-- Phase 5 report for why this rule exists (Alembic itself is not
-- installed in this build sandbox, so these are hand-written SQL
-- migrations rather than Alembic-generated ones; wire up real Alembic
-- once the package is installable).
-- NOTE: this file has NOT been run against a live Postgres instance in this
-- sandbox (no Postgres/Docker available here — see Phase 1 report). It has
-- been checked for structural completeness against Part E by an automated
-- stdlib script (tests/test_schema_structure.py) that parses this file's
-- CREATE TABLE statements and asserts every table/column/constraint named
-- in the spec is present. Run `make db-up && make db-migrate` in a real
-- environment for a genuine execution check.

CREATE TABLE merchants (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    recovery_policy_tier TEXT NOT NULL DEFAULT 'standard'
);

CREATE TABLE customers (
    id              TEXT PRIMARY KEY,
    merchant_id     TEXT NOT NULL REFERENCES merchants(id),
    consent_whatsapp BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE recoverable_items (
    id                  TEXT PRIMARY KEY,
    type                TEXT NOT NULL CHECK (type IN ('PAYMENT_FAILURE','B2B_RECEIVABLE')),
    merchant_id         TEXT NOT NULL REFERENCES merchants(id),
    customer_id         TEXT NOT NULL REFERENCES customers(id),
    amount              NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    currency            TEXT NOT NULL DEFAULT 'INR',
    created_at          TIMESTAMPTZ NOT NULL,
    due_at              TIMESTAMPTZ,
    days_overdue        INT NOT NULL DEFAULT 0,
    payment_method      TEXT,
    failure_code        TEXT,
    historical_attempts INT NOT NULL DEFAULT 0,
    contact_count_7d    INT NOT NULL DEFAULT 0,
    evidence_text       TEXT NOT NULL,
    risk_flags          JSONB NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'PENDING',
    UNIQUE (id)
);
CREATE INDEX idx_items_status ON recoverable_items(status);
CREATE INDEX idx_items_merchant ON recoverable_items(merchant_id);

CREATE TABLE model_predictions (
    id              TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL REFERENCES recoverable_items(id),
    intervention    TEXT NOT NULL,
    p_recover       NUMERIC(6,5) NOT NULL,
    model_version   TEXT NOT NULL,
    diagnosis_source TEXT NOT NULL CHECK (diagnosis_source IN ('llm','rule_table')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (item_id, intervention, diagnosis_source, model_version)
);

CREATE TABLE allocations (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    item_id             TEXT NOT NULL REFERENCES recoverable_items(id),
    intervention        TEXT,
    expected_net_value  NUMERIC(12,2) NOT NULL,
    solver_status       TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, item_id)
);

CREATE TABLE policies (
    version         TEXT PRIMARY KEY,
    config_json     JSONB NOT NULL,
    activated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE executions (
    id                  TEXT PRIMARY KEY,
    idempotency_key     TEXT NOT NULL UNIQUE,
    allocation_id       TEXT NOT NULL REFERENCES allocations(id),
    item_id             TEXT NOT NULL REFERENCES recoverable_items(id),
    intervention        TEXT NOT NULL,
    executor_adapter    TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN (
                            'CLAIMED', 'DISPATCHED',
                            'VERIFIED_SUCCESS', 'VERIFIED_FAILED',
                            'DISPATCH_FAILED', 'UNCERTAIN'
                        )),
    external_ref        TEXT,
    requested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at          TIMESTAMPTZ,
    dispatched_at       TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ
);
CREATE INDEX idx_executions_status ON executions(status);
CREATE INDEX idx_executions_allocation ON executions(allocation_id);

CREATE TABLE audit_events (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT,
    item_id             TEXT,
    event_type          TEXT NOT NULL,
    payload             JSONB NOT NULL,
    model_version       TEXT,
    policy_version      TEXT,
    optimizer_run_id    TEXT,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason              TEXT,
    result              TEXT
);
CREATE INDEX idx_audit_run ON audit_events(run_id);
CREATE INDEX idx_audit_item ON audit_events(item_id);
-- audit_events is APPEND-ONLY: REVOKE UPDATE/DELETE from the app role at
-- deploy time, e.g.:
--   REVOKE UPDATE, DELETE ON audit_events FROM recover_alloc_app;

CREATE TABLE evaluation_runs (
    id              TEXT PRIMARY KEY,
    strategy        TEXT NOT NULL,
    test_set_hash   TEXT NOT NULL,
    metrics_json    JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
