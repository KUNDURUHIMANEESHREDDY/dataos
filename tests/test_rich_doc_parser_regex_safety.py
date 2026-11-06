"""Regression tests for bounded Markdown figure and footnote parsing."""

import unittest

from intelligence.document.rich_doc_parser import RichDocumentExtractor


class TestRichDocumentRegexSafety(unittest.TestCase):
    def test_extracts_normal_figures_and_footnotes(self):
        parsed = RichDocumentExtractor.extract_markdown_tables_and_figures(
            "![System diagram](images/system.png)\n[^source-1]: Verified source"
        )

        self.assertEqual(parsed["figure_count"], 1)
        self.assertEqual(parsed["figures"][0]["caption"], "System diagram")
        self.assertEqual(parsed["figures"][0]["path"], "images/system.png")
        self.assertEqual(parsed["citation_count"], 1)
        self.assertEqual(parsed["citations"][0]["key"], "source-1")
        self.assertEqual(parsed["citations"][0]["text"], "Verified source")

    def test_long_unterminated_lines_fail_closed(self):
        malformed_figure = "![" + ("caption" * 10000) + "](" + ("x" * 100000)
        malformed_footnote = "[^source]:" + (" " * 100000)
        parsed = RichDocumentExtractor.extract_markdown_tables_and_figures(
            malformed_figure + "\n" + malformed_footnote
        )

        self.assertEqual(parsed["figures"], [])
        self.assertEqual(parsed["citations"], [])


if __name__ == "__main__":
    unittest.main()
