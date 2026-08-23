"""
Tests for Data Lineage, Provenance Traversal, Agent Permissions, and Lossless Export.
"""

import unittest
import tempfile
import os
import json
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from core.permissions.policy import PermissionPolicy, Capability
from infrastructure.storage.sqlite_store import SQLiteStorage
from core.provenance.lineage_engine import LineageEngine
from runtime.agents.agent import AgentHarness
from infrastructure.io.export_engine import DataOSExporter


class TestLineageAndGovernance(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.lineage = LineageEngine(self.storage)
        self.exporter = DataOSExporter(self.storage)

        # Build Lineage Chain: Raw Data -> Cleaned Data -> Model/Analysis -> Report
        self.raw_obj = self.storage.save_object(DataObject(type="dataset", source="file://raw_data.csv"))
        self.clean_obj = self.storage.save_object(DataObject(type="dataset", source="derived://cleaned"))
        self.model_obj = self.storage.save_object(DataObject(type="model", source="derived://model"))
        self.report_obj = self.storage.save_object(DataObject(type="report", source="derived://report"))

        # Add derivation relationships
        # clean_obj derived_from raw_obj
        self.storage.save_relationship(Relationship(source=self.raw_obj.id, target=self.clean_obj.id, relation_type=RelationType.TRANSFORMS_TO.value))
        # model_obj reads_from clean_obj
        self.storage.save_relationship(Relationship(source=self.clean_obj.id, target=self.model_obj.id, relation_type=RelationType.READS_FROM.value))
        # report_obj derived_from model_obj
        self.storage.save_relationship(Relationship(source=self.model_obj.id, target=self.report_obj.id, relation_type=RelationType.DERIVED_FROM.value))

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_upstream_lineage_trace(self):
        """Verify upstream lineage from final report traces all the way back to raw_data.csv."""
        trace = self.lineage.trace_upstream_lineage(self.report_obj.id, max_depth=5)
        self.assertEqual(trace["target_object_id"], self.report_obj.id)
        self.assertEqual(trace["total_ancestors"], 3)
        self.assertTrue(len(trace["root_sources"]) >= 1)
        self.assertEqual(trace["root_sources"][0]["object_id"], self.raw_obj.id)

    def test_downstream_impact_analysis(self):
        """Verify downstream impact of raw_data.csv touches clean_obj, model_obj, and report_obj."""
        impact = self.lineage.trace_downstream_impact(self.raw_obj.id, max_depth=5)
        self.assertEqual(impact["root_object_id"], self.raw_obj.id)
        self.assertEqual(impact["total_downstream_dependents"], 3)
        impacted_ids = [n["object_id"] for n in impact["impacted_nodes"]]
        self.assertIn(self.clean_obj.id, impacted_ids)
        self.assertIn(self.report_obj.id, impacted_ids)

    def test_agent_permission_enforcement(self):
        """Verify agent capability enforcement and execution tracing."""
        policy = PermissionPolicy(
            principal_id="test_agent",
            allowed_capabilities={Capability.SEARCH.value, Capability.READ_OBJECT.value}
        )
        harness = AgentHarness(agent_id="test_agent", policy=policy, storage=self.storage)

        # Authorized operation
        read_res = harness.execute_capability(Capability.READ_OBJECT, {"object_id": self.raw_obj.id})
        self.assertTrue(read_res["success"])
        self.assertEqual(read_res["output"]["id"], self.raw_obj.id)

        # Unauthorized operation (SQL Query) -> Should raise PermissionError
        with self.assertRaises(PermissionError):
            harness.execute_capability(Capability.QUERY_SQL, {"query": "SELECT 1;"})

    def test_lossless_export(self):
        """Verify export to standard JSON-LD and GraphML formats."""
        json_ld = self.exporter.export_json_ld()
        self.assertIn("@graph", json_ld)
        self.assertEqual(len(json_ld["@graph"]), 4)
        self.assertEqual(len(json_ld["relationships"]), 3)

        graphml_xml = self.exporter.export_graphml()
        self.assertIn("<graphml", graphml_xml)
        self.assertIn(self.raw_obj.id, graphml_xml)

        sql_dump = self.exporter.export_sql_dump()
        self.assertIn("INSERT INTO dataos_objects", sql_dump)


if __name__ == "__main__":
    unittest.main()
