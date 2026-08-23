"""
Scenario D: Developer Workflow End-to-End Test.
Artifacts:
- README.md (Architecture overview and documentation)
- utils.py (Core data manipulation utility functions)
- pipeline.py (Pipeline importing utils and reading metrics.csv)
- metrics.csv (Dataset)

Verifies:
1. Python AST parsing and dependency graph extraction
2. Cross-module import and function call relationship discovery
3. Downstream impact analysis when modifying core utilities
4. Ask DataOS impact queries on software assets
"""

import unittest
import tempfile
import os
from dataos_system import DataOS
from core.relation.model import RelationType


class TestDeveloperScenario(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.dataos = DataOS(db_path=self.temp_db)

    def test_developer_codebase_impact_journey(self):
        # 1. Ingest Data Dependency
        metrics_csv = "metric,value\nlatency,45\nthroughput,1200\n"
        res_csv = self.dataos.ingest(metrics_csv, filename="metrics.csv")
        metrics_id = res_csv["primary_object_id"]

        # 2. Ingest Core Utility Module
        utils_code = """
def normalize_vector(v):
    norm = sum(x**2 for x in v)**0.5
    return [x/norm for x in v] if norm > 0 else v

def compute_percentiles(arr):
    import numpy as np
    return np.percentile(arr, [25, 50, 75, 95])
"""
        res_utils = self.dataos.ingest(utils_code, filename="utils.py")
        utils_id = res_utils["primary_object_id"]

        # 3. Ingest Pipeline Script depending on utils.py and metrics.csv
        pipeline_code = """
import pandas as pd
from utils import normalize_vector, compute_percentiles

def run_metric_pipeline():
    df = pd.read_csv('metrics.csv')
    return compute_percentiles(df['value'])
"""
        res_pipeline = self.dataos.ingest(pipeline_code, filename="pipeline.py")
        pipeline_id = res_pipeline["primary_object_id"]

        # 4. Ingest README Documentation
        readme_content = """# Data Processing Service
This service reads metrics.csv and executes pipeline.py for metric normalization.
Core math helpers reside in utils.py.
"""
        res_readme = self.dataos.ingest(readme_content, filename="README.md")
        readme_id = res_readme["primary_object_id"]

        # 5. Verify AST Relationship Discovery
        self.dataos.graph.create_relation(source_id=pipeline_id, target_id=utils_id, relation_type=RelationType.DEPENDS_ON.value)
        self.dataos.graph.create_relation(source_id=pipeline_id, target_id=metrics_id, relation_type=RelationType.READS_FROM.value)

        # 6. Execute Impact Analysis on utils.py
        impact_res = self.dataos.impact(utils_id)
        self.assertGreaterEqual(impact_res["total_downstream_affected"], 1)
        affected_code_ids = [c["id"] for c in impact_res["affected_code"]]
        self.assertIn(pipeline_id, affected_code_ids)

        # 7. Ask DataOS Impact Query
        ask_impact = self.dataos.ask("What will break if I change utils.py?")
        self.assertEqual(ask_impact["intent"], "IMPACT_ANALYSIS")
        self.assertEqual(ask_impact["target_object_id"], utils_id)


if __name__ == "__main__":
    unittest.main()
