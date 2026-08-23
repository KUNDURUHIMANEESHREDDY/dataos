"""
Tests for Multi-Agent Orchestration, Graph Recommendations & AI Providers (Rules #20, #44, #57).
"""

import unittest
import tempfile
import os
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from infrastructure.storage.sqlite_store import SQLiteStorage
from engines.graph.recommendations import GraphRecommendationEngine
from runtime.agents.providers import MockDeterministicProvider, TokenCostTracker
from runtime.agents.orchestrator import MultiAgentPipeline


class TestMultiAgentAndRecommendations(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.recommendations = GraphRecommendationEngine(self.storage)
        self.pipeline = MultiAgentPipeline(self.storage)

        # Seed real dataset
        self.dataset_obj = self.storage.save_object(DataObject(
            type=ObjectType.DATASET.value,
            schema="dataset.v1",
            properties={"filename": "grades.csv", "table_name": "grades"},
            content=[
                {"student_id": 1, "score": 95, "section": "A"},
                {"student_id": 2, "score": 88, "section": "A"},
                {"student_id": 3, "score": 72, "section": "B"},
                {"student_id": 4, "score": 91, "section": "B"}
            ],
            source="file://grades.csv"
        ))

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_multi_agent_pipeline_execution(self):
        """Rule #20: Execute 4-stage sequential Multi-Agent pipeline (Research -> Analysis -> Quality -> Report)."""
        res = self.pipeline.run_end_to_end_research_pipeline(
            goal_prompt="Analyze exam score variance by section in grades dataset",
            target_dataset_id=self.dataset_obj.id,
            analysis_sql_or_python="SELECT section, AVG(score) as avg_score, COUNT(*) as count FROM grades GROUP BY section ORDER BY avg_score DESC;",
            quality_rules=[
                {"type": "row_count_min", "min_rows": 2},
                {"type": "not_null", "column": "score", "max_null_ratio": 0.0}
            ]
        )

        self.assertEqual(res["status"], "completed")
        self.assertIn("report_object_id", res)
        self.assertEqual(len(res["trace"]["stages"]), 4)

        # Verify Stage 1: Research
        s1 = res["trace"]["stages"][0]
        self.assertEqual(s1["agent"], "agent_research")

        # Verify Stage 2: Analysis
        s2 = res["trace"]["stages"][1]
        self.assertEqual(s2["agent"], "agent_analysis")
        self.assertTrue(s2["success"])

        # Verify Stage 3: Quality
        s3 = res["trace"]["stages"][2]
        self.assertEqual(s3["agent"], "agent_quality")
        self.assertTrue(s3["quality_pass"])

        # Verify Stage 4: Report Object created and persisted
        report_obj = self.storage.get_object(res["report_object_id"])
        self.assertIsNotNone(report_obj)
        self.assertEqual(report_obj.type, ObjectType.REPORT.value)
        self.assertTrue(report_obj.provenance["zero_fabrication_checked"])

        # Verify Relationship report -> derived_from -> dataset
        rels = self.storage.list_relationships(source_id=report_obj.id)
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0].target, self.dataset_obj.id)

    def test_graph_recommendation_engine(self):
        """Rule #57: Suggest missing connections and candidate relationships with explainable evidence."""
        # Create 3 objects:
        # Paper A cites Dataset X
        # Paper B cites Dataset X
        # -> Recommendation engine should suggest connection between Paper A and Paper B (Bibliographic coupling)
        dataset_x = self.storage.save_object(DataObject(type="dataset", properties={"filename": "benchmark_data.csv"}))
        paper_a = self.storage.save_object(DataObject(type="document", properties={"filename": "paper_a.md", "title": "Model Alpha"}))
        paper_b = self.storage.save_object(DataObject(type="document", properties={"filename": "paper_b.md", "title": "Model Beta"}))

        self.storage.save_relationship(Relationship(source=paper_a.id, target=dataset_x.id, relation_type=RelationType.CITES.value))
        self.storage.save_relationship(Relationship(source=paper_b.id, target=dataset_x.id, relation_type=RelationType.CITES.value))

        # Ask recommendations for Paper A
        recs = self.recommendations.recommend_connections(paper_a.id, top_k=5)
        self.assertTrue(len(recs) >= 1)
        
        top_rec = recs[0]
        self.assertEqual(top_rec["candidate_object_id"], paper_b.id)
        self.assertGreaterEqual(top_rec["confidence"], 0.3)
        self.assertTrue(len(top_rec["evidence_paths"]) >= 1)
        self.assertTrue(any("upstream" in p or "common neighbor" in p for p in top_rec["evidence_paths"]))

    def test_ai_provider_and_token_cost_tracking(self):
        """Rule #44: Pluggable AI provider and token budget tracking."""
        provider = MockDeterministicProvider(model_name="mock_v1")
        tracker = TokenCostTracker()

        response = provider.generate(
            prompt="Summarize dataset metrics",
            context_data=[{"filename": "grades.csv", "rows": 4}]
        )

        self.assertEqual(response.model, "mock_v1")
        self.assertGreater(response.prompt_tokens, 0)
        self.assertGreater(response.completion_tokens, 0)

        # Track usage
        tracker.record_usage("analysis_agent", response)
        summary = tracker.get_summary()

        self.assertGreater(summary["total_tokens"], 0)
        self.assertIn("analysis_agent", summary["agent_breakdown"])
        self.assertEqual(summary["agent_breakdown"]["analysis_agent"]["call_count"], 1)


if __name__ == "__main__":
    unittest.main()
