"""
Tests for DataOS Kernel (Phase 1):
Object Model, Schemas, Relations, Provenance, Versioning, Permissions, and Persistent Storage.
"""

import unittest
import os
import tempfile
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from core.schema.model import Schema, FieldDefinition, DataType
from core.schema.validator import SchemaValidator
from core.provenance.model import ProvenanceEvent, ProvenanceEventType
from core.versioning.history import VersionHistory
from core.permissions.policy import PermissionPolicy, Capability
from infrastructure.storage.sqlite_store import SQLiteStorage
from infrastructure.storage.blob_store import FileBlobStorage


class TestDataOSKernel(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.temp_blob_dir = tempfile.mkdtemp()
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.blob_store = FileBlobStorage(root_dir=self.temp_blob_dir)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)
        import shutil
        if os.path.exists(self.temp_blob_dir):
            shutil.rmtree(self.temp_blob_dir)

    def test_universal_object_model(self):
        """Verify 11-field Universal Object Model and immutability version bumping."""
        obj = DataObject(
            type=ObjectType.DOCUMENT.value,
            schema="doc.v1",
            properties={"title": "Test Doc", "word_count": 120},
            content="Hello DataOS world",
            source="file://test.md"
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(obj.version, 1)
        self.assertIn("content_hash", obj.metadata)

        # Save to persistent storage
        saved = self.storage.save_object(obj)
        retrieved = self.storage.get_object(obj.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.properties["title"], "Test Doc")

        # Create new version
        v2 = obj.create_new_version(
            new_properties={"word_count": 150},
            new_content="Hello DataOS world updated",
            transformation_desc="Added content"
        )
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.id, obj.id)
        self.assertEqual(v2.properties["word_count"], 150)
        self.assertEqual(len(v2.provenance["transformations"]), 1)

    def test_schema_definition_and_validation(self):
        """Verify dynamic schema validation and constraints."""
        schema = Schema(name="user_profile.v1", target_object_type="user")
        schema.add_field(FieldDefinition(name="username", data_type=DataType.STRING.value, constraints={"required": True, "min_length": 3}))
        schema.add_field(FieldDefinition(name="age", data_type=DataType.INTEGER.value, constraints={"min_value": 0, "max_value": 150}))

        # Valid data
        valid_res = SchemaValidator.validate(schema, {"username": "alice", "age": 30})
        self.assertTrue(valid_res.is_valid)

        # Invalid data (missing required field)
        invalid_res = SchemaValidator.validate(schema, {"age": 30})
        self.assertFalse(invalid_res.is_valid)
        self.assertIn("Missing required field: 'username'", invalid_res.errors[0])

        # Save & retrieve schema
        self.storage.save_schema(schema)
        retrieved_schema = self.storage.get_schema("user_profile.v1")
        self.assertIsNotNone(retrieved_schema)
        self.assertEqual(retrieved_schema.name, "user_profile.v1")

    def test_first_class_relationships(self):
        """Verify relationship creation, persistence, confidence, and evidence."""
        obj1 = self.storage.save_object(DataObject(type="document", source="file://a.md"))
        obj2 = self.storage.save_object(DataObject(type="dataset", source="file://b.csv"))

        rel = Relationship(
            source=obj1.id,
            target=obj2.id,
            relation_type=RelationType.DERIVED_FROM.value,
            confidence=0.92
        )
        rel.add_evidence("citation", "Explicit reference to dataset b.csv", 0.92)
        self.storage.save_relationship(rel)

        retrieved_rels = self.storage.list_relationships(source_id=obj1.id)
        self.assertEqual(len(retrieved_rels), 1)
        self.assertEqual(retrieved_rels[0].target, obj2.id)
        self.assertEqual(retrieved_rels[0].confidence, 0.92)
        self.assertEqual(len(retrieved_rels[0].evidence), 1)

    def test_provenance_event_logging(self):
        """Verify provenance logging and OpenLineage standard conversion."""
        event = ProvenanceEvent(
            target_object_id="test-obj-123",
            event_type=ProvenanceEventType.TRANSFORMATION.value,
            description="CSV Cleaned and Aggregated",
            inputs=[{"object_id": "raw-csv-1", "version": 1}],
            tools_used=[{"name": "pandas", "version": "2.0"}]
        )
        self.storage.record_provenance_event(event)

        events = self.storage.get_provenance_events("test-obj-123")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "transformation")

        openlineage = event.to_openlineage_run_event()
        self.assertEqual(openlineage["eventType"], "COMPLETE")
        self.assertEqual(openlineage["job"]["namespace"], "dataos")

    def test_permissions_capability_gating(self):
        """Verify role-based capability enforcement."""
        policy = PermissionPolicy(
            principal_id="readonly_agent",
            allowed_capabilities={Capability.SEARCH.value, Capability.READ_OBJECT.value}
        )
        self.assertTrue(policy.has_capability(Capability.SEARCH))
        self.assertTrue(policy.has_capability(Capability.READ_OBJECT))
        self.assertFalse(policy.has_capability(Capability.DELETE_OBJECT))
        self.assertFalse(policy.has_capability(Capability.QUERY_SQL))


if __name__ == "__main__":
    unittest.main()
