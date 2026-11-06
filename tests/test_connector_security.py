"""Security regressions for database and filesystem connectors."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from infrastructure.connectors.database_connector import DatabaseConnector
from infrastructure.connectors.filesystem_connector import FilesystemConnector


class TestDatabaseConnectorSecurity(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "source.db")
        connection = sqlite3.connect(self.db_path)
        connection.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);"
            "INSERT INTO users VALUES (1, 'Alice');"
            "CREATE TABLE orders (id INTEGER PRIMARY KEY);"
            "INSERT INTO orders VALUES (1);"
        )
        connection.commit()
        connection.close()
        self.connector = DatabaseConnector(
            "readonly",
            {"engine": "sqlite", "connection_string": f"sqlite:///{self.db_path}", "read_only": True},
        )

    def tearDown(self):
        self.connector.close()
        self.temp_dir.cleanup()

    def test_catalog_lookup_rejects_injected_table_identifier(self):
        with self.assertRaises(FileNotFoundError):
            self.connector.read_resource("users; DROP TABLE orders")
        self.assertIn("orders", [item["name"] for item in self.connector.list_resources()])

    def test_read_resource_bounds_limit(self):
        for limit in (0, -1, 10001, True):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.connector.read_resource("users", limit=limit)

    def test_read_only_sqlite_authorizer_blocks_attach_pragma_and_ddl(self):
        for query in (
            "ATTACH DATABASE ':memory:' AS injected",
            "PRAGMA query_only = OFF",
            "CREATE TABLE injected (id INTEGER)",
        ):
            with self.subTest(query=query):
                with self.assertRaises(sqlite3.DatabaseError):
                    self.connector.execute_query(query)
        self.assertIn("orders", [item["name"] for item in self.connector.list_resources()])

    def test_read_only_sqlite_still_allows_select(self):
        result = self.connector.execute_query("SELECT name FROM users")
        self.assertEqual(result["rows"], [{"name": "Alice"}])

    def test_postgres_schema_filter_uses_bound_parameters(self):
        class FakeCursor:
            def __init__(self):
                self.query = None
                self.params = None
            def execute(self, query, params=None):
                self.query = query
                self.params = params
            def fetchall(self):
                return []
        class FakeConnection:
            def __init__(self):
                self.current_cursor = FakeCursor()
            def cursor(self):
                return self.current_cursor

        connector = DatabaseConnector(
            "postgres",
            {"engine": "postgresql", "connection_string": "postgresql://unused", "schema_filter": ["public", "x' OR 1=1 --"]},
        )
        fake = FakeConnection()
        connector._connection = fake
        try:
            self.assertEqual(connector.list_resources(), [])
            self.assertIn("IN (%s, %s)", fake.current_cursor.query)
            self.assertEqual(fake.current_cursor.params, ("public", "x' OR 1=1 --"))
            self.assertNotIn("x' OR 1=1 --", fake.current_cursor.query)
        finally:
            connector._connection = None


class TestFilesystemConnectorSecurity(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.root = base / "root"
        self.root.mkdir()
        (self.root / "safe.txt").write_text("safe", encoding="utf-8")
        self.outside = base / "outside.txt"
        self.outside.write_text("outside", encoding="utf-8")
        self.connector = FilesystemConnector("scoped", {"root_path": str(self.root)})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_rejects_parent_and_absolute_path_reads(self):
        with self.assertRaises(ValueError):
            self.connector.read_resource("../outside.txt")
        with self.assertRaises(ValueError):
            self.connector.read_resource(str(self.outside))

    def test_rejects_directory_traversal(self):
        with self.assertRaises(ValueError):
            self.connector.read_directory("../")

    def test_rejects_and_hides_symlink_escape(self):
        link = self.root / "outside-link.txt"
        try:
            link.symlink_to(self.outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is unavailable on this platform")
        with self.assertRaises(ValueError):
            self.connector.read_resource("outside-link.txt")
        self.assertNotIn("outside-link.txt", [item["name"] for item in self.connector.list_resources()])


if __name__ == "__main__":
    unittest.main()
