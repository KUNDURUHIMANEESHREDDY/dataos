"""Tests for the fail-closed known SQL sink regression sentinel."""

import unittest

from scripts.check_sql_compiler_boundary import find_unsafe_sql_sinks


class TestSQLCompilerBoundary(unittest.TestCase):
    def test_detects_python_caller_controlled_execute(self):
        findings = find_unsafe_sql_sinks(
            {
                "engines/compute/sql_engine.py": (
                    "cursor = conn.execute(\n    sql_query\n)\n"
                ),
                "rust-backend/src/sql_engine.rs": "conn.prepare(compiled.sql)",
            }
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("engines/compute/sql_engine.py:1", findings[0])

    def test_detects_rust_caller_controlled_prepare(self):
        findings = find_unsafe_sql_sinks(
            {
                "engines/compute/sql_engine.py": "conn.execute(compiled.sql, params)",
                "rust-backend/src/sql_engine.rs": "let stmt = conn.prepare(query)?;",
            }
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("rust-backend/src/sql_engine.rs:1", findings[0])

    def test_allows_compiler_output_with_bound_parameters(self):
        findings = find_unsafe_sql_sinks(
            {
                "engines/compute/sql_engine.py": (
                    "compiled = compile_read_only_query(request, schema)\n"
                    "cursor = conn.execute(compiled.sql, compiled.parameters)\n"
                ),
                "rust-backend/src/sql_engine.rs": (
                    "let compiled = compile_read_only_query(request, schema)?;\n"
                    "let mut stmt = conn.prepare(&compiled.sql)?;\n"
                    "stmt.query(params_from_iter(compiled.parameters))?;\n"
                ),
            }
        )
        self.assertEqual(findings, [])

    def test_missing_runtime_source_fails_closed(self):
        findings = find_unsafe_sql_sinks(
            {"engines/compute/sql_engine.py": "conn.execute(compiled.sql, params)"}
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("missing source file", findings[0])


if __name__ == "__main__":
    unittest.main()
