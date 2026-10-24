"""Scoped evidence retrieval for the DataOS knowledge graph."""
from __future__ import annotations
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")
STOP_WORDS = {"about","after","again","also","and","are","been","before","between","both","but","can","could","does","for","from","have","into","its","more","most","not","our","out","over","same","should","some","such","than","that","the","their","them","then","there","these","they","this","those","through","under","use","using","was","were","what","when","where","which","while","who","why","will","with","would","you","your"}

class KnowledgeQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    selected_file_ids: List[str] = Field(min_length=1, max_length=200)
    include_related: bool = True
    max_related_files: int = Field(default=10, ge=0, le=50)
    min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)

def _flatten(value: Any, limit: int = 120000) -> str:
    if value is None: return ""
    if isinstance(value, str): return value[:limit]
    try: return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:limit]
    except (TypeError, ValueError): return str(value)[:limit]

def object_text(obj: Any) -> str:
    props = getattr(obj, "properties", None) or {}
    parts = [_flatten(props.get(k), 30000) for k in ("filename","name","title","description","summary","text","extracted_text","raw_text","content_text","raw_csv") if isinstance(props, dict) and props.get(k) is not None]
    content = getattr(obj, "content", None)
    if content is not None: parts.append(_flatten(content, 100000))
    return "\n".join(p for p in parts if p).strip()[:120000]

def query_terms(query: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(query) if t.lower() not in STOP_WORDS]

def rank_text(query: str, text: str) -> float:
    terms = set(query_terms(query))
    if not terms or not text: return 0.0
    lowered = text.lower()
    matched = [t for t in terms if t in lowered]
    if not matched: return 0.0
    coverage = len(matched) / len(terms)
    frequency = sum(min(lowered.count(t), 4) for t in matched)
    return round(0.8 * coverage + 0.2 * min(frequency / max(1, len(terms) * 2), 1.0), 4)

def extract_snippet(text: str, query: str, max_chars: int = 720) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars: return compact
    lowered = compact.lower()
    hits = [lowered.find(t) for t in query_terms(query) if lowered.find(t) >= 0]
    if not hits: return compact[:max_chars].rstrip() + "…"
    start = max(0, min(hits) - max_chars // 4)
    if start > 0:
        boundary = compact.find(" ", start)
        start = boundary if boundary >= 0 else 0
    end = min(len(compact), start + max_chars)
    if end < len(compact):
        boundary = compact.rfind(" ", start, end)
        if boundary > start: end = boundary
    return ("…" if start else "") + compact[start:end].strip() + ("…" if end < len(compact) else "")

def _relation_dict(rel: Any) -> Dict[str, Any]:
    if isinstance(rel, dict): return rel
    method = getattr(rel, "to_dict", None)
    if callable(method):
        value = method()
        return value if isinstance(value, dict) else {}
    return {"source_id": getattr(rel, "source_id", None), "target_id": getattr(rel, "target_id", None), "relation_type": getattr(rel, "relation_type", "related_to"), "confidence": getattr(rel, "confidence", 1.0)}

def resolve_related_files(selected_ids: Sequence[str], relationships: Iterable[Any], max_related_files: int = 10, min_confidence: float = 0.75) -> List[Dict[str, Any]]:
    selected = set(selected_ids)
    candidates: Dict[str, Dict[str, Any]] = {}
    for raw in relationships:
        rel = _relation_dict(raw)
        source, target = rel.get("source_id") or rel.get("source"), rel.get("target_id") or rel.get("target")
        if not source or not target: continue
        try: confidence = float(rel.get("confidence", 1.0))
        except (TypeError, ValueError): confidence = 0.0
        if confidence < min_confidence: continue
        neighbor = target if source in selected and target not in selected else source if target in selected and source not in selected else None
        if not neighbor: continue
        candidate = {"file_id": neighbor, "confidence": confidence, "relationship_type": str(rel.get("relation_type") or rel.get("type") or "related_to"), "connected_to": source if source in selected else target}
        if neighbor not in candidates or confidence > candidates[neighbor]["confidence"]: candidates[neighbor] = candidate
    return sorted(candidates.values(), key=lambda x: (-x["confidence"], x["file_id"]))[:max_related_files]

def create_knowledge_router(dataos: Any) -> APIRouter:
    router = APIRouter(tags=["Knowledge Graph RAG"])
    @router.post("/api/knowledge/query", summary="Retrieve evidence from selected and related files")
    async def query_knowledge(req: KnowledgeQueryRequest) -> Dict[str, Any]:
        selected_ids = list(dict.fromkeys(req.selected_file_ids))
        selected: Dict[str, Any] = {}
        missing = []
        for file_id in selected_ids:
            obj = dataos.storage.get_object(file_id)
            if obj is None: missing.append(file_id)
            else: selected[file_id] = obj
        if missing:
            raise HTTPException(status_code=404, detail={"message":"One or more selected files no longer exist.","missing_file_ids":missing})
        relationships: List[Any] = []
        if req.include_related and req.max_related_files:
            seen = set()
            for file_id in selected_ids:
                for kwargs in ({"source_id":file_id,"limit":5000},{"target_id":file_id,"limit":5000}):
                    try: batch = dataos.storage.list_relationships(**kwargs) or []
                    except (TypeError, ValueError): batch = []
                    for item in batch:
                        rel = _relation_dict(item)
                        key = (rel.get("id"), rel.get("source_id") or rel.get("source"), rel.get("target_id") or rel.get("target"), rel.get("relation_type") or rel.get("type"))
                        if key not in seen: seen.add(key); relationships.append(rel)
        related = resolve_related_files(selected_ids, relationships, req.max_related_files if req.include_related else 0, req.min_confidence)
        related_objects = {item["file_id"]: dataos.storage.get_object(item["file_id"]) for item in related}
        related_objects = {k:v for k,v in related_objects.items() if v is not None}
        eligible = {**selected, **related_objects}
        evidence = []
        for file_id, obj in eligible.items():
            text = object_text(obj)
            score = rank_text(req.query, text)
            if not text or score <= 0: continue
            props = getattr(obj, "properties", None) or {}
            rel_info = next((x for x in related if x["file_id"] == file_id), None)
            evidence.append({"file_id":file_id,"name":str(props.get("filename") or props.get("name") or props.get("title") or file_id),"score":score,"excerpt":extract_snippet(text, req.query),"selected":file_id in selected,"inclusion_reason":"explicitly selected" if file_id in selected else f'{rel_info["relationship_type"]} ({rel_info["confidence"]:.2f})',"relationship":rel_info})
        evidence = sorted(evidence, key=lambda x: (-x["score"], not x["selected"], x["name"].lower()))[:12]
        related_response = []
        for item in related:
            obj = related_objects.get(item["file_id"])
            if obj is not None:
                props = getattr(obj, "properties", None) or {}
                related_response.append({**item,"name":str(props.get("filename") or props.get("name") or item["file_id"])})
        return {
            "query":req.query,"mode":"scoped_evidence_retrieval","selected_file_ids":selected_ids,
            "related_files":related_response,"eligible_file_ids":list(eligible),"eligible_file_count":len(eligible),
            "evidence":evidence,
            "answer":f"Retrieved {len(evidence)} matching evidence passages from {len(eligible)} eligible files. Results are restricted to selected files and the configured one-hop related-file set." if evidence else "No matching text was found inside the selected files or their eligible related files. Try a more specific query or inspect the stored document content.",
            "generation_available":False,
            "generation_note":"This endpoint currently performs scope-constrained evidence retrieval. Provider-backed answer synthesis is not wired into the current DataOS API, so it does not call the global /api/ask endpoint or claim an LLM-generated answer."
        }
    return router
