"""Live PostgreSQL integration tests for storage contracts and additive migrations.

The normal unit suite exercises PostgreSQL's SQLite emulation. This file runs
only in the dedicated CI service job, where fallback to mock mode is a failure.
"""
from __future__ import annotations

import os
import unittest
from uuid import uuid4

from core.object.model import DataObject, ObjectType
from infrastructure.storage.postgres_store import PostgresStorage


POSTGRES_URL = os.getenv("DATAOS_TEST_POSTGRES_URL")


@unittest.skipUnless(POSTGRES_URL, "requires the dedicated live PostgreSQL CI service")
class TestLivePostgresObjectLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg2

        # Simulate a database created by the pre-soft-delete schema. The store
        # initializer must add deleted_at without dropping or rewriting rows.
        connection = psycopg2.connect(POSTGRES_URL)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dataos_objects (
                        id VARCHAR(255) PRIMARY KEY,
                        type VARCHAR(64) NOT NULL,
                        schema VARCHAR(128) NOT NULL,
                        properties JSONB NOT NULL,
                        content JSONB,
                        provenance JSONB NOT NULL,
                        permissions JSONB NOT NULL,
                        timestamps JSONB NOT NULL,
                        version INT NOT NULL DEFAULT 1,
                        source TEXT,
                        metadata JSONB,
                        indexes JSONB
                    )
                    """
                )
            connection.commit()
        finally:
            connection.close()

        cls.store = PostgresStorage(connection_string=POSTGRES_URL, mock_mode=False)
        if cls.store.mock_mode or cls.store._pg_conn is None:
            raise AssertionError("Live PostgreSQL test silently fell back to mock mode")

    @classmethod
    def tearDownClass(cls) -> None:
        connection = getattr(cls.store, "_pg_conn", None)
        if connection is not None:
            connection.close()

    def test_additive_migration_and_soft_delete_visibility(self) -> None:
        token = uuid4().hex
        obj = DataObject(
            type=ObjectType.DATASET.value,
            properties={"integration_test": token},
            source=f"test://{token}",
        )
        self.store.save_object(obj)

        try:
            self.assertEqual(self.store.count_objects(source=token), 1)
            self.assertEqual(
                [item.id for item in self.store.list_objects(source=token, limit=10)],
                [obj.id],
            )

            self.assertTrue(self.store.delete_object(obj.id, soft=True))
            self.assertIsNone(self.store.get_object(obj.id))
            self.assertEqual(self.store.count_objects(source=token), 0)
            self.assertEqual(self.store.list_objects(source=token, limit=10), [])
            self.assertFalse(self.store.delete_object(obj.id, soft=True))
        finally:
            # Test data is unique and confined to the ephemeral CI database.
            self.store.delete_object(obj.id, soft=False)


if __name__ == "__main__":
    unittest.main()
