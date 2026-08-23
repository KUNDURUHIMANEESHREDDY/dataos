"""
Tests for Deep Format & Notebook Intelligence (Rules #51, #53, #54, #45).
Verifies:
1. Jupyter Notebook Cell-by-Cell DAG Engine & Lineage
2. Rich Document Embedded Tables, Figures, and Footnote Citation Extraction
3. Persistent Vector Indexing, Versioning, and Recomputability
"""

import unittest
import tempfile
import os
import json
from core.object.model import DataObject, ObjectType
from core.relation.model import RelationType
from infrastructure.storage.sqlite_store import SQLiteStorage
from intelligence.code.notebook_parser import JupyterNotebookParser
from intelligence.document.rich_doc_parser import RichDocumentExtractor
from engines.search.vector_index import PersistentVectorIndex, TFIDFVectorEmbeddingModel


class TestNotebookAndRichDocs(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.vector_index = PersistentVectorIndex(db_path=self.temp_db)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_jupyter_notebook_dag_and_lineage(self):
        """Rule #51: Parse .ipynb into cell-by-cell execution DAG and ingest to graph."""
        notebook_dict = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": "# Academic Performance Analysis\nLoad and analyze student data."
                },
                {
                    "cell_type": "code",
                    "execution_count": 1,
                    "source": "import pandas as pd\nraw_df = pd.read_csv('students.csv')",
                    "outputs": []
                },
                {
                    "cell_type": "code",
                    "execution_count": 2,
                    "source": "filtered_df = raw_df[raw_df['gpa'] > 3.5]\navg_gpa = filtered_df['gpa'].mean()",
                    "outputs": [{"name": "stdout", "text": "Filtered 4 students"}]
                },
                {
                    "cell_type": "code",
                    "execution_count": 3,
                    "source": "print('Final Result:', avg_gpa)\nfiltered_df.to_csv('high_performers.csv')",
                    "outputs": [{"name": "stdout", "text": "Final Result: 3.84"}]
                }
            ],
            "metadata": {"kernelspec": {"name": "python3"}},
            "nbformat": 4,
            "nbformat_minor": 2
        }
        nb_json_str = json.dumps(notebook_dict)

        # 1. Parse content
        parsed = JupyterNotebookParser.parse_notebook_content(nb_json_str, "academic_analysis.ipynb")
        self.assertEqual(parsed["total_cells"], 4)
        self.assertEqual(parsed["code_cells_count"], 3)
        self.assertEqual(parsed["markdown_cells_count"], 1)
        self.assertIn("students.csv", parsed["data_dependencies"])
        self.assertIn("high_performers.csv", parsed["data_outputs"])

        # Check Cell 2 depends on Cell 1 (raw_df)
        cell_2 = parsed["cells"][2]
        self.assertIn(1, cell_2["dependencies"])
        # Check Cell 3 depends on Cell 2 (avg_gpa, filtered_df)
        cell_3 = parsed["cells"][3]
        self.assertIn(2, cell_3["dependencies"])

        # 2. Ingest to Graph
        ingest_res = JupyterNotebookParser.ingest_notebook_to_graph(nb_json_str, "academic_analysis.ipynb", self.storage)
        self.assertEqual(ingest_res["cells_created"], 4)
        self.assertTrue(ingest_res["dag_edges_created"] >= 2)

        # Verify in persistent graph
        nb_obj = self.storage.get_object(ingest_res["notebook_id"])
        self.assertIsNotNone(nb_obj)
        
        # Check relationships
        rels = self.storage.list_relationships(source_id=nb_obj.id)
        self.assertEqual(len(rels), 4)  # 4 CONTAINS relations for 4 cells

    def test_rich_document_table_and_citation_extraction(self):
        """Rule #54: Extract embedded tables, figures, and footnotes from Markdown document."""
        doc_content = """# Machine Learning Benchmark Report

Here are the evaluation results:

| Model | Accuracy | F1_Score | Latency_ms |
|---|---|---|---|
| BERT | 0.92 | 0.91 | 45.2 |
| RoBERTa | 0.94 | 0.93 | 48.0 |
| GPT-4 | 0.98 | 0.97 | 120.5 |

![Architecture Overview](images/arch_diagram.png)

[^1]: Vaswani et al., 2017. Attention Is All You Need.
[^2]: Devlin et al., 2018. BERT: Pre-training of Deep Bidirectional Transformers.
"""
        # 1. Structure extraction
        extracted = RichDocumentExtractor.extract_markdown_tables_and_figures(doc_content)
        self.assertEqual(extracted["table_count"], 1)
        self.assertEqual(extracted["figure_count"], 1)
        self.assertEqual(extracted["citation_count"], 2)

        table_data = extracted["tables"][0]
        self.assertEqual(table_data["row_count"], 3)
        self.assertEqual(table_data["columns"], ["Model", "Accuracy", "F1_Score", "Latency_ms"])

        # 2. Ingest to Graph
        ingest_res = RichDocumentExtractor.ingest_rich_document_to_graph(doc_content, "benchmark_report.md", self.storage)
        self.assertEqual(ingest_res["tables_extracted_count"], 1)
        self.assertEqual(ingest_res["citations_extracted_count"], 2)

        # Verify extracted table object exists in storage as a first-class DataObject
        table_obj = self.storage.get_object(ingest_res["table_object_ids"][0])
        self.assertIsNotNone(table_obj)
        self.assertEqual(table_obj.type, ObjectType.TABLE.value)
        self.assertEqual(len(table_obj.content), 3)

    def test_persistent_vector_indexing_and_search(self):
        """Rule #45: Persistent vector index with cosine similarity search and recomputability."""
        # Create objects with distinct semantic domains
        obj_astronomy = self.storage.save_object(DataObject(
            type="document",
            properties={"filename": "astronomy.md", "title": "Hubble Deep Space Telescope and Galaxies"},
            content="Observations of distant spiral galaxies, nebulae, and stellar formation in deep space."
        ))
        obj_finance = self.storage.save_object(DataObject(
            type="document",
            properties={"filename": "finance.md", "title": "Quarterly Financial Revenue Earnings"},
            content="Quarterly balance sheet, EBITDA margins, cash flow statements, and dividends."
        ))
        obj_medicine = self.storage.save_object(DataObject(
            type="document",
            properties={"filename": "clinical.md", "title": "Clinical Trial Medical Pharmacology"},
            content="Double-blind clinical trial evaluating patient drug efficacy, dosage, and antibodies."
        ))

        # 1. Index all objects
        for obj in [obj_astronomy, obj_finance, obj_medicine]:
            idx_res = self.vector_index.index_object(obj)
            self.assertEqual(idx_res["model"], "tfidf_statistical")

        # 2. Search query in finance domain
        finance_matches = self.vector_index.search_similar("revenue earnings and dividends", top_k=2)
        self.assertTrue(len(finance_matches) >= 1)
        top_match = finance_matches[0]
        self.assertEqual(top_match["object_id"], obj_finance.id)
        self.assertGreater(top_match["similarity"], 0.0)

        # 3. Search query in astronomy domain
        astro_matches = self.vector_index.search_similar("telescope galaxies space", top_k=2)
        self.assertTrue(len(astro_matches) >= 1)
        self.assertEqual(astro_matches[0]["object_id"], obj_astronomy.id)

        # 4. Recompute all vectors (Rule #45 Recomputability)
        recompute_res = self.vector_index.recompute_all(self.storage)
        self.assertEqual(recompute_res["total_recomputed"], 3)


if __name__ == "__main__":
    unittest.main()
