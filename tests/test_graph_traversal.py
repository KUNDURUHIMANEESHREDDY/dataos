"""
Tests for Universal Relationship Graph & Graph Analytics (Phase 2).
Verifies multi-hop traversal, pathfinding, and NetworkX analytical algorithms.
"""

import unittest
import tempfile
import os
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from infrastructure.storage.sqlite_store import SQLiteStorage
from engines.graph.engine import GraphEngine
from engines.graph.algorithms import GraphAnalyticsEngine


class TestGraphTraversal(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.graph_engine = GraphEngine(self.storage)
        self.analytics_engine = GraphAnalyticsEngine(self.storage)

        # Build Graph: A -> B -> C and A -> D -> C
        self.obj_a = self.storage.save_object(DataObject(type="document", source="file://a.md"))
        self.obj_b = self.storage.save_object(DataObject(type="dataset", source="file://b.csv"))
        self.obj_c = self.storage.save_object(DataObject(type="report", source="file://c.pdf"))
        self.obj_d = self.storage.save_object(DataObject(type="notebook", source="file://d.ipynb"))

        self.graph_engine.create_relation(self.obj_a.id, self.obj_b.id, RelationType.REFERENCES.value, confidence=0.9)
        self.graph_engine.create_relation(self.obj_b.id, self.obj_c.id, RelationType.DERIVED_FROM.value, confidence=0.95)
        self.graph_engine.create_relation(self.obj_a.id, self.obj_d.id, RelationType.CITES.value, confidence=0.85)
        self.graph_engine.create_relation(self.obj_d.id, self.obj_c.id, RelationType.PRODUCES.value, confidence=0.9)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_multi_hop_traversal(self):
        """Verify 2-hop traversal from root node A reaches B, D, and C."""
        traversal = self.graph_engine.traverse(start_id=self.obj_a.id, max_hops=2)
        self.assertEqual(traversal["root_id"], self.obj_a.id)
        self.assertEqual(traversal["total_nodes_reached"], 4)
        self.assertEqual(len(traversal["edges"]), 4)

    def test_find_paths(self):
        """Verify pathfinding finds both paths: A->B->C and A->D->C."""
        paths = self.graph_engine.find_paths(self.obj_a.id, self.obj_c.id, max_depth=3)
        self.assertEqual(len(paths), 2)
        self.assertIn([self.obj_a.id, self.obj_b.id, self.obj_c.id], paths)
        self.assertIn([self.obj_a.id, self.obj_d.id, self.obj_c.id], paths)

    def test_graph_analytics_pagerank_and_centrality(self):
        """Verify NetworkX analysis correctly identifies node C as having high in-degree and importance."""
        pagerank_scores = self.analytics_engine.compute_pagerank()
        self.assertGreater(len(pagerank_scores), 0)
        self.assertIn(self.obj_c.id, pagerank_scores)

        centrality = self.analytics_engine.compute_degree_centrality()
        # Node C has 2 incoming edges
        self.assertGreater(centrality[self.obj_c.id]["in_degree"], 0.0)


if __name__ == "__main__":
    unittest.main()
