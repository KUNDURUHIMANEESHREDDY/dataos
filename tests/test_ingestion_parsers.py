"""
Tests for Ingestion Parsers (Phase 3).
Verifies Document, Dataset, Code AST, and Media intelligence parsing.
"""

import unittest
from intelligence.document.doc_parser import DocumentParser
from intelligence.dataset.dataset_parser import DatasetParser
from intelligence.code.ast_analyzer import CodeASTAnalyzer
from intelligence.media import MediaProcessor as MediaParser


class TestIngestionParsers(unittest.TestCase):

    def test_document_parser(self):
        """Verify Markdown section extraction and citation parsing."""
        md_text = """# Paper Title
## Abstract
This paper analyzes academic data.
## Methodology
We use dataset from [students.csv](file://students.csv) as described in [1] and (Knuth et al., 1984).
"""
        parsed = DocumentParser.parse_text_or_markdown(md_text, "paper.md")
        self.assertEqual(parsed["title"], "Paper Title")
        self.assertEqual(len(parsed["headings"]), 3)
        self.assertEqual(len(parsed["links"]), 1)
        self.assertEqual(parsed["links"][0]["text"], "students.csv")
        self.assertTrue(len(parsed["citations"]) >= 1)

    def test_dataset_parser(self):
        """Verify CSV column and type inference."""
        csv_text = "id,name,gpa,is_active\n1,Alice,3.85,True\n2,Bob,3.50,False\n3,Charlie,3.90,True"
        parsed = DatasetParser.parse_csv(csv_text, "students.csv")
        self.assertEqual(parsed["row_count"], 3)
        self.assertEqual(parsed["column_count"], 4)
        self.assertEqual(parsed["column_names"], ["id", "name", "gpa", "is_active"])

    def test_code_ast_analyzer(self):
        """Verify Python code AST extraction of imports, functions, and file reads."""
        code_text = """
import pandas as pd
import numpy as np

def calculate_gpa(filepath):
    df = pd.read_csv('students.csv')
    return df['gpa'].mean()
"""
        parsed = CodeASTAnalyzer.analyze_python_code(code_text, "analyzer.py")
        self.assertEqual(len(parsed["imports"]), 2)
        self.assertEqual(len(parsed["functions"]), 1)
        self.assertEqual(parsed["functions"][0]["name"], "calculate_gpa")
        self.assertIn("students.csv", parsed["data_dependencies"])

    def test_media_parser(self):
        """Verify transcript timestamp parsing."""
        vtt_text = """00:00:00.000 --> 00:00:05.000
Welcome to the data structures lecture.
00:00:05.500 --> 00:00:10.000
Today we will discuss graph algorithms."""
        parser = MediaParser()
        parsed = parser.parse_transcript(vtt_text, "lecture.vtt")
        self.assertEqual(parsed["segment_count"], 2)
        self.assertIn("Welcome", parsed["segments"][0]["text"])


if __name__ == "__main__":
    unittest.main()
