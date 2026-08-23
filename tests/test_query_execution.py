"""
Tests for Unified Query Engine (Phase 6).
Verifies SQL execution, Python execution, and Grounded NL queries.
"""

import unittest
import tempfile
import os
from core.object.model import DataObject, ObjectType
from infrastructure.storage.sqlite_store import SQLiteStorage
from engines.query.query_engine import UnifiedQueryEngine


class TestQueryExecution(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.query_engine = UnifiedQueryEngine(self.storage)

        # Seed tabular dataset
        self.dataset = self.storage.save_object(DataObject(
            type=ObjectType.DATASET.value,
            properties={"filename": "employees.csv", "table_name": "employees"},
            content=[
                {"id": 1, "name": "Alice", "department": "Eng", "salary": 120000},
                {"id": 2, "name": "Bob", "department": "Eng", "salary": 110000},
                {"id": 3, "name": "Charlie", "department": "Design", "salary": 95000}
            ],
            source="file://employees.csv"
        ))

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_sql_query_execution(self):
        """Verify real SQL query execution against registered dataset table."""
        res = self.query_engine.execute_query("SELECT department, AVG(salary) as avg_sal FROM employees GROUP BY department ORDER BY avg_sal DESC;")
        self.assertTrue(res["success"])
        self.assertEqual(res["row_count"], 2)
        eng_row = next(r for r in res["results"] if r["department"] == "Eng")
        self.assertEqual(eng_row["avg_sal"], 115000.0)

    def test_python_query_execution(self):
        """Verify Python execution."""
        code = "results['total_eng_salary'] = int(dfs['employees'][dfs['employees']['department'] == 'Eng']['salary'].sum())"
        res = self.query_engine.execute_query(code, query_type="python", context_object_id=self.dataset.id)
        self.assertTrue(res["success"])
        self.assertEqual(res["results"]["total_eng_salary"], 230000)

    def test_grounded_natural_language_query(self):
        """Verify natural language query grounded in search and graph."""
        res = self.query_engine.execute_query("Find employee salary records", query_type="natural_language")
        self.assertTrue(res["success"])
        self.assertTrue(len(res["evidence"]) >= 1)


if __name__ == "__main__":
    unittest.main()
