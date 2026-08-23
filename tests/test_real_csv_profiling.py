"""
Tests for Data Profiling & Quality Engine (Phase 5).
Verifies that all statistics, distributions, and quality checks are calculated on real data.
"""

import unittest
import pandas as pd
import numpy as np
from engines.profiling.profiler import DataProfiler
from engines.quality.quality_engine import DataQualityEngine


class TestRealCSVProfiling(unittest.TestCase):

    def setUp(self):
        # Create real sample dataframe with known properties
        # Column A: Normal numbers with 1 known outlier (1000)
        # Column B: Categorical values
        # Column C: Perfect correlation with Column A
        data = {
            "gpa": [3.0, 3.2, 3.5, 3.8, 4.0, 3.6, 3.4, 3.9, 10.0],  # 10.0 is an outlier
            "major": ["CS", "CS", "Math", "CS", "Physics", "Math", "CS", "Physics", "CS"],
            "score": [30.0, 32.0, 35.0, 38.0, 40.0, 36.0, 34.0, 39.0, 100.0]
        }
        self.df = pd.DataFrame(data)

    def test_statistical_profiling(self):
        """Verify real computed metrics from dataframe."""
        profile = DataProfiler.profile_dataframe(self.df, dataset_name="students")
        self.assertEqual(profile["row_count"], 9)
        self.assertEqual(profile["column_count"], 3)
        self.assertEqual(profile["completeness_ratio"], 1.0)

        # Check GPA stats
        gpa_meta = profile["columns"]["gpa"]
        self.assertEqual(gpa_meta["kind"], "numeric")
        self.assertAlmostEqual(gpa_meta["mean"], float(self.df["gpa"].mean()), places=3)
        self.assertEqual(gpa_meta["outlier_count"], 1)  # 10.0 detected as outlier

        # Check Pearson correlation between gpa and score
        corr = profile["correlations"]["gpa"]["score"]
        self.assertAlmostEqual(corr, 1.0, places=3)

    def test_quality_rule_evaluation(self):
        """Verify data quality assertions."""
        rules = [
            {"type": "row_count_min", "min_rows": 5},
            {"type": "not_null", "column": "gpa", "max_null_ratio": 0.0},
            {"type": "range", "column": "gpa", "min": 0.0, "max": 4.0}  # Will fail because of 10.0
        ]
        report_obj = DataQualityEngine.evaluate_rules(self.df, rules, target_object_id="test-dataset")
        
        self.assertFalse(report_obj.properties["overall_pass"])
        self.assertEqual(report_obj.properties["total_checks"], 3)
        self.assertEqual(report_obj.properties["passed_checks"], 2)
        self.assertEqual(report_obj.properties["failed_checks"], 1)


if __name__ == "__main__":
    unittest.main()
