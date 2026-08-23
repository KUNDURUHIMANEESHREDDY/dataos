"""
Critical Invariant Test: Zero Data Fabrication (Rule #1, Rule #48, Rule #73).
The system must fail loudly if an AI claims a computation or fact occurred without real supporting data.
"""

import unittest
import tempfile
import os
import pandas as pd
from core.object.model import DataObject, ObjectType
from infrastructure.storage.sqlite_store import SQLiteStorage
from runtime.grounding.grounder import GroundingEngine, GroundedAssertion
from engines.compute.sql_engine import SQLExecutionEngine
from engines.compute.python_sandbox import PythonSandbox


class TestNoFabricatedResults(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.grounding = GroundingEngine(self.storage)
        self.sql_engine = SQLExecutionEngine(self.storage)
        self.python_sandbox = PythonSandbox(self.storage)

        # Seed real dataset
        self.dataset_obj = DataObject(
            type=ObjectType.DATASET.value,
            schema="dataset.v1",
            properties={"filename": "transactions.csv", "table_name": "transactions"},
            content=[
                {"id": 1, "amount": 100.0, "status": "completed"},
                {"id": 2, "amount": 250.0, "status": "completed"},
                {"id": 3, "amount": 50.0, "status": "failed"},
                {"id": 4, "amount": 400.0, "status": "completed"}
            ],
            source="file://transactions.csv"
        )
        self.storage.save_object(self.dataset_obj)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_grounding_rejects_unsupported_ai_assertions(self):
        """Invariant: Grounding engine MUST reject claims lacking concrete evidence or computation."""
        unsupported_assertion = GroundedAssertion(
            claim="Total revenue for 2026 was $10,000,000",
            evidence=[],  # No evidence provided!
            computations=[],  # No real computation!
            source_object_ids=[]
        )

        with self.assertRaises(ValueError) as ctx:
            self.grounding.ground_response(
                summary_text="Financial summary",
                assertions=[unsupported_assertion]
            )

        self.assertIn("Grounding Violation (Rule #73)", str(ctx.exception))

    def test_grounding_accepts_verified_real_data_assertions(self):
        """Invariant: Grounding engine accepts assertions with verifiable computation on real data."""
        # 1. Run real SQL computation
        sql_res = self.sql_engine.execute_sql("SELECT SUM(amount) as total_completed FROM transactions WHERE status = 'completed';")
        self.assertTrue(sql_res["success"])
        real_sum = sql_res["rows"][0]["total_completed"]
        self.assertEqual(real_sum, 750.0)  # 100 + 250 + 400

        # 2. Build verified assertion
        verified_assertion = GroundedAssertion(
            claim="Total completed transaction amount is $750.0",
            evidence=[{"source_id": self.dataset_obj.id, "row_count": 4}],
            computations=[sql_res],
            source_object_ids=[self.dataset_obj.id]
        )

        grounded_record = self.grounding.ground_response(
            summary_text="Transaction analysis report",
            assertions=[verified_assertion]
        )

        self.assertEqual(grounded_record["status"], "VERIFIED_GROUNDED")
        self.assertEqual(grounded_record["assertion_count"], 1)
        self.assertTrue(grounded_record["provenance"]["zero_fabrication_checked"])

    def test_python_sandbox_computes_real_data_deterministically(self):
        """Invariant: Python sandbox executes against loaded DataObjects without simulation."""
        code = """
df = dfs['transactions']
completed_df = df[df['status'] == 'completed']
results['mean_completed_amount'] = float(completed_df['amount'].mean())
results['count_completed'] = int(len(completed_df))
"""
        exec_res = self.python_sandbox.execute_code(code, input_object_ids=[self.dataset_obj.id])
        self.assertTrue(exec_res["success"])
        
        # Verify mathematically: (100 + 250 + 400) / 3 = 250.0
        self.assertEqual(exec_res["results"]["mean_completed_amount"], 250.0)
        self.assertEqual(exec_res["results"]["count_completed"], 3)


if __name__ == "__main__":
    unittest.main()
