import asyncio
import unittest
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.knowledge_rag import (
    KnowledgeQueryRequest,
    create_knowledge_router,
    extract_snippet,
    rank_text,
    resolve_related_files,
)
from backend.sql_authorization import can_read_object


class KnowledgeAuthorizationStorage:
    def __init__(self, objects, relationships=()):
        self.objects = {obj.id: obj for obj in objects}
        self.relationships = list(relationships)

    def get_object(self, object_id):
        return self.objects.get(object_id)

    def list_relationships(self, source_id=None, target_id=None, limit=5000):
        return [
            rel for rel in self.relationships
            if (source_id is None or rel["source_id"] == source_id)
            and (target_id is None or rel["target_id"] == target_id)
        ][:limit]


def knowledge_object(object_id, owner, text, readers=()):
    return SimpleNamespace(
        id=object_id,
        properties={"filename": f"{object_id}.txt", "text": text},
        content=None,
        permissions={"owner": owner, "read": list(readers), "write": [owner]},
    )


def knowledge_endpoint(storage):
    router = create_knowledge_router(
        SimpleNamespace(storage=storage),
        get_current_user=lambda: None,
        requires_identity=lambda user: user is None,
        can_read_object=can_read_object,
    )
    return router.routes[0].endpoint


def test_knowledge_query_rejects_selected_objects_owned_by_another_user():
    storage = KnowledgeAuthorizationStorage([
        knowledge_object("private", "bob", "project launch details"),
    ])
    endpoint = knowledge_endpoint(storage)
    alice = SimpleNamespace(id="alice", role="analyst")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(endpoint(
            KnowledgeQueryRequest(query="project launch", selected_file_ids=["private"]),
            current_user=alice,
        ))

    assert exc.value.status_code == 404
    assert "private" in exc.value.detail["missing_file_ids"]


def test_knowledge_query_filters_private_related_objects_before_retrieval():
    selected = knowledge_object("selected", "alice", "project launch evidence")
    private_related = knowledge_object("private-related", "bob", "project launch secret")
    storage = KnowledgeAuthorizationStorage(
        [selected, private_related],
        relationships=[{
            "source_id": "selected",
            "target_id": "private-related",
            "confidence": 0.99,
            "relation_type": "references",
        }],
    )
    endpoint = knowledge_endpoint(storage)
    alice = SimpleNamespace(id="alice", role="analyst")

    result = asyncio.run(endpoint(
        KnowledgeQueryRequest(query="project launch", selected_file_ids=["selected"]),
        current_user=alice,
    ))

    assert result["eligible_file_ids"] == ["selected"]
    assert result["related_files"] == []
    assert all(item["file_id"] != "private-related" for item in result["evidence"])


def test_knowledge_query_requires_identity_when_production_policy_requires_it():
    storage = KnowledgeAuthorizationStorage([])
    endpoint = knowledge_endpoint(storage)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(endpoint(
            KnowledgeQueryRequest(query="anything", selected_file_ids=["missing"]),
            current_user=None,
        ))

    assert exc.value.status_code == 401


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
