"""
Tests for Knowledge Extraction (Rule #46).
Validates entity, concept, claim, and relationship extraction.
"""

import unittest
from intelligence.knowledge.extractor import (
    KnowledgeExtractor, ExtractedEntity, ExtractedConcept,
    ExtractedClaim, ExtractedRelationship, EntityType,
)


class TestKnowledgeExtractor(unittest.TestCase):

    def setUp(self):
        self.extractor = KnowledgeExtractor()

    def test_extract_entities_email(self):
        text = "Contact us at support@example.com for help."
        entities = self.extractor.extract_entities(text)
        emails = [e for e in entities if e.entity_type == EntityType.EMAIL]
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0].text, "support@example.com")

    def test_extract_entities_url(self):
        text = "Visit https://example.com or www.test.org for details."
        entities = self.extractor.extract_entities(text)
        urls = [e for e in entities if e.entity_type == EntityType.URL]
        self.assertGreaterEqual(len(urls), 1)

    def test_extract_entities_date(self):
        text = "The meeting is on 2024-01-15 and the report is due Jan 20, 2024."
        entities = self.extractor.extract_entities(text)
        dates = [e for e in entities if e.entity_type == EntityType.DATE]
        self.assertGreaterEqual(len(dates), 1)

    def test_extract_entities_file_ref(self):
        text = "Analyze data.csv and merge with results.json into report.pdf."
        entities = self.extractor.extract_entities(text)
        files = [e for e in entities if e.entity_type == EntityType.FILE_REF]
        filenames = [e.text for e in files]
        self.assertIn("data.csv", filenames)
        self.assertIn("results.json", filenames)
        self.assertIn("report.pdf", filenames)

    def test_extract_entities_code_ref(self):
        text = "Use pandas.DataFrame to load the data via mymodule.utils.loader."
        entities = self.extractor.extract_entities(text)
        code_refs = [e for e in entities if e.entity_type == EntityType.CODE_REF]
        self.assertGreaterEqual(len(code_refs), 1)

    def test_extract_entities_capitalized(self):
        text = "Alice went to Paris to meet with Google about the project."
        entities = self.extractor.extract_entities(text)
        names = [e.text for e in entities]
        self.assertIn("Alice", names)
        self.assertIn("Paris", names)
        self.assertIn("Google", names)

    def test_extract_concepts(self):
        text = """
        Machine learning is a subset of artificial intelligence. Machine learning
        algorithms learn from data. Deep learning is a specialized form of machine
        learning using neural networks. Data science combines statistics and computing.
        """
        concepts = self.extractor.extract_concepts(text, top_k=5)
        self.assertGreaterEqual(len(concepts), 3)
        terms = [c.term for c in concepts]
        self.assertIn("machine", terms)

    def test_extract_concepts_empty(self):
        concepts = self.extractor.extract_concepts("")
        self.assertEqual(len(concepts), 0)

    def test_extract_claims(self):
        text = "The study shows that 75% of users prefer the new interface. The system is always available."
        claims = self.extractor.extract_claims(text)
        self.assertGreaterEqual(len(claims), 1)
        types = [c.claim_type for c in claims]
        self.assertIn("numerical", types)

    def test_extract_claims_short_sentences_ignored(self):
        text = "Yes. No. Maybe."
        claims = self.extractor.extract_claims(text)
        self.assertEqual(len(claims), 0)

    def test_extract_relationships(self):
        text = "Bob depends on Alice and Charlie depends on Alice."
        rels = self.extractor.extract_relationships(text)
        self.assertGreaterEqual(len(rels), 1)
        rel_types = [r.relation_type for r in rels]
        self.assertIn("depends_on", rel_types)

    def test_extract_relationships_has(self):
        text = "The database has Alice and the table has Bob."
        rels = self.extractor.extract_relationships(text)
        has_rels = [r for r in rels if r.relation_type == "has_property"]
        self.assertGreaterEqual(len(has_rels), 1)

    def test_extract_all(self):
        text = "Alice visited Google.com on 2024-01-15. The report.csv contains analysis data."
        result = self.extractor.extract_all(text)
        self.assertIn("entities", result)
        self.assertIn("concepts", result)
        self.assertIn("claims", result)
        self.assertIn("relationships", result)
        self.assertIsInstance(result["entities"], list)

    def test_entity_to_dict(self):
        entity = ExtractedEntity(
            text="test@email.com",
            entity_type=EntityType.EMAIL,
            confidence=0.9,
            start_pos=0,
            end_pos=15,
        )
        d = entity.to_dict()
        self.assertEqual(d["text"], "test@email.com")
        self.assertEqual(d["entity_type"], "email")
        self.assertEqual(d["confidence"], 0.9)

    def test_concept_to_dict(self):
        concept = ExtractedConcept(term="machine learning", weight=0.8, context="Machine learning is AI.")
        d = concept.to_dict()
        self.assertEqual(d["term"], "machine learning")
        self.assertEqual(d["weight"], 0.8)

    def test_claim_to_dict(self):
        claim = ExtractedClaim(
            text="The data shows 50% improvement",
            claim_type="numerical",
            confidence=0.7,
            evidence_span="50%",
        )
        d = claim.to_dict()
        self.assertEqual(d["claim_type"], "numerical")
        self.assertIn("50%", d["evidence_span"])

    def test_relationship_to_dict(self):
        rel = ExtractedRelationship(
            source="Python",
            target="programming language",
            relation_type="is_a",
            confidence=0.8,
        )
        d = rel.to_dict()
        self.assertEqual(d["relation_type"], "is_a")
        self.assertEqual(d["source"], "Python")

    def test_deduplication(self):
        text = "Email support@example.com or email admin@example.com. Email support@example.com again."
        entities = self.extractor.extract_entities(text)
        emails = [e for e in entities if e.entity_type == EntityType.EMAIL]
        # Should be deduplicated
        unique_emails = set(e.text for e in emails)
        self.assertEqual(len(unique_emails), 2)

    def test_custom_patterns(self):
        import re
        custom = {"version": re.compile(r'v\d+\.\d+\.\d+')}
        extractor = KnowledgeExtractor(custom_entity_patterns=custom)
        text = "Running version v1.2.3 in production."
        entities = extractor.extract_entities(text)
        versions = [e for e in entities if e.entity_type == EntityType.CUSTOM]
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].text, "v1.2.3")

    def test_phone_extraction(self):
        text = "Call us at (555) 123-4567 or +1-800-555-0199."
        entities = self.extractor.extract_entities(text)
        phones = [e for e in entities if e.entity_type == EntityType.PHONE]
        self.assertGreaterEqual(len(phones), 1)


class TestEntityType(unittest.TestCase):

    def test_all_types(self):
        for et in EntityType:
            self.assertIsInstance(et.value, str)


if __name__ == "__main__":
    unittest.main()
