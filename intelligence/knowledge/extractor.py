"""
Knowledge Extraction Engine for DataOS (Rule #46).
Extracts structured knowledge from unstructured text:
entities, concepts, claims, and relationships.
Uses rule-based and heuristic approaches (no external NLP dependencies).
"""

from __future__ import annotations
import re
import uuid
import math
from typing import Dict, Any, List, Optional, Set, Tuple
from collections import Counter
from enum import Enum


class EntityType(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    DATE = "date"
    EMAIL = "email"
    URL = "url"
    PHONE = "phone"
    NUMBER = "number"
    CODE_REF = "code_ref"
    FILE_REF = "file_ref"
    CUSTOM = "custom"


class ExtractedEntity:
    """A single extracted entity from text."""

    def __init__(
        self,
        text: str,
        entity_type: EntityType,
        confidence: float = 0.5,
        start_pos: int = 0,
        end_pos: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.id = str(uuid.uuid4())[:12]
        self.text = text.strip()
        self.entity_type = entity_type
        self.confidence = confidence
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the entity."""
        return {
            "id": self.id,
            "text": self.text,
            "entity_type": self.entity_type.value,
            "confidence": round(self.confidence, 3),
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
            "metadata": self.metadata,
        }


class ExtractedConcept:
    """A topic or concept extracted from text."""

    def __init__(self, term: str, weight: float = 1.0, context: str = ""):
        self.id = str(uuid.uuid4())[:12]
        self.term = term.lower().strip()
        self.weight = weight
        self.context = context

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the concept."""
        return {
            "id": self.id,
            "term": self.term,
            "weight": round(self.weight, 3),
            "context": self.context[:200],
        }


class ExtractedClaim:
    """A factual claim extracted from text."""

    def __init__(
        self,
        text: str,
        claim_type: str = "assertion",
        confidence: float = 0.5,
        evidence_span: str = "",
        source_sentence: str = "",
    ):
        self.id = str(uuid.uuid4())[:12]
        self.text = text
        self.claim_type = claim_type
        self.confidence = confidence
        self.evidence_span = evidence_span
        self.source_sentence = source_sentence

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the claim."""
        return {
            "id": self.id,
            "text": self.text,
            "claim_type": self.claim_type,
            "confidence": round(self.confidence, 3),
            "evidence_span": self.evidence_span,
            "source_sentence": self.source_sentence[:200],
        }


class ExtractedRelationship:
    """A relationship extracted between two entities or concepts."""

    def __init__(
        self,
        source: str,
        target: str,
        relation_type: str,
        confidence: float = 0.5,
        evidence: str = "",
    ):
        self.id = str(uuid.uuid4())[:12]
        self.source = source
        self.target = target
        self.relation_type = relation_type
        self.confidence = confidence
        self.evidence = evidence

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the relationship."""
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relation_type": self.relation_type,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence[:200],
        }


class KnowledgeExtractor:
    """
    Extracts structured knowledge from unstructured text using rule-based methods.
    No external NLP library required.
    """

    # Patterns for entity extraction
    EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    URL_PATTERN = re.compile(r'https?://[^\s<>\"\')]+|www\.[^\s<>\"\')]+')
    PHONE_PATTERN = re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
    DATE_PATTERN = re.compile(
        r'\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|'
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4})\b',
        re.IGNORECASE,
    )
    NUMBER_PATTERN = re.compile(r'\b\d+(?:\.\d+)?(?:[%kKmMbB])?\b')
    CODE_REF_PATTERN = re.compile(r'\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+\b')
    FILE_REF_PATTERN = re.compile(
        r'\b[\w.-]+\.(?:csv|json|xml|pdf|md|txt|py|js|ts|ipynb|sql|parquet|yaml|yml|toml)\b',
        re.IGNORECASE,
    )

    # Common relationship indicator words
    RELATIONSHIP_INDICATORS = {
        "is_a": ["is a", "is an", "is the", "are", "was a", "was an"],
        "has_property": ["has", "have", "having", "contains", "includes", "features"],
        "part_of": ["part of", "component of", "belong to", "belongs to", "member of"],
        "causes": ["causes", "leads to", "results in", "triggers", "produces"],
        "depends_on": ["depends on", "relies on", "requires", "needs", "based on"],
        "derived_from": ["derived from", "based on", "computed from", "generated from"],
        "located_in": ["located in", "found in", "situated in", "based in", "in"],
        "created_by": ["created by", "built by", "developed by", "authored by", "written by"],
        "references": ["references", "cites", "mentions", "refers to", "quotes"],
        "opposite_of": ["opposite of", "contrast to", "versus", "vs", "unlike"],
    }

    # Stopwords for concept extraction
    STOPWORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "both", "each", "few", "more", "most",
        "other", "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "just", "because", "but", "and", "or",
        "if", "while", "about", "up", "it", "its", "this", "that", "these",
        "those", "i", "me", "my", "we", "our", "you", "your", "he", "him",
        "his", "she", "her", "they", "them", "their", "what", "which", "who",
    }

    def __init__(self, custom_entity_patterns: Optional[Dict[str, re.Pattern]] = None):
        self._custom_patterns = custom_entity_patterns or {}

    def extract_entities(self, text: str) -> List[ExtractedEntity]:
        """Extract all entities from text."""
        entities = []
        entities.extend(self._extract_by_pattern(text, self.EMAIL_PATTERN, EntityType.EMAIL, 0.9))
        entities.extend(self._extract_by_pattern(text, self.URL_PATTERN, EntityType.URL, 0.85))
        entities.extend(self._extract_by_pattern(text, self.PHONE_PATTERN, EntityType.PHONE, 0.7))
        entities.extend(self._extract_by_pattern(text, self.DATE_PATTERN, EntityType.DATE, 0.8))
        entities.extend(self._extract_by_pattern(text, self.FILE_REF_PATTERN, EntityType.FILE_REF, 0.85))
        entities.extend(self._extract_by_pattern(text, self.CODE_REF_PATTERN, EntityType.CODE_REF, 0.6))

        # Extract capitalized phrases as potential persons/organizations/locations
        entities.extend(self._extract_capitalized_phrases(text))

        # Custom patterns
        for name, pattern in self._custom_patterns.items():
            for match in pattern.finditer(text):
                entities.append(ExtractedEntity(
                    text=match.group(),
                    entity_type=EntityType.CUSTOM,
                    confidence=0.7,
                    start_pos=match.start(),
                    end_pos=match.end(),
                    metadata={"pattern_name": name},
                ))

        return self._deduplicate_entities(entities)

    def extract_concepts(self, text: str, top_k: int = 20) -> List[ExtractedConcept]:
        """Extract key concepts/topics from text using TF scoring."""
        sentences = self._split_sentences(text)
        words = []
        for sentence in sentences:
            tokens = re.findall(r'\b[a-zA-Z]{3,}\b', sentence)
            words.extend(t.lower() for t in tokens if t.lower() not in self.STOPWORDS)

        word_freq = Counter(words)
        if not word_freq:
            return []

        max_freq = max(word_freq.values())
        concepts = []
        for word, freq in word_freq.most_common(top_k * 2):
            weight = freq / max_freq
            # Find context
            context = ""
            for s in sentences:
                if word in s.lower():
                    context = s.strip()
                    break
            concepts.append(ExtractedConcept(term=word, weight=weight, context=context))
            if len(concepts) >= top_k:
                break

        return concepts

    def extract_claims(self, text: str) -> List[ExtractedClaim]:
        """Extract factual claims from text."""
        sentences = self._split_sentences(text)
        claims = []
        claim_indicators = [
            (r'\b(?:is|are|was|were)\b', "assertion", 0.6),
            (r'\b(?:\d+(?:\.\d+)?)\b', "numerical", 0.7),
            (r'\b(?:always|never|every|all|none)\b', "universal", 0.5),
            (r'\b(?:approximately|about|roughly|estimated)\b', "approximate", 0.4),
            (r'\b(?:study|research|data|evidence)\s+(?:shows?|indicates?|suggests?)\b', "empirical", 0.7),
        ]

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue

            best_type = "assertion"
            best_conf = 0.3
            for pattern, claim_type, base_conf in claim_indicators:
                if re.search(pattern, sentence, re.IGNORECASE):
                    if base_conf > best_conf:
                        best_conf = base_conf
                        best_type = claim_type

            # Extract evidence spans (numbers, dates, names)
            evidence_spans = []
            for match in self.NUMBER_PATTERN.finditer(sentence):
                evidence_spans.append(match.group())
            for match in self.DATE_PATTERN.finditer(sentence):
                evidence_spans.append(match.group())

            claims.append(ExtractedClaim(
                text=sentence,
                claim_type=best_type,
                confidence=best_conf,
                evidence_span="; ".join(evidence_spans),
                source_sentence=sentence,
            ))

        return claims

    def extract_relationships(self, text: str) -> List[ExtractedRelationship]:
        """Extract relationships between entities in text."""
        entities = self.extract_entities(text)
        entity_texts = {e.text.lower(): e.text for e in entities}
        sentences = self._split_sentences(text)
        relationships = []

        for sentence in sentences:
            sentence_lower = sentence.lower()
            for rel_type, indicators in self.RELATIONSHIP_INDICATORS.items():
                for indicator in indicators:
                    if indicator in sentence_lower:
                        # Find entities on each side of the indicator
                        parts = sentence_lower.split(indicator, 1)
                        if len(parts) == 2:
                            source_entities = self._find_entities_in_text(parts[0], entity_texts)
                            target_entities = self._find_entities_in_text(parts[1], entity_texts)
                            for src in source_entities:
                                for tgt in target_entities:
                                    if src != tgt:
                                        relationships.append(ExtractedRelationship(
                                            source=src,
                                            target=tgt,
                                            relation_type=rel_type,
                                            confidence=0.6,
                                            evidence=sentence.strip(),
                                        ))

        return self._deduplicate_relationships(relationships)

    def extract_all(self, text: str) -> Dict[str, Any]:
        """Extract all knowledge types from text in one call."""
        return {
            "entities": [e.to_dict() for e in self.extract_entities(text)],
            "concepts": [c.to_dict() for c in self.extract_concepts(text)],
            "claims": [cl.to_dict() for cl in self.extract_claims(text)],
            "relationships": [r.to_dict() for r in self.extract_relationships(text)],
        }

    def _extract_by_pattern(
        self, text: str, pattern: re.Pattern, entity_type: EntityType, confidence: float
    ) -> List[ExtractedEntity]:
        entities = []
        for match in pattern.finditer(text):
            entities.append(ExtractedEntity(
                text=match.group(),
                entity_type=entity_type,
                confidence=confidence,
                start_pos=match.start(),
                end_pos=match.end(),
            ))
        return entities

    def _extract_capitalized_phrases(self, text: str) -> List[ExtractedEntity]:
        """Extract capitalized word sequences as potential named entities."""
        pattern = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b')
        entities = []
        seen = set()
        for match in pattern.finditer(text):
            phrase = match.group()
            if phrase in seen or len(phrase) < 3:
                continue
            seen.add(phrase)
            # Simple heuristic: multi-word capitalized = organization, single = person/location
            words = phrase.split()
            if len(words) >= 2:
                etype = EntityType.ORGANIZATION
                conf = 0.5
            else:
                etype = EntityType.PERSON
                conf = 0.4
            entities.append(ExtractedEntity(
                text=phrase,
                entity_type=etype,
                confidence=conf,
                start_pos=match.start(),
                end_pos=match.end(),
            ))
        return entities

    def _find_entities_in_text(self, text_fragment: str, entity_texts: Dict[str, str]) -> List[str]:
        """Find which known entities appear in a text fragment."""
        found = []
        for entity_lower, entity_original in entity_texts.items():
            if entity_lower in text_fragment:
                found.append(entity_original)
        return found

    def _deduplicate_entities(self, entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
        seen = set()
        result = []
        for e in entities:
            key = (e.text.lower(), e.entity_type.value)
            if key not in seen:
                seen.add(key)
                result.append(e)
        return result

    def _deduplicate_relationships(self, rels: List[ExtractedRelationship]) -> List[ExtractedRelationship]:
        seen = set()
        result = []
        for r in rels:
            key = (r.source.lower(), r.target.lower(), r.relation_type)
            if key not in seen:
                seen.add(key)
                result.append(r)
        return result

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        return re.split(r'(?<=[.!?])\s+', text)
