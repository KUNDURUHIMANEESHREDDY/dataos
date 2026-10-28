"""
Dual-Backend Storage Tests for DataOS (Rule #28, Rule #30).
Verifies contract parity between SQLiteStorage and PostgresStorage.
"""

import unittest
import tempfile
import os
import types
from unittest.mock import Mock, patch
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from core.schema.model import Schema
from core.provenance.model import ProvenanceEvent
from infrastructure.storage.sqlite_store import SQLiteStorage
from infrastructure.storage.postgres_store import PostgresStorage
from dataos_system import DataOS


class TestDualStorageBackends(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.sqlite_store = SQLiteStorage(db_path=self.temp_db)
        self.postgres_store = PostgresStorage(mock_mode=True)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def _test_backend_contract_parity(self, store, name: str):
        # 1. Object Lifecycle
        obj = store.save_object(DataObject(
            type=ObjectType.DATASET.value,
            properties={"name": "metrics", "rows": 100},
            content=[{"metric": "latency", "val": 42}],
            provenance={"created_by": "test_agent"}
        ))
        retrieved = store.get_object(obj.id)
        self.assertIsNotNone(retrieved, f"Failed to retrieve object from {name}")
        self.assertEqual(retrieved.properties["rows"], 100)

        # 2. Relationship Lifecycle
        report_obj = store.save_object(DataObject(
            type=ObjectType.REPORT.value,
            properties={"title": "Performance Report"}
        ))

        # Counts describe the full filtered collection, not just the first page.
        self.assertEqual(store.count_objects(), 2)
        self.assertEqual(store.count_objects(object_type=ObjectType.DATASET.value), 1)
        self.assertEqual(store.count_objects(source="internal"), 2)

        rel = store.save_relationship(Relationship(
            source=obj.id,
            target=report_obj.id,
            relation_type=RelationType.PRODUCES.value,
            confidence=0.98
        ))
        rel_retrieved = store.get_relationship(rel.id)
        self.assertIsNotNone(rel_retrieved)
        self.assertEqual(rel_retrieved.confidence, 0.98)

        low_confidence = store.save_relationship(Relationship(
            source=obj.id, target=report_obj.id, relation_type=RelationType.REFERENCES.value, confidence=0.2
        ))
        self.assertEqual(low_confidence.confidence, 0.2)
        high_confidence = store.save_relationship(Relationship(
            source=obj.id, target=report_obj.id, relation_type=RelationType.REFERENCES.value, confidence=0.75
        ))
        self.assertEqual(store.count_relationships(source_id=obj.id, min_confidence=0.5), 2)
        self.assertEqual(len(store.list_relationships(source_id=obj.id, min_confidence=0.5, limit=1, offset=0)), 1)
        self.assertTrue(store.delete_relationship(high_confidence.id, soft=True))
        self.assertIsNone(store.get_relationship(high_confidence.id))
        self.assertEqual(store.count_relationships(source_id=obj.id, min_confidence=0.5), 1)
        self.assertEqual(store.list_relationships(source_id=obj.id, min_confidence=0.5, limit=10), [rel_retrieved])

        # 3. Schema Lifecycle
        schema = store.save_schema(Schema(
            name="dataset.metrics.v1",
            target_object_type=ObjectType.DATASET.value,
            version="1.0.0",
            fields={}
        ))
        sch_retrieved = store.get_schema("dataset.metrics.v1")
        self.assertIsNotNone(sch_retrieved)
        self.assertEqual(sch_retrieved.name, "dataset.metrics.v1")

        # 4. Provenance Events
        prov_event = store.record_provenance_event(ProvenanceEvent(
            target_object_id=obj.id,
            event_type="ingestion",
            description="Ingested raw metrics CSV"
        ))
        events = store.get_provenance_events(obj.id)
        self.assertTrue(len(events) >= 1)
        self.assertEqual(events[0].event_type, "ingestion")

        # 5. Version History Snapshots
        history = store.get_version_history(obj.id)
        self.assertTrue(len(history) >= 1)
        self.assertEqual(history[0]["version"], 1)

        # Object deletion must honor the common storage contract in both
        # PostgreSQL mode and its SQLite emulation.
        temporary = store.save_object(DataObject(
            type=ObjectType.DATASET.value,
            properties={"name": "temporary"}
        ))
        self.assertTrue(store.delete_object(temporary.id, soft=False))
        self.assertIsNone(store.get_object(temporary.id))
        self.assertEqual(store.count_objects(), 2)

        self.assertTrue(store.delete_object(obj.id, soft=True))
        self.assertIsNone(store.get_object(obj.id))
        self.assertEqual(store.count_objects(), 1)
        self.assertEqual([item.id for item in store.list_objects(limit=10)], [report_obj.id])

        self.assertTrue(store.delete_object(report_obj.id, soft=True))
        self.assertEqual(store.count_objects(), 0)
        self.assertEqual(store.list_objects(limit=10), [])

    def test_sqlite_storage_contract(self):
        self._test_backend_contract_parity(self.sqlite_store, "SQLiteStorage")

    def test_postgres_storage_contract(self):
        self._test_backend_contract_parity(self.postgres_store, "PostgresStorage")

    def test_dataos_runtime_backend_switching(self):
        # 1. Initialize DataOS with SQLite
        dataos_sqlite = DataOS(db_path=self.temp_db)
        self.assertIsInstance(dataos_sqlite.storage, SQLiteStorage)

        # 2. Initialize DataOS with Postgres backend
        dataos_pg = DataOS(storage_backend=self.postgres_store)
        self.assertIsInstance(dataos_pg.storage, PostgresStorage)

        # 3. A requested PostgreSQL URL must fail closed if the connection
        # cannot be established; it must never silently become ephemeral SQLite.
        driver = types.ModuleType("psycopg2")
        driver.connect = Mock(side_effect=OSError("connection refused"))
        with patch.dict("sys.modules", {"psycopg2": driver}):
            with self.assertRaisesRegex(RuntimeError, "refusing to fall back to ephemeral SQLite"):
                DataOS.from_url("postgresql://postgres:postgres@db.invalid:5432/dataos")
        driver.connect.assert_called_once()


    def test_postgres_schema_failure_closes_connection_before_raising(self):
        # A successful TCP connection followed by a schema error must not leak
        # the partially initialized connection when the constructor fails.
        connection = Mock()
        driver = types.ModuleType("psycopg2")
        driver.connect = Mock(return_value=connection)
        with patch.dict("sys.modules", {"psycopg2": driver}):
            with patch.object(PostgresStorage, "_init_postgres_schema", side_effect=ValueError("schema failure")):
                with self.assertRaisesRegex(RuntimeError, "refusing to fall back to ephemeral SQLite"):
                    PostgresStorage(connection_string="postgresql://user:password@db.invalid:5432/dataos")
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
