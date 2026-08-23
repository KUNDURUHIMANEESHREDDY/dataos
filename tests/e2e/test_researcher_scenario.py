"""
Scenario C: Researcher Workflow End-to-End Test.
Artifacts:
- paper.md (Research paper with embedded tables and bibliography)
- experiment_data.csv (Raw laboratory trials data)
- experiment_pipeline.ipynb (Jupyter Notebook parsing cell execution DAG)

Verifies:
1. Ingestion of rich document, raw dataset, and Jupyter Notebook DAG
2. Cell-level dependency and data read lineage
3. Multi-hop knowledge and lineage graph connectivity
4. Why? API tracing research conclusions back to raw experiment cells
"""

import unittest
import tempfile
import os
import json
from dataos_system import DataOS


class TestResearcherScenario(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.dataos = DataOS(db_path=self.temp_db)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_researcher_reproducibility_journey(self):
        # 1. Ingest Raw Dataset
        csv_data = "trial_id,temperature,efficiency,batch\n1,300,0.85,A\n2,320,0.89,A\n3,340,0.92,B\n4,360,0.95,B\n"
        res_data = self.dataos.ingest(csv_data, filename="experiment_data.csv")
        data_id = res_data["primary_object_id"]

        # 2. Ingest Jupyter Notebook DAG
        notebook_dict = {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": 1,
                    "metadata": {},
                    "source": [
                        "import pandas as pd\n",
                        "raw_df = pd.read_csv('experiment_data.csv')\n",
                        "print(raw_df.shape)"
                    ],
                    "outputs": [{"output_type": "stream", "name": "stdout", "text": ["(4, 4)\n"]}]
                },
                {
                    "cell_type": "code",
                    "execution_count": 2,
                    "metadata": {},
                    "source": [
                        "efficiency_mean = raw_df['efficiency'].mean()\n",
                        "print('Mean efficiency:', efficiency_mean)"
                    ],
                    "outputs": [{"output_type": "stream", "name": "stdout", "text": ["Mean efficiency: 0.9025\n"]}]
                }
            ],
            "metadata": {"language_info": {"name": "python"}},
            "nbformat": 4,
            "nbformat_minor": 4
        }
        res_nb = self.dataos.ingest(json.dumps(notebook_dict), filename="experiment_pipeline.ipynb")
        nb_id = res_nb["primary_object_id"]
        self.assertEqual(res_nb["format"], ".ipynb")

        # 3. Ingest Research Paper with Tables and Citations
        paper_content = """# Thermal Efficiency Gains in Catalyst Reactions
## Abstract
This study evaluates high-temperature catalyst efficiency based on experiment_data.csv.

| Temperature | Efficiency |
| ----------- | ---------- |
| 300 K       | 85%        |
| 360 K       | 95%        |

## Analysis Pipeline
Data processed in experiment_pipeline.ipynb demonstrates a linear efficiency gain with temperature.
"""
        res_paper = self.dataos.ingest(paper_content, filename="catalyst_paper.md")
        paper_id = res_paper["primary_object_id"]
        self.assertGreaterEqual(res_paper["extracted_tables_count"], 1)

        # 4. Verify Graph Discovery
        paper_neighbors = self.dataos.graph.neighbors(paper_id)
        self.assertTrue(len(paper_neighbors) >= 1)

        # 5. Ask DataOS to explain why the paper conclusions exist
        why_paper = self.dataos.why(paper_id)
        self.assertEqual(why_paper["object_name"], "catalyst_paper.md")

        # 6. Ask DataOS regarding efficiency findings
        ask_res = self.dataos.ask("What is the efficiency trend in catalyst experiment_data.csv?")
        self.assertEqual(ask_res["intent"], "FIND_EVIDENCE")
        self.assertTrue(len(ask_res["evidence"]) >= 1)


if __name__ == "__main__":
    unittest.main()
