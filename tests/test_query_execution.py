"""
Tests for Unified Query Engine (Phase 6).
Verifies SQL execution, Python execution, grounded NL queries and SQL safety.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.object.model import DataObject, ObjectType
from engines.compute.sql_engine import SQLExecutionEngine, _ALLOWED_SQLITE_FUNCTIONS
from infrastructure.storage.sqlite_store import SQLiteStorage
from engines.query.query_engine import UnifiedQueryEngine


class TestQueryExecution(unittest.TestCase):

    def setUp(self):
        fd, self.temp_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.query_engine = UnifiedQueryEngine(self.storage)
        self.sql_engine = SQLExecutionEngine(self.storage)

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
        res = self.query_engine.execute_query(
            "SELECT department, AVG(salary) as avg_sal FROM employees "
            "GROUP BY department ORDER BY avg_sal DESC;"
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["row_count"], 2)
        eng_row = next(r for r in res["results"] if r["department"] == "Eng")
        self.assertEqual(eng_row["avg_sal"], 115000.0)

    def test_sql_engine_does_not_overwrite_ambiguous_dataset_aliases(self):
        """Duplicate filenames must not silently select whichever dataset registers last."""
        second_dataset = self.storage.save_object(DataObject(
            type=ObjectType.DATASET.value,
            properties={"filename": "employees.csv", "table_name": "employees"},
            content=[{"id": 9, "name": "Mallory", "department": "Security", "salary": 1}],
            source="file://another-employees.csv",
        ))

        ambiguous = self.sql_engine.execute_sql(
            "SELECT name FROM employees",
            table_objects=[self.dataset, second_dataset],
        )
        self.assertFalse(ambiguous["success"])
        self.assertIn("employees", ambiguous["ambiguous_table_names"])
        self.assertNotIn("employees", ambiguous["registered_tables"])

        for dataset, expected_name in (
            (self.dataset, "Alice"),
            (second_dataset, "Mallory"),
        ):
            with self.subTest(dataset_id=dataset.id):
                alias = f"tbl_{dataset.id[:8]}"
                result = self.sql_engine.execute_sql(
                    f"SELECT name FROM {alias}",
                    table_objects=[self.dataset, second_dataset],
                )
                self.assertTrue(result["success"], result["error"])
                self.assertEqual(result["rows"][0]["name"], expected_name)
                self.assertIn("employees", result["ambiguous_table_names"])

    def test_sql_engine_rejects_database_mutations_and_pragmas(self):
        """Caller SQL must not alter registered data or the in-memory schema."""
        forbidden_queries = (
            "DELETE FROM employees",
            "UPDATE employees SET salary = 0",
            "INSERT INTO employees (id, name) VALUES (4, 'Mallory')",
            "CREATE TABLE attacker (value TEXT)",
            "DROP TABLE employees",
            "ALTER TABLE employees ADD COLUMN secret TEXT",
            "ATTACH DATABASE ':memory:' AS attacker",
            "PRAGMA query_only = OFF",
        )
        for query in forbidden_queries:
            with self.subTest(query=query):
                result = self.sql_engine.execute_sql(
                    query,
                    table_objects=[self.dataset],
                )
                self.assertFalse(result["success"])

    def test_sqlite_function_policy_uses_canonical_sorted_manifest(self):
        manifest = Path(__file__).resolve().parents[1] / "security" / "sqlite_allowed_functions.txt"
        entries = [
            line.strip()
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(entries, sorted(entries))
        self.assertEqual(len(entries), len(set(entries)))
        self.assertEqual(_ALLOWED_SQLITE_FUNCTIONS, set(entries))

    def test_sql_engine_allows_reviewed_scalar_and_aggregate_functions(self):
        result = self.sql_engine.execute_sql(
            "SELECT LOWER(name) AS normalized_name, "
            "ROUND(AVG(salary), 2) AS avg_salary "
            "FROM employees GROUP BY LOWER(name) ORDER BY normalized_name",
            table_objects=[self.dataset],
        )
        self.assertTrue(result["success"], result["error"])
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["rows"][0]["normalized_name"], "alice")

    def test_sql_engine_rejects_unreviewed_sqlite_functions(self):
        for query in ("SELECT random()", "SELECT randomblob(8)", "SELECT sqlite_version()"):
            with self.subTest(query=query):
                result = self.sql_engine.execute_sql(query, table_objects=[])
                self.assertFalse(result["success"])
                self.assertIn("not authorized", result["error"].lower())

    def test_sql_engine_rejects_extension_and_file_functions(self):
        """Untrusted SQL must not load extensions or access SQLite file helpers."""
        forbidden_queries = (
            "SELECT load_extension('untrusted-extension')",
            "SELECT readfile('/etc/passwd')",
            "SELECT writefile('/tmp/dataos-sql-test', 'x')",
            "SELECT fts3_tokenizer('simple')",
        )
        for query in forbidden_queries:
            with self.subTest(query=query):
                result = self.sql_engine.execute_sql(query, table_objects=[self.dataset])
                self.assertFalse(result["success"])
                if "load_extension" in query:
                    self.assertIn("not authorized", result["error"].lower())

    def test_sql_engine_rejects_multiple_statements(self):
        result = self.sql_engine.execute_sql(
            "SELECT 1; DROP TABLE employees",
            table_objects=[self.dataset],
        )
        self.assertFalse(result["success"])

    def test_sql_engine_rejects_oversized_query(self):
        query = "SELECT 1 -- " + ("x" * SQLExecutionEngine.MAX_QUERY_BYTES)
        result = self.sql_engine.execute_sql(query, table_objects=[])
        self.assertFalse(result["success"])
        self.assertIn("byte limit", result["error"])

    def test_sql_engine_rejects_oversized_result(self):
        query = (
            "WITH RECURSIVE seq(x) AS (VALUES(1) "
            "UNION ALL SELECT x + 1 FROM seq WHERE x < 10001) "
            "SELECT x FROM seq"
        )
        result = self.sql_engine.execute_sql(query, table_objects=[])
        self.assertFalse(result["success"])
        self.assertIn("row limit", result["error"])

    def test_sql_engine_enforces_execution_deadline(self):
        query = (
            "WITH RECURSIVE seq(x) AS (VALUES(1) "
            "UNION ALL SELECT x + 1 FROM seq WHERE x < 1000000) "
            "SELECT sum(x) FROM seq"
        )
        with patch.object(SQLExecutionEngine, "MAX_QUERY_SECONDS", -1):
            result = self.sql_engine.execute_sql(query, table_objects=[])
        self.assertFalse(result["success"])
        self.assertIn("interrupted", result["error"].lower())

    def test_python_query_execution(self):
        """Verify Python execution."""
        code = (
            "results['total_eng_salary'] = int("
            "dfs['employees'][dfs['employees']['department'] == 'Eng']['salary'].sum())"
        )
        res = self.query_engine.execute_query(
            code,
            query_type="python",
            context_object_id=self.dataset.id,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["results"]["total_eng_salary"], 230000)

    def test_grounded_natural_language_query(self):
        """Verify natural language query grounded in search and graph."""
        res = self.query_engine.execute_query(
            "Find employee salary records",
            query_type="natural_language",
        )
        self.assertTrue(res["success"])
        self.assertTrue(len(res["evidence"]) >= 1)


if __name__ == "__main__":
    unittest.main()
