"""
Tests for Cloud Storage Backends (Rule #50).
Tests metadata index and interface using in-memory SQLite (no cloud connection).
"""

import unittest
import json
from infrastructure.storage.cloud_store import CloudStorageBackend, S3Storage, GCSStorage, AzureBlobStorage
from core.object.model import DataObject, ObjectType, Timestamps
from core.relation.model import Relationship
from core.schema.model import Schema
from core.provenance.model import ProvenanceEvent


class MockCloudStorage(CloudStorageBackend):
    """Mock cloud storage for testing without cloud credentials."""

    def __init__(self, bucket_name="test-bucket", prefix="dataos/", index_db=":memory:"):
        super().__init__(bucket_name, prefix, index_db)
        self._blobs: dict = {}

    def _upload_blob(self, key, data, content_type="application/json"):
        self._blobs[key] = data
        return {"key": key, "size": len(data)}

    def _download_blob(self, key):
        return self._blobs.get(key)

    def _delete_blob(self, key):
        if key in self._blobs:
            del self._blobs[key]
            return True
        return False

    def _list_blobs(self, prefix=""):
        return [k for k in self._blobs if k.startswith(prefix)]


class TestMockCloudStorage(unittest.TestCase):

    def setUp(self):
        self.storage = MockCloudStorage()

    def test_save_and_get_object(self):
        obj = DataObject(id="obj1", type=ObjectType.DOCUMENT.value, properties={"name": "test"})
        saved = self.storage.save_object(obj)
        self.assertEqual(saved.id, "obj1")
        found = self.storage.get_object("obj1")
        self.assertIsNotNone(found)
        self.assertEqual(found.properties["name"], "test")

    def test_list_objects(self):
        self.storage.save_object(DataObject(id="o1", type="document"))
        self.storage.save_object(DataObject(id="o2", type="dataset"))
        all_objs = self.storage.list_objects()
        self.assertEqual(len(all_objs), 2)

    def test_list_objects_filter_type(self):
        self.storage.save_object(DataObject(id="o1", type="document"))
        self.storage.save_object(DataObject(id="o2", type="dataset"))
        docs = self.storage.list_objects(object_type="document")
        self.assertEqual(len(docs), 1)

    def test_delete_object_soft(self):
        self.storage.save_object(DataObject(id="o1", type="document"))
        self.assertTrue(self.storage.delete_object("o1", soft=True))
        self.assertIsNone(self.storage.get_object("o1"))

    def test_delete_object_hard(self):
        self.storage.save_object(DataObject(id="o1", type="document"))
        self.assertTrue(self.storage.delete_object("o1", soft=False))
        self.assertIsNone(self.storage.get_object("o1"))

    def test_delete_nonexistent(self):
        self.assertFalse(self.storage.delete_object("no_such"))

    def test_save_and_get_relationship(self):
        rel = Relationship(id="r1", source="a", target="b", relation_type="CONTAINS")
        self.storage.save_relationship(rel)
        found = self.storage.get_relationship("r1")
        self.assertIsNotNone(found)
        self.assertEqual(found.source, "a")

    def test_list_relationships(self):
        self.storage.save_relationship(Relationship(id="r1", source="a", target="b", relation_type="CONTAINS"))
        self.storage.save_relationship(Relationship(id="r2", source="a", target="c", relation_type="DEPENDS_ON"))
        rels = self.storage.list_relationships(source_id="a")
        self.assertEqual(len(rels), 2)

    def test_list_relationships_filter_type(self):
        self.storage.save_relationship(Relationship(id="r1", source="a", target="b", relation_type="CONTAINS"))
        self.storage.save_relationship(Relationship(id="r2", source="a", target="c", relation_type="DEPENDS_ON"))
        rels = self.storage.list_relationships(relation_type="CONTAINS")
        self.assertEqual(len(rels), 1)

    def test_delete_relationship(self):
        self.storage.save_relationship(Relationship(id="r1", source="a", target="b", relation_type="X"))
        self.assertTrue(self.storage.delete_relationship("r1"))
        self.assertIsNone(self.storage.get_relationship("r1"))

    def test_save_and_get_schema(self):
        schema = Schema(id="s1", name="test_schema", version=1, description="A test schema")
        self.storage.save_schema(schema)
        found = self.storage.get_schema("s1")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "test_schema")

    def test_get_schema_by_name(self):
        schema = Schema(id="s1", name="test_schema", version=1)
        self.storage.save_schema(schema)
        found = self.storage.get_schema("test_schema")
        self.assertIsNotNone(found)

    def test_list_schemas(self):
        self.storage.save_schema(Schema(id="s1", name="a", version=1))
        self.storage.save_schema(Schema(id="s2", name="b", version=1))
        schemas = self.storage.list_schemas()
        self.assertEqual(len(schemas), 2)

    def test_record_provenance_event(self):
        event = ProvenanceEvent(
            id="e1", target_object_id="obj1", event_type="created",
            description="Object created", inputs=[], outputs=["obj1"],
            tools_used=["ingestion"], parameters={}, execution_context={},
        )
        self.storage.record_provenance_event(event)
        events = self.storage.get_provenance_events("obj1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "created")

    def test_version_history(self):
        obj = DataObject(id="v1", type="document", version=1)
        self.storage.save_object(obj)
        obj2 = obj.create_new_version(new_properties={"updated": True})
        self.storage.save_object(obj2)
        history = self.storage.get_version_history("v1")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["version"], 1)
        self.assertEqual(history[1]["version"], 2)

    def test_object_saved_to_cloud(self):
        obj = DataObject(id="c1", type="document")
        self.storage.save_object(obj)
        blobs = self.storage._list_blobs("dataos/objects/")
        self.assertEqual(len(blobs), 1)

    def test_get_nonexistent(self):
        self.assertIsNone(self.storage.get_object("no_such"))
        self.assertIsNone(self.storage.get_relationship("no_such"))
        self.assertIsNone(self.storage.get_schema("no_such"))


class TestS3StorageInit(unittest.TestCase):

    def test_init(self):
        storage = S3Storage("my-bucket", prefix="test/", aws_access_key="key", aws_secret_key="secret")
        self.assertEqual(storage.bucket_name, "my-bucket")
        self.assertEqual(storage.prefix, "test/")

    def test_init_default_prefix(self):
        storage = S3Storage("my-bucket")
        self.assertEqual(storage.prefix, "dataos/")


class TestGCSStorageInit(unittest.TestCase):

    def test_init(self):
        storage = GCSStorage("my-bucket", project="my-project")
        self.assertEqual(storage.bucket_name, "my-bucket")
        self.assertEqual(storage._project, "my-project")


class TestAzureBlobStorageInit(unittest.TestCase):

    def test_init(self):
        storage = AzureBlobStorage("my-container", connection_string="DefaultEndpointsProtocol=https;")
        self.assertEqual(storage.bucket_name, "my-container")


class TestRelationship(unittest.TestCase):

    def test_relationship_to_dict(self):
        rel = Relationship(id="r1", source="a", target="b", relation_type="X")
        d = rel.to_dict()
        self.assertEqual(d["id"], "r1")
        self.assertEqual(d["source"], "a")


if __name__ == "__main__":
    unittest.main()
