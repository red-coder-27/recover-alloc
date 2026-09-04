"""
Structural verification of db/schema.sql WITHOUT a live Postgres instance.

This does NOT prove the SQL executes correctly against real Postgres (there
is no Postgres available in this sandbox — see the Phase 1 report). What it
DOES prove, right now, with zero dependencies: every table, primary key,
foreign key, unique constraint, and index required by the locked spec
(Part E) is actually present in the file, by name, so the schema can't
silently drift from the spec between now and when someone runs it for real.

Real execution check (run in an environment with Postgres/Docker):
    docker compose up -d db
    psql $DATABASE_URL -f backend/db/schema.sql
"""
import os
import re
import unittest

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")

REQUIRED_TABLES = [
    "merchants",
    "customers",
    "recoverable_items",
    "model_predictions",
    "allocations",
    "policies",
    "executions",
    "audit_events",
    "evaluation_runs",
]

REQUIRED_UNIQUE_CONSTRAINTS = [
    # (table, what makes it unique - checked as substring presence near the table block)
    ("model_predictions", "UNIQUE (item_id, intervention, diagnosis_source, model_version)"),
    ("allocations", "UNIQUE (run_id, item_id)"),
    ("executions", "idempotency_key     TEXT NOT NULL UNIQUE"),
]

REQUIRED_INDEXES = [
    "idx_items_status",
    "idx_items_merchant",
    "idx_audit_run",
    "idx_audit_item",
    "idx_executions_status",
    "idx_executions_allocation",
]

REQUIRED_FOREIGN_KEYS = [
    ("customers", "REFERENCES merchants(id)"),
    ("recoverable_items", "REFERENCES merchants(id)"),
    ("recoverable_items", "REFERENCES customers(id)"),
    ("model_predictions", "REFERENCES recoverable_items(id)"),
    ("allocations", "REFERENCES recoverable_items(id)"),
    ("executions", "REFERENCES allocations(id)"),
    ("executions", "REFERENCES recoverable_items(id)"),
]


class TestSchemaStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SCHEMA_PATH, "r") as f:
            cls.sql = f.read()
        # Split into per-table blocks for scoped checks.
        cls.table_blocks = {}
        for table in REQUIRED_TABLES:
            match = re.search(
                rf"CREATE TABLE {table} \((.*?)\n\);", cls.sql, re.DOTALL
            )
            cls.table_blocks[table] = match.group(1) if match else ""

    def test_all_required_tables_present(self):
        for table in REQUIRED_TABLES:
            self.assertIn(
                f"CREATE TABLE {table}", self.sql, f"missing table: {table}"
            )

    def test_all_tables_have_a_block_body(self):
        for table, block in self.table_blocks.items():
            self.assertTrue(block.strip(), f"table {table} block not parsed/empty")

    def test_recoverable_items_type_check_constraint(self):
        block = self.table_blocks["recoverable_items"]
        self.assertIn("CHECK (type IN ('PAYMENT_FAILURE','B2B_RECEIVABLE'))", block)

    def test_recoverable_items_amount_nonnegative_check(self):
        block = self.table_blocks["recoverable_items"]
        self.assertIn("CHECK (amount >= 0)", block)

    def test_executions_status_check_constraint(self):
        block = self.table_blocks["executions"]
        self.assertIn(
            "CHECK (status IN (", block
        )
        for state in ["CLAIMED", "DISPATCHED", "VERIFIED_SUCCESS", "VERIFIED_FAILED", "DISPATCH_FAILED", "UNCERTAIN"]:
            self.assertIn(f"'{state}'", block, f"executions status check missing state: {state}")

    def test_required_unique_constraints_present(self):
        for table, fragment in REQUIRED_UNIQUE_CONSTRAINTS:
            self.assertIn(
                fragment,
                self.table_blocks[table],
                f"missing unique constraint in {table}: {fragment}",
            )

    def test_required_indexes_present(self):
        for index_name in REQUIRED_INDEXES:
            self.assertIn(f"CREATE INDEX {index_name}", self.sql)

    def test_required_foreign_keys_present(self):
        for table, fragment in REQUIRED_FOREIGN_KEYS:
            self.assertIn(
                fragment,
                self.table_blocks[table],
                f"missing FK in {table}: {fragment}",
            )

    def test_audit_events_append_only_comment_present(self):
        # We can't REVOKE against a live DB here, but the deploy-time
        # instruction must exist in the file so it isn't forgotten.
        self.assertIn("APPEND-ONLY", self.sql)
        self.assertIn("REVOKE UPDATE, DELETE ON audit_events", self.sql)

    def test_every_table_has_a_primary_key(self):
        for table, block in self.table_blocks.items():
            has_pk = "PRIMARY KEY" in block
            self.assertTrue(has_pk, f"table {table} has no PRIMARY KEY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
