"""
API Endpoint Unit Tests — RECOVER-ALLOC Phase 8.
Tests all FastAPI endpoints using TestClient.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


class TestAPIEndpoints(unittest.TestCase):
    def test_health_endpoint(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["ortools_installed"])

    def test_dashboard_summary_endpoint(self):
        response = client.get("/dashboard/summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_revenue_at_risk", data)
        self.assertIn("recoverable_expected_objective", data)
        self.assertIn("resource_utilization_percent", data)
        self.assertGreater(data["n_items"], 0)

    def test_recovery_items_endpoint(self):
        response = client.get("/recovery/items?limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 10)
        item = data["items"][0]
        self.assertIn("amount", item)
        self.assertIn("policy_status", item)

    def test_recovery_plan_endpoint(self):
        payload = {"n_items": 20, "retry_slots": 10, "whatsapp_quota": 10, "human_hours": 2}
        response = client.post("/recovery/plan", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("run_id", data)
        self.assertIn("expected_objective", data)
        self.assertIn("compare_naive", data)
        self.assertGreater(len(data["allocations"]), 0)

    def test_recovery_execute_endpoint(self):
        plan_res = client.post("/recovery/plan", json={"n_items": 10})
        plan_data = plan_res.json()
        alloc = plan_data["allocations"][0]

        exec_payload = {
            "run_id": plan_data["run_id"],
            "allocation_id": alloc["allocation_id"],
            "item_id": alloc["item_id"],
            "intervention": alloc["chosen_intervention"] or "PAYMENT_RETRY",
            "adapter_type": "simulator",
        }
        response = client.post("/recovery/execute", json=exec_payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)

    def test_duplicate_execution_scenario(self):
        plan_res = client.post("/recovery/plan", json={"n_items": 10})
        plan_data = plan_res.json()
        alloc = plan_data["allocations"][0]

        exec_payload = {
            "run_id": plan_data["run_id"],
            "allocation_id": alloc["allocation_id"],
            "item_id": alloc["item_id"],
            "intervention": alloc["chosen_intervention"] or "PAYMENT_RETRY",
            "adapter_type": "simulator",
            "failure_scenario": "duplicate",
        }
        response = client.post("/recovery/execute", json=exec_payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["first_execution"]["status"], "EXECUTED")
        self.assertEqual(data["second_execution_duplicate"]["status"], "DUPLICATE_BLOCKED")

    def test_audit_events_endpoint(self):
        response = client.get("/audit/events")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("audit_events", data)

    def test_evaluation_summary_endpoint(self):
        response = client.get("/evaluation/summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("verified_benchmarks", data)

    def test_evaluation_compare_endpoint(self):
        response = client.get("/evaluation/compare")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("counterexample_proof", data)
        self.assertEqual(data["counterexample_proof"]["naive_greedy_objective"], 24845.50)


if __name__ == "__main__":
    unittest.main()
