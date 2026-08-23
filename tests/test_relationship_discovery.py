"""
Tests for Automatic Relationship Discovery Engine (Phase 4).
Verifies multi-signal matching (Structural, Content, Code AST).
"""

import unittest
import tempfile
import os
from core.object.model import DataObject, ObjectType
from core.relation.types import RelationType
from infrastructure.storage.sqlite_store import SQLiteStorage
from intelligence.discovery.engine import RelationshipDiscoveryEngine


class TestRelationshipDiscovery(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.engine = RelationshipDiscoveryEngine(self.storage)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_content_and_citation_discovery(self):
        """Verify automatic link between paper.md referencing students.csv."""
        csv_obj = self.storage.save_object(DataObject(
            type=ObjectType.DATASET.value,
            properties={"filename": "students.csv", "columns": ["student_id", "gpa"]},
            source="file://students.csv"
        ))

        doc_obj = self.storage.save_object(DataObject(
            type=ObjectType.DOCUMENT.value,
            properties={"filename": "paper.md", "title": "Academic Study"},
            content="We evaluate GPA performance from students.csv across 500 samples.",
            source="file://paper.md"
        ))

        discovered = self.engine.discover_all(auto_persist=True)
        self.assertTrue(len(discovered) >= 1)
        
        rel = discovered[0]
        self.assertEqual(rel.source, doc_obj.id)
        self.assertEqual(rel.target, csv_obj.id)
        self.assertGreaterEqual(rel.confidence, 0.8)
        self.assertTrue(len(rel.evidence) >= 1)

    def test_code_ast_dependency_discovery(self):
        """Verify automatic link between Python script and CSV data dependency."""
        csv_obj = self.storage.save_object(DataObject(
            type=ObjectType.DATASET.value,
            properties={"filename": "grades.csv"},
            source="file://grades.csv"
        ))

        code_obj = self.storage.save_object(DataObject(
            type=ObjectType.CODE.value,
            properties={"filename": "analysis.py", "data_dependencies": ["grades.csv"]},
            content="import pandas as pd\ndf = pd.read_csv('grades.csv')",
            source="file://analysis.py"
        ))

        discovered = self.engine.discover_relationships_for_object(code_obj, auto_persist=True)
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].relation_type, RelationType.READS_FROM.value)
        self.assertEqual(discovered[0].target, csv_obj.id)
        self.assertEqual(discovered[0].confidence, 0.95)


if __name__ == "__main__":
    unittest.main()
