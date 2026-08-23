"""
Tests for Connector System (Rule #36).
Validates connector creation, lifecycle, database/filesystem connectors, and manager.
"""

import unittest
import os
import tempfile
import shutil
import sqlite3
import json
from infrastructure.connectors.base import BaseConnector
from infrastructure.connectors.database_connector import DatabaseConnector
from infrastructure.connectors.filesystem_connector import FilesystemConnector
from infrastructure.connectors.connector_manager import ConnectorManager, ConnectorState


class TestBaseConnector(unittest.TestCase):

    def test_base_connector_is_abstract(self):
        with self.assertRaises(TypeError):
            BaseConnector(name="test", config={})

    def test_base_connector_interface(self):
        class DummyConnector(BaseConnector):
            def test_connection(self): return True
            def list_resources(self): return []
            def read_resource(self, resource_id): return {}
        c = DummyConnector(name="d", config={"a": 1})
        self.assertEqual(c.name, "d")
        self.assertEqual(c.config["a"], 1)


class TestDatabaseConnector(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.connector = None
        conn = sqlite3.connect(self.temp_db)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
        cursor.execute("INSERT INTO users VALUES (1, 'Alice', 30)")
        cursor.execute("INSERT INTO users VALUES (2, 'Bob', 25)")
        cursor.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL)")
        cursor.execute("INSERT INTO orders VALUES (1, 1, 99.99)")
        cursor.execute("INSERT INTO orders VALUES (2, 2, 49.50)")
        conn.commit()
        conn.close()

    def tearDown(self):
        if self.connector:
            self.connector.close()
        if os.path.exists(self.temp_db):
            try:
                os.remove(self.temp_db)
            except PermissionError:
                pass

    def test_connection(self):
        self.connector = DatabaseConnector(name="test_db", config={
            "engine": "sqlite",
            "connection_string": f"sqlite:///{self.temp_db}",
        })
        self.assertTrue(self.connector.test_connection())

    def test_list_resources(self):
        self.connector = DatabaseConnector(name="test_db", config={
            "engine": "sqlite",
            "connection_string": f"sqlite:///{self.temp_db}",
        })
        resources = self.connector.list_resources()
        names = [r["name"] for r in resources]
        self.assertIn("users", names)
        self.assertIn("orders", names)

    def test_read_resource(self):
        self.connector = DatabaseConnector(name="test_db", config={
            "engine": "sqlite",
            "connection_string": f"sqlite:///{self.temp_db}",
        })
        data = self.connector.read_resource("users")
        self.assertEqual(data["row_count"], 2)
        self.assertEqual(data["columns"], ["id", "name", "age"])
        self.assertEqual(data["rows"][0]["name"], "Alice")

    def test_read_resource_as_object(self):
        self.connector = DatabaseConnector(name="test_db", config={
            "engine": "sqlite",
            "connection_string": f"sqlite:///{self.temp_db}",
        })
        obj = self.connector.read_resource_as_object("users")
        self.assertEqual(obj.type, "dataset")
        self.assertEqual(obj.properties["table_name"], "users")
        self.assertEqual(len(obj.content), 2)

    def test_execute_query(self):
        self.connector = DatabaseConnector(name="test_db", config={
            "engine": "sqlite",
            "connection_string": f"sqlite:///{self.temp_db}",
        })
        result = self.connector.execute_query("SELECT name FROM users WHERE age > 26")
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["name"], "Alice")

    def test_read_only_blocks_writes(self):
        self.connector = DatabaseConnector(name="test_db", config={
            "engine": "sqlite",
            "connection_string": f"sqlite:///{self.temp_db}",
            "read_only": True,
        })
        with self.assertRaises(PermissionError):
            self.connector.execute_query("DELETE FROM users")

    def test_bad_engine_raises(self):
        with self.assertRaises(ValueError):
            DatabaseConnector(name="bad", config={"engine": "oracle", "connection_string": ""})

    def test_close(self):
        connector = DatabaseConnector(name="test_db", config={
            "engine": "sqlite",
            "connection_string": f"sqlite:///{self.temp_db}",
        })
        connector._get_connection()
        connector.close()
        self.assertIsNone(connector._connection)


class TestFilesystemConnector(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        # Create test files
        with open(os.path.join(self.temp_dir, "data.csv"), "w") as f:
            f.write("name,score\nAlice,95\nBob,87")
        with open(os.path.join(self.temp_dir, "notes.md"), "w") as f:
            f.write("# Notes\nHello world")
        os.makedirs(os.path.join(self.temp_dir, "subdir"))
        with open(os.path.join(self.temp_dir, "subdir", "nested.json"), "w") as f:
            json.dump({"key": "value"}, f)
        with open(os.path.join(self.temp_dir, ".hidden"), "w") as f:
            f.write("secret")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_connection(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        self.assertTrue(connector.test_connection())

    def test_list_resources(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        resources = connector.list_resources()
        names = [r["name"] for r in resources]
        self.assertIn("data.csv", names)
        self.assertIn("notes.md", names)

    def test_hidden_files_excluded_by_default(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        resources = connector.list_resources()
        names = [r["name"] for r in resources]
        self.assertNotIn(".hidden", names)

    def test_hidden_files_included(self):
        connector = FilesystemConnector(name="test_fs", config={
            "root_path": self.temp_dir,
            "include_hidden": True,
        })
        resources = connector.list_resources()
        names = [r["name"] for r in resources]
        self.assertIn(".hidden", names)

    def test_file_type_filter(self):
        connector = FilesystemConnector(name="test_fs", config={
            "root_path": self.temp_dir,
            "file_types": [".csv"],
        })
        resources = connector.list_resources()
        names = [r["name"] for r in resources]
        self.assertIn("data.csv", names)
        self.assertNotIn("notes.md", names)

    def test_read_resource(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        data = connector.read_resource("data.csv")
        self.assertEqual(data["name"], "data.csv")
        self.assertIn("name,score", data["content"])
        self.assertFalse(data["is_binary"])

    def test_read_resource_as_object(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        obj = connector.read_resource_as_object("data.csv")
        self.assertEqual(obj.type, "dataset")
        self.assertEqual(obj.properties["filename"], "data.csv")
        self.assertIn("name,score", obj.content)

    def test_read_json_as_object(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        obj = connector.read_resource_as_object("subdir/nested.json")
        self.assertEqual(obj.type, "dataset")
        self.assertEqual(obj.content, {"key": "value"})

    def test_read_nonexistent_raises(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        with self.assertRaises(FileNotFoundError):
            connector.read_resource("no_such_file.csv")

    def test_search_files(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        results = connector.search_files("data.csv")
        self.assertGreaterEqual(len(results), 1)
        names = [r["name"] for r in results]
        self.assertIn("data.csv", names)

    def test_read_directory(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        items = connector.read_directory(".")
        names = [i["name"] for i in items]
        self.assertIn("data.csv", names)

    def test_close(self):
        connector = FilesystemConnector(name="test_fs", config={"root_path": self.temp_dir})
        connector.close()  # Should not raise


class TestConnectorManager(unittest.TestCase):

    def setUp(self):
        ConnectorManager.reset()
        self.manager = ConnectorManager()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        ConnectorManager.reset()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_connector(self):
        connector = self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.assertIsInstance(connector, FilesystemConnector)
        self.assertEqual(connector.name, "fs1")

    def test_get_connector(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        c = self.manager.get_connector("fs1")
        self.assertIsNotNone(c)
        self.assertEqual(c.name, "fs1")

    def test_duplicate_raises(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        with self.assertRaises(ValueError):
            self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})

    def test_connect(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.assertTrue(self.manager.connect("fs1"))
        entry = self.manager.get_entry("fs1")
        self.assertEqual(entry.state, ConnectorState.CONNECTED)

    def test_connect_nonexistent(self):
        self.assertFalse(self.manager.connect("no_such"))

    def test_disconnect(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.manager.connect("fs1")
        self.assertTrue(self.manager.disconnect("fs1"))
        entry = self.manager.get_entry("fs1")
        self.assertEqual(entry.state, ConnectorState.DISCONNECTED)

    def test_remove(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.assertTrue(self.manager.remove("fs1"))
        self.assertIsNone(self.manager.get_connector("fs1"))

    def test_list_all(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.manager.create_connector("db1", "database", {"engine": "sqlite", "connection_string": ":memory:"})
        all_c = self.manager.list_all()
        self.assertEqual(len(all_c), 2)

    def test_list_by_type(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.manager.create_connector("fs2", "filesystem", {"root_path": self.temp_dir})
        fs_list = self.manager.list_by_type("filesystem")
        self.assertEqual(len(fs_list), 2)

    def test_list_connected(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.manager.create_connector("fs2", "filesystem", {"root_path": self.temp_dir})
        self.manager.connect("fs1")
        connected = self.manager.list_connected()
        self.assertEqual(len(connected), 1)

    def test_connect_all(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.manager.create_connector("fs2", "filesystem", {"root_path": self.temp_dir})
        results = self.manager.connect_all()
        self.assertTrue(results["fs1"])
        self.assertTrue(results["fs2"])

    def test_disconnect_all(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        self.manager.connect("fs1")
        self.manager.disconnect_all()
        entry = self.manager.get_entry("fs1")
        self.assertEqual(entry.state, ConnectorState.DISCONNECTED)

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            self.manager.create_connector("bad", "oracle_db", {})

    def test_register_custom_type(self):
        class CustomConnector(BaseConnector):
            def test_connection(self): return True
            def list_resources(self): return []
            def read_resource(self, resource_id): return {}
        self.manager.register_type("custom", CustomConnector)
        c = self.manager.create_connector("c1", "custom", {})
        self.assertIsInstance(c, CustomConnector)

    def test_get_stats(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        stats = self.manager.get_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["by_type"]["filesystem"], 1)

    def test_ingest_from_connector(self):
        self.manager.create_connector("fs1", "filesystem", {"root_path": self.temp_dir})
        with open(os.path.join(self.temp_dir, "test.csv"), "w") as f:
            f.write("a,b\n1,2")
        obj = self.manager.ingest_from_connector("fs1", "test.csv")
        self.assertIsNotNone(obj)
        self.assertEqual(obj.type, "dataset")


class TestConnectorEntry(unittest.TestCase):

    def test_to_dict(self):
        from infrastructure.connectors.connector_manager import ConnectorEntry, ConnectorState
        c = FilesystemConnector(name="test", config={"root_path": "."})
        entry = ConnectorEntry(connector=c, connector_type="filesystem")
        d = entry.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["connector_type"], "filesystem")
        self.assertEqual(d["state"], ConnectorState.REGISTERED)


if __name__ == "__main__":
    unittest.main()
