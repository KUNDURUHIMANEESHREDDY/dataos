"""Regression tests for principal-scoped reads in the Python reference API."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend.app as api
from backend.knowledge_rag import KnowledgeQueryRequest, create_knowledge_router
from backend.object_acl import can_read_object, list_readable_objects
from engines.search.search_engine import HybridSearchEngine


def user(principal_id: str, role: str = "viewer"):
    return SimpleNamespace(id=principal_id, role=role)


def obj(object_id: str, *, owner: str = "", read=(), write=()):
    return SimpleNamespace(
        id=object_id,
        type="document",
        source="test://fixture",
        schema="generic.v1",
        properties={"title": object_id},
        content={"text": object_id},
        permissions={"owner": owner, "read": list(read), "write": list(write)},
        to_dict=lambda: {
            "id": object_id,
            "permissions": {"owner": owner, "read": list(read), "write": list(write)},
        },
    )


class MemoryStorage:
    def __init__(self, objects, relationships=()):
        self.objects = list(objects)
        self.relationships = list(relationships)

    def list_objects(self, object_type=None, source=None, limit=100, offset=0):
        rows = self.objects
        if object_type:
            rows = [item for item in rows if item.type == object_type]
        if source:
            rows = [item for item in rows if source in item.source]
        return rows[offset:offset + limit]

    def list_relationships(
        self, source_id=None, target_id=None, relation_type=None,
        min_confidence=0.0, limit=1000, offset=0,
    ):
        rows = self.relationships
        if source_id:
            rows = [item for item in rows if item.source == source_id]
        if target_id:
            rows = [item for item in rows if item.target == target_id]
        if relation_type:
            rows = [item for item in rows if item.relation_type == relation_type]
        return rows[offset:offset + limit]

    def get_object(self, object_id):
        return next((item for item in self.objects if item.id == object_id), None)


def run(awaitable):
    return asyncio.run(awaitable)


def test_acl_owner_reader_wildcard_admin_and_write_only_semantics():
    alice = user("alice")
    assert can_read_object(obj("owned", owner="alice"), alice)
    assert can_read_object(obj("shared", read=["alice"]), alice)
    assert can_read_object(obj("public", read=["*"]), alice)
    assert not can_read_object(obj("write-only", write=["alice"]), alice)
    assert not can_read_object(obj("private", owner="bob", read=["bob"]), alice)
    assert can_read_object(obj("private", owner="bob", read=["bob"]), user("root", "admin"))


def test_list_readable_objects_filters_before_api_pagination():
    storage = MemoryStorage([
        obj("private-a", owner="bob", read=["bob"]),
        obj("visible-a", owner="alice", read=["alice"]),
        obj("private-b", owner="bob", read=["bob"]),
        obj("visible-b", owner="alice", read=["alice"]),
    ])
    visible = list_readable_objects(storage, user("alice"))
    assert [item.id for item in visible] == ["visible-a", "visible-b"]


def test_authorized_scan_fails_closed_when_collection_exceeds_bound():
    class LargeStorage:
        def list_objects(self, object_type=None, source=None, limit=100, offset=0):
            if offset >= 20_000:
                return [obj("overflow", owner="alice", read=["alice"])]
            return [obj(f"row-{index}", owner="alice", read=["alice"]) for index in range(offset, offset + limit)]

    with pytest.raises(HTTPException) as exc:
        list_readable_objects(LargeStorage(), user("alice"))
    assert exc.value.status_code == 503
    assert "cannot safely authorize" in exc.value.detail


def test_python_api_list_paginates_only_after_acl_filtering(monkeypatch):
    storage = MemoryStorage([
        obj("private", owner="bob", read=["bob"]),
        obj("visible-1", owner="alice", read=["alice"]),
        obj("visible-2", owner="alice", read=["alice"]),
    ])
    monkeypatch.setattr(api.dataos, "storage", storage)
    result = run(api.list_objects(limit=1, offset=1, current_user=user("alice")))
    assert result["total"] == 2
    assert [item["id"] for item in result["objects"]] == ["visible-2"]


def test_python_api_object_get_conceals_private_object(monkeypatch):
    storage = MemoryStorage([obj("private", owner="bob", read=["bob"])])
    monkeypatch.setattr(api.dataos, "storage", storage)
    with pytest.raises(HTTPException) as exc:
        run(api.get_object("private", current_user=user("alice")))
    assert exc.value.status_code == 404


def test_python_api_vector_search_is_scoped_to_readable_object_ids(monkeypatch):
    storage = MemoryStorage([
        obj("visible", owner="alice", read=["alice"]),
        obj("private", owner="bob", read=["bob"]),
    ])
    monkeypatch.setattr(api.dataos, "storage", storage)
    captured = {}

    def search_similar(**kwargs):
        captured.update(kwargs)
        return [{"object_id": "visible", "similarity": 1.0}]

    monkeypatch.setattr(api.dataos.vector_index, "search_similar", search_similar)
    result = run(api.search_vectors(q="sales", top_k=5, current_user=user("alice")))
    assert captured["object_ids"] == ["visible"]
    assert result["results"][0]["object_id"] == "visible"


def test_python_api_hybrid_search_passes_acl_filter_to_engine(monkeypatch):
    storage = MemoryStorage([
        obj("visible", owner="alice", read=["alice"]),
        obj("private", owner="bob", read=["bob"]),
    ])
    monkeypatch.setattr(api.dataos, "storage", storage)
    captured = {}

    def search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(api.dataos.search_engine, "search", search)
    run(api.hybrid_search(q="sales", current_user=user("alice")))
    assert captured["object_ids"] == {"visible"}


def test_hybrid_engine_filters_candidates_before_returning_objects():
    visible = obj("visible", owner="alice", read=["alice"])
    private = obj("private", owner="bob", read=["bob"])
    engine = HybridSearchEngine(MemoryStorage([visible, private]))
    results = engine.search("visible", object_ids={"visible"})
    assert [item["object_id"] for item in results] == ["visible"]


def test_python_api_relationship_list_hides_edges_with_private_endpoints(monkeypatch):
    visible = obj("visible", owner="alice", read=["alice"])
    private = obj("private", owner="bob", read=["bob"])
    rel_visible = SimpleNamespace(source="visible", target="visible", relation_type="references", to_dict=lambda: {"source": "visible", "target": "visible"})
    rel_private = SimpleNamespace(source="visible", target="private", relation_type="references", to_dict=lambda: {"source": "visible", "target": "private"})
    storage = MemoryStorage([visible, private], [rel_visible, rel_private])
    monkeypatch.setattr(api.dataos, "storage", storage)
    result = run(api.list_relationships(current_user=user("alice")))
    assert result["total"] == 1
    assert result["relationships"] == [{"source": "visible", "target": "visible"}]


def test_python_api_neighbors_hide_private_nodes_and_edges(monkeypatch):
    storage = MemoryStorage([
        obj("root", owner="alice", read=["alice"]),
        obj("visible", owner="alice", read=["alice"]),
        obj("private", owner="bob", read=["bob"]),
    ])
    monkeypatch.setattr(api.dataos, "storage", storage)
    monkeypatch.setattr(api.dataos.graph, "neighbors", lambda object_id, direction, allowed_object_ids=None: [
        {"neighbor_id": "visible", "neighbor_object": {"id": "visible"}},
        {"neighbor_id": "private", "neighbor_object": {"id": "private"}},
    ])
    result = run(api.get_neighbors("root", current_user=user("alice")))
    assert result["total"] == 1
    assert result["neighbors"] == [{"neighbor_id": "visible", "neighbor_object": {"id": "visible"}}]


def test_knowledge_retrieval_hides_unreadable_selected_and_related_objects():
    selected = obj("selected", owner="alice", read=["alice"])
    private = obj("private", owner="bob", read=["bob"])
    relation = SimpleNamespace(
        id="edge-1", source="selected", target="private",
        relation_type="related_to", confidence=0.99,
    )
    storage = MemoryStorage([selected, private], [relation])
    dataos = SimpleNamespace(storage=storage)
    async def resolve_user():
        return user("alice")
    router = create_knowledge_router(dataos, current_user_dependency=resolve_user)
    endpoint = router.routes[0].endpoint
    result = run(endpoint(
        KnowledgeQueryRequest(query="selected", selected_file_ids=["selected"]),
        current_user=user("alice"),
    ))
    assert result["related_files"] == []
    assert result["eligible_file_ids"] == ["selected"]
    assert "private" not in str(result)


def test_knowledge_retrieval_conceals_private_selected_id():
    selected = obj("private", owner="bob", read=["bob"])
    storage = MemoryStorage([selected])
    router = create_knowledge_router(SimpleNamespace(storage=storage))
    endpoint = router.routes[0].endpoint
    with pytest.raises(HTTPException) as exc:
        run(endpoint(
            KnowledgeQueryRequest(query="secret", selected_file_ids=["private"]),
            current_user=user("alice"),
        ))
    assert exc.value.status_code == 404


def test_graph_engine_never_traverses_through_private_intermediate_nodes():
    from engines.graph.engine import GraphEngine

    root = obj("root", owner="alice", read=["alice"])
    private = obj("private", owner="bob", read=["bob"])
    public_descendant = obj("public-descendant", owner="alice", read=["alice"])
    root_to_private = SimpleNamespace(
        source="root", target="private", relation_type="references",
        confidence=1.0, to_dict=lambda: {"source": "root", "target": "private"},
    )
    private_to_public = SimpleNamespace(
        source="private", target="public-descendant", relation_type="references",
        confidence=1.0, to_dict=lambda: {"source": "private", "target": "public-descendant"},
    )
    engine = GraphEngine(MemoryStorage(
        [root, private, public_descendant],
        [root_to_private, private_to_public],
    ))

    neighbors = engine.get_neighbors("root", allowed_object_ids={"root", "public-descendant"})
    assert neighbors == []

    result = engine.traverse(
        "root",
        max_hops=3,
        allowed_object_ids={"root", "public-descendant"},
    )
    assert [node["id"] for node in result["nodes"]] == ["root"]
    assert result["edges"] == []
    assert result["paths"] == []


def test_hybrid_search_rejects_private_context_object(monkeypatch):
    storage = MemoryStorage([
        obj("visible", owner="alice", read=["alice"]),
        obj("private-context", owner="bob", read=["bob"]),
    ])
    monkeypatch.setattr(api.dataos, "storage", storage)
    called = {"value": False}

    def search(**kwargs):
        called["value"] = True
        return []

    monkeypatch.setattr(api.dataos.search_engine, "search", search)
    with pytest.raises(HTTPException) as exc:
        run(api.hybrid_search(q="sales", context_id="private-context", current_user=user("alice")))
    assert exc.value.status_code == 404
    assert called["value"] is False


def test_write_acl_is_separate_from_read_acl():
    from backend.object_acl import can_write_object

    alice = user("alice")
    write_only = obj("write-only", owner="bob", read=["bob"], write=["alice"])
    assert can_write_object(write_only, alice)
    assert not can_read_object(write_only, alice)


def test_api_create_object_assigns_private_creator_acl(monkeypatch):
    saved = []
    monkeypatch.setattr(api.dataos.storage, "save_object", lambda item: saved.append(item) or item)
    request = api.ObjectCreateRequest(type="document", content={"text": "private"})
    result = run(api.create_object(request, current_user=user("alice")))
    assert result["permissions"] == {"owner": "alice", "read": ["alice"], "write": ["alice"]}
    assert saved[0].permissions == {"owner": "alice", "read": ["alice"], "write": ["alice"]}


def test_api_delete_object_requires_write_access(monkeypatch):
    private = obj("private", owner="bob", read=["alice"], write=["bob"])
    deleted = {"called": False}
    monkeypatch.setattr(api.dataos.storage, "get_object", lambda object_id: private)
    monkeypatch.setattr(api.dataos.storage, "delete_object", lambda *args, **kwargs: deleted.update(called=True) or True)
    with pytest.raises(HTTPException) as exc:
        run(api.delete_object("private", current_user=user("alice")))
    assert exc.value.status_code == 404
    assert deleted["called"] is False


def test_api_create_relationship_requires_write_access_to_both_endpoints(monkeypatch):
    source = obj("source", owner="alice", read=["alice"], write=["alice"])
    target = obj("target", owner="bob", read=["alice"], write=["bob"])
    objects = {"source": source, "target": target}
    monkeypatch.setattr(api.dataos.storage, "get_object", lambda object_id: objects.get(object_id))
    created = {"called": False}
    monkeypatch.setattr(
        api.dataos.graph,
        "create_relation",
        lambda **kwargs: created.update(called=True) or SimpleNamespace(to_dict=lambda: {}),
    )
    request = api.RelationCreateRequest(source_id="source", target_id="target")
    with pytest.raises(HTTPException) as exc:
        run(api.create_relationship(request, current_user=user("alice")))
    assert exc.value.status_code == 404
    assert created["called"] is False
