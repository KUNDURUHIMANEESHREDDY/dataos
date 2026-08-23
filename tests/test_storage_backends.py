"""
Dual-Backend Storage Tests for DataOS (Rule #28, Rule #30).
Verifies contract parity between SQLiteStorage and PostgresStorage.
"""

import unittest
import tempfile
import os
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
        rel = store.save_relationship(Relationship(
            source=obj.id,
            target=report_obj.id,
            relation_type=RelationType.PRODUCES.value,
            confidence=0.98
        ))
        rel_retrieved = store.get_relationship(rel.id)
        self.assertIsNotNone(rel_retrieved)
        self.assertEqual(rel_retrieved.confidence, 0.98)

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

        # 3. Initialize via connection URL
        dataos_url = DataOS.from_url("postgresql://postgres:postgres@localhost:5432/dataos")
        self.assertIsInstance(dataos_url.storage, PostgresStorage)


if __name__ == "__main__":
    unittest.main()
