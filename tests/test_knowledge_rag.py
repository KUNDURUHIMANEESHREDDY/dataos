import unittest
from backend.knowledge_rag import extract_snippet, rank_text, resolve_related_files

class KnowledgeRAGHelpersTests(unittest.TestCase):
    def test_rank_text_rewards_query_overlap(self):
        self.assertGreater(rank_text("vector search", "Vector search uses semantic vectors."), 0.5)
        self.assertEqual(rank_text("unrelated token", "A completely different sentence."), 0.0)

    def test_extract_snippet_is_bounded_and_query_centered(self):
        text = ("background words " * 80) + "the target evidence appears here " + ("tail words " * 80)
        snippet = extract_snippet(text, "target evidence", max_chars=120)
        self.assertLessEqual(len(snippet), 122)
        self.assertIn("target", snippet)

    def test_related_files_are_confidence_filtered_and_bounded(self):
        rels = [
            {"source_id":"selected","target_id":"strong","confidence":0.9,"relation_type":"references"},
            {"source_id":"selected","target_id":"weak","confidence":0.4,"relation_type":"related_to"},
            {"source_id":"selected","target_id":"second","confidence":0.8,"relation_type":"derived_from"},
        ]
        result = resolve_related_files(["selected"], rels, max_related_files=1, min_confidence=0.75)
        self.assertEqual([x["file_id"] for x in result], ["strong"])

    def test_related_files_deduplicate_by_best_confidence(self):
        rels = [
            {"source_id":"a","target_id":"b","confidence":0.8,"relation_type":"related_to"},
            {"source_id":"a","target_id":"b","confidence":0.95,"relation_type":"references"},
        ]
        result = resolve_related_files(["a"], rels)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["confidence"], 0.95)
        self.assertEqual(result[0]["relationship_type"], "references")

if __name__ == "__main__":
    unittest.main()
