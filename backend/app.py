"""
DataOS — Universal Data Operating System
FastAPI Backend REST API (Rule #33).
API-First architecture exposing objects, graph, compute, intelligence,
search, provenance, agents, workflows, and catalog to the web frontend and external clients.
"""

from __future__ import annotations
import os
import uuid
import datetime
import hmac
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header, Request, Query as FastQuery
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from dataos_system import DataOS
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from core.permissions.policy import Capability
from backend.knowledge_rag import create_knowledge_router
from backend.cors_config import cors_middleware_options
from backend.workflow_api import WorkflowRequestError, execute_safe_workflow
from runtime.workflows.workflow_engine import WorkflowEngine

def require_production_api_token(request: Request, authorization: Optional[str] = Header(default=None)) -> None:
    """Require a high-entropy bearer token for API routes in production.

    All supported environment markers are checked so a conflicting development
    marker cannot accidentally disable production authentication. The health
    route outside /api remains available for liveness monitoring.
    """
    if not request.url.path.startswith("/api/"):
        return

    production_markers = (
        os.getenv("DATAOS_ENV", ""),
        os.getenv("APP_ENV", ""),
        os.getenv("ENVIRONMENT", ""),
    )
    if not any(marker.strip().lower() in {"production", "prod"} for marker in production_markers):
        return

    expected = os.getenv("DATAOS_API_TOKEN", "")
    if not expected or expected.strip() != expected or len(expected.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail="Production API authentication is unavailable; configure DATAOS_API_TOKEN with at least 32 UTF-8 bytes.",
        )

    scheme, separator, supplied = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail="A valid bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Initialize single DataOS kernel
dataos = DataOS(db_path="dataos.db", blob_dir=".dataos_blobs")
workflow_engine = WorkflowEngine(storage=dataos.storage)

app = FastAPI(
    title="DataOS Universal Data Operating System API",
    description="""
    API-first interface for DataOS — a universal, graph-based, computable data operating system.
    All operations are deterministic, verifiable against real data, and fully traceable.
    """,
    version="1.0.0",
    dependencies=[Depends(require_production_api_token)],
)

app.add_middleware(
    CORSMiddleware,
    **cors_middleware_options(os.getenv("DATAOS_CORS_ORIGINS")),
)


app.include_router(create_knowledge_router(dataos))


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================

class ObjectCreateRequest(BaseModel):
    type: str = "document"
    schema_ref: str = "generic.v1"
    properties: Dict[str, Any] = Field(default_factory=dict)
    content: Any = Field(default_factory=dict)
    source: str = "api://user"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RelationCreateRequest(BaseModel):
    source_id: str
    target_id: str
    relation_type: str = "references"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SQLQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    agent_or_user: str = "api_user"


class PythonComputeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100000)
    input_object_ids: List[str] = Field(default_factory=list)
    agent_or_user: str = "api_user"


class UnifiedQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    query_type: str = "auto"
    context_object_id: Optional[str] = None
    agent_or_user: str = "api_user"


class QualityEvaluateRequest(BaseModel):
    rules: List[Dict[str, Any]] = Field(default_factory=list)


class AgentExecutionRequest(BaseModel):
    agent_id: str
    capability: str
    params: Dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionRequest(BaseModel):
    definition: Dict[str, Any]
    context: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# OBJECT ROUTES
# =============================================================================

@app.get("/api/objects/", summary="List DataOS Objects")
async def list_objects(
    object_type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    objs = dataos.storage.list_objects(object_type=object_type, source=source, limit=limit, offset=offset)
    return {"total": len(objs), "objects": [o.to_dict() for o in objs]}


@app.post("/api/objects/", summary="Create DataOS Object")
async def create_object(req: ObjectCreateRequest):
    obj = DataObject(
        type=req.type,
        schema=req.schema_ref,
        properties=req.properties,
        content=req.content,
        source=req.source,
        metadata=req.metadata
    )
    saved = dataos.storage.save_object(obj)
    return saved.to_dict()


@app.get("/api/objects/{object_id}", summary="Get DataOS Object")
async def get_object(object_id: str):
    obj = dataos.storage.get_object(object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    return obj.to_dict()


@app.delete("/api/objects/{object_id}", summary="Delete DataOS Object")
async def delete_object(object_id: str, soft: bool = True):
    success = dataos.storage.delete_object(object_id, soft=soft)
    if not success:
        raise HTTPException(status_code=404, detail="Object not found or already deleted")
    return {"status": "deleted", "object_id": object_id, "soft": soft}


# =============================================================================
# RELATIONSHIP & GRAPH ROUTES
# =============================================================================

@app.get("/api/relationships/", summary="List Relationships")
async def list_relationships(
    source_id: Optional[str] = None,
    target_id: Optional[str] = None,
    relation_type: Optional[str] = None,
    min_confidence: float = 0.0,
    limit: int = 1000
):
    rels = dataos.storage.list_relationships(
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        min_confidence=min_confidence,
        limit=limit
    )
    return {"total": len(rels), "relationships": [r.to_dict() for r in rels]}


@app.post("/api/relationships/", summary="Create Relationship")
async def create_relationship(req: RelationCreateRequest):
    rel = dataos.graph.create_relation(
        source_id=req.source_id,
        target_id=req.target_id,
        relation_type=req.relation_type,
        confidence=req.confidence,
        metadata=req.metadata
    )
    return rel.to_dict()


@app.get("/api/graph/neighbors/{object_id}", summary="Get Object Neighbors")
async def get_neighbors(object_id: str, direction: str = "both"):
    neighbors = dataos.graph.neighbors(object_id, direction=direction)
    return {"object_id": object_id, "total": len(neighbors), "neighbors": neighbors}


@app.get("/api/graph/traverse/{object_id}", summary="Multi-Hop Graph Traversal")
async def traverse_graph(
    object_id: str,
    max_hops: int = FastQuery(default=3, ge=1, le=10),
    min_confidence: float = FastQuery(default=0.0, ge=0.0, le=1.0),
):
    return dataos.graph.engine.traverse(
        start_id=object_id,
        max_hops=max_hops,
        min_confidence=min_confidence,
    )


@app.get("/api/graph/analytics", summary="Graph Analytics & PageRank")
async def graph_analytics(algorithm: str = "pagerank"):
    metrics = dataos.graph.analytics()
    if algorithm == "pagerank":
        return {"algorithm": "pagerank", "scores": metrics["pagerank"]}
    if algorithm == "centrality":
        return {
            "degree_centrality": metrics["degree_centrality"],
            "betweenness_centrality": metrics["betweenness_centrality"],
        }
    if algorithm == "communities":
        return {"communities": metrics["communities"]}
    raise HTTPException(status_code=400, detail=f"Unsupported algorithm: {algorithm}")


# =============================================================================
# COMPUTATION & QUERY ROUTES
# =============================================================================

@app.post("/api/compute/sql", summary="Execute SQL Query")
async def compute_sql(req: SQLQueryRequest):
    res = dataos.sql(req.query)
    return res


@app.post("/api/compute/python", summary="Execute Python Sandbox")
async def compute_python(req: PythonComputeRequest):
    res = dataos.python(req.code, input_object_ids=req.input_object_ids)
    return res


@app.post("/api/query/", summary="Unified Query Execution")
async def query_unified(req: UnifiedQueryRequest):
    query_type = req.query_type.strip().lower()
    if query_type == "auto":
        query_type = "sql" if req.query.lstrip().lower().startswith(("select ", "with ")) else "ask"

    if query_type == "sql":
        return dataos.sql(req.query)
    if query_type == "python":
        return dataos.python(req.query)
    if query_type in {"ask", "natural_language"}:
        return dataos.ask(req.query)
    if query_type == "search":
        results = dataos.search_engine.search(
            query=req.query,
            context_object_id=req.context_object_id,
            limit=20,
        )
        return {"query": req.query, "total_matches": len(results), "results": results}
    raise HTTPException(
        status_code=400,
        detail="Unsupported query_type. Use auto, sql, python, ask, or search.",
    )


# =============================================================================
# SEARCH & PROFILING ROUTES
# =============================================================================

@app.get("/api/search/", summary="Hybrid Search")
async def hybrid_search(
    q: str = FastQuery(..., description="Search query string"),
    object_type: Optional[str] = None,
    context_id: Optional[str] = None,
    limit: int = FastQuery(default=20, ge=1, le=100)
):
    results = dataos.search_engine.search(
        query=q,
        object_type=object_type,
        context_object_id=context_id,
        limit=limit,
    )
    return {"query": q, "total_matches": len(results), "results": results}


@app.get("/api/vectors/search", summary="Persistent Vector Similarity Search (Rule #45)")
async def search_vectors(
    q: str = FastQuery(..., description="Semantic query string"),
    top_k: int = FastQuery(default=10, ge=1, le=100),
):
    results = dataos.search_vector(query_text=q, top_k=top_k)
    return {"query": q, "total_matches": len(results), "results": results}


@app.post("/api/vectors/recompute", summary="Recompute All Vector Embeddings (Rule #45)")
async def recompute_vectors():
    return dataos.vector_index.recompute_all(dataos.storage)


@app.post("/api/notebooks/ingest", summary="Ingest Jupyter Notebook DAG (Rule #51)")
async def ingest_notebook_api(
    filename: str = Form("analysis.ipynb"),
    content: str = Form(...)
):
    try:
        return dataos.ingest(content, filename=filename, discover_relations=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Notebook ingestion failed: {exc}") from exc


@app.post("/api/documents/extract_rich", summary="Extract Rich Document Tables & Citations (Rule #54)")
async def extract_rich_document_api(
    filename: str = Form("paper.md"),
    content: str = Form(...)
):
    try:
        return dataos.ingest(content, filename=filename, discover_relations=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Document ingestion failed: {exc}") from exc


# =============================================================================
# TIME-TRAVEL & BI-TEMPORAL ROUTES (Rule #27, Rule #29, Rule #59)
# =============================================================================

@app.get("/api/time_travel/object/{object_id}", summary="Time-Travel Point-in-Time Object Query (Rule #27)")
async def time_travel_object(
    object_id: str,
    as_of: str = FastQuery(..., description="Timestamp ISO string to travel to"),
    temporal_axis: str = "system_time"
):
    if temporal_axis not in {"system_time", "validity_time"}:
        raise HTTPException(status_code=400, detail="temporal_axis must be system_time or validity_time")
    obj = dataos.time_travel.get_object_as_of(object_id, as_of, temporal_axis=temporal_axis)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Object {object_id} not found as of {as_of}")
    return obj.to_dict()


@app.get("/api/time_travel/graph", summary="Time-Travel Point-in-Time Graph Topology Query (Rule #27)")
async def time_travel_graph(
    as_of: str = FastQuery(..., description="Timestamp ISO string"),
    temporal_axis: str = "system_time"
):
    if temporal_axis not in {"system_time", "validity_time"}:
        raise HTTPException(status_code=400, detail="temporal_axis must be system_time or validity_time")
    graph = dataos.time_travel.get_graph_as_of(as_of, temporal_axis=temporal_axis)
    return graph


@app.get("/api/time_travel/changes", summary="Changes Between Two Historical Timestamps (Rule #27)")
async def time_travel_changes(
    t1: str = FastQuery(..., description="Start timestamp ISO"),
    t2: str = FastQuery(..., description="End timestamp ISO"),
    temporal_axis: str = "system_time"
):
    if temporal_axis not in {"system_time", "validity_time"}:
        raise HTTPException(status_code=400, detail="temporal_axis must be system_time or validity_time")
    changes = dataos.time_travel.changes_between(t1, t2, temporal_axis=temporal_axis)
    return changes


class ConflictResolutionRequest(BaseModel):
    conflict_object_id: str
    strategy: str = "last_write_wins"
    manual_properties: Optional[Dict[str, Any]] = None


@app.post("/api/sync/resolve_conflict", summary="Explicit Conflict Resolution (Rule #59)")
async def resolve_conflict_api(req: ConflictResolutionRequest):
    try:
        res = dataos.sync.resolve_conflict(
            conflict_object_id=req.conflict_object_id,
            strategy=req.strategy,
            manual_properties=req.manual_properties
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/profiling/{object_id}", summary="Get Dataset Profile")
async def get_dataset_profile(object_id: str):
    obj = dataos.storage.get_object(object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    import pandas as pd
    import io
    df = None
    if isinstance(obj.content, list) and all(isinstance(r, dict) for r in obj.content):
        df = pd.DataFrame(obj.content)
    elif isinstance(obj.properties.get("raw_csv"), str):
        df = pd.read_csv(io.StringIO(obj.properties["raw_csv"]))
    elif isinstance(obj.properties.get("sample_rows"), list):
        df = pd.DataFrame(obj.properties["sample_rows"])

    if df is None or df.empty:
        raise HTTPException(status_code=400, detail="Object does not contain tabular dataset content")

    profile = dataos.profiler.profile_dataframe(df, dataset_name=obj.properties.get("filename", obj.id))
    return profile


@app.post("/api/quality/{object_id}", summary="Evaluate Data Quality Rules")
async def evaluate_quality(object_id: str, req: QualityEvaluateRequest):
    obj = dataos.storage.get_object(object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    import pandas as pd
    import io
    df = None
    if isinstance(obj.content, list) and all(isinstance(r, dict) for r in obj.content):
        df = pd.DataFrame(obj.content)
    elif isinstance(obj.properties.get("raw_csv"), str):
        df = pd.read_csv(io.StringIO(obj.properties["raw_csv"]))
    elif isinstance(obj.properties.get("sample_rows"), list):
        df = pd.DataFrame(obj.properties["sample_rows"])

    if df is None:
        raise HTTPException(status_code=400, detail="Object is not tabular")

    rules = req.rules if req.rules else [{"type": "row_count_min", "min_rows": 1}]
    quality_obj = dataos.quality.evaluate_rules(df, rules, target_object_id=obj.id)
    dataos.storage.save_object(quality_obj)
    return quality_obj.to_dict()


# =============================================================================
# PROVENANCE & LINEAGE ROUTES
# =============================================================================

@app.get("/api/provenance/lineage/{object_id}", summary="Data Lineage Traversal")
async def get_lineage(object_id: str, direction: str = "upstream", max_depth: int = 10):
    if direction == "upstream":
        return dataos.lineage.trace_upstream_lineage(object_id, max_depth=max_depth)
    else:
        return dataos.lineage.trace_downstream_impact(object_id, max_depth=max_depth)


# =============================================================================
# AI AGENT & WORKFLOW ROUTES (Rule #20, Rule #44, Rule #57)
# =============================================================================

class MultiAgentPipelineRequest(BaseModel):
    goal_prompt: str
    target_dataset_id: str
    analysis_sql_or_python: str
    quality_rules: Optional[List[Dict[str, Any]]] = None


@app.post("/api/agents/pipeline/research", summary="Run Composable Multi-Agent Research Pipeline (Rule #20)")
async def run_multi_agent_pipeline_api(req: MultiAgentPipelineRequest):
    res = dataos.multi_agent.run_end_to_end_research_pipeline(
        goal_prompt=req.goal_prompt,
        target_dataset_id=req.target_dataset_id,
        analysis_sql_or_python=req.analysis_sql_or_python,
        quality_rules=req.quality_rules,
    )
    return res


@app.get("/api/recommendations/connections/{object_id}", summary="Graph Recommendation & Missing Link Discovery (Rule #57)")
async def recommend_connections_api(
    object_id: str,
    top_k: int = FastQuery(default=10, ge=1, le=100),
):
    recs = dataos.graph.recommendations(object_id, top_k=top_k)
    return {"target_object_id": object_id, "recommendations": recs}


@app.get("/api/recommendations/datasets/{object_id}", summary="Recommend Relevant Datasets (Rule #57)")
async def recommend_datasets_api(
    object_id: str,
    top_k: int = FastQuery(default=5, ge=1, le=100),
):
    target = dataos.storage.get_object(object_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Object not found")
    query = str(target.properties.get("filename") or target.properties.get("title") or target.type)
    recs = dataos.search_engine.search(
        query=query,
        object_type="dataset",
        context_object_id=object_id,
        limit=top_k,
    )
    return {"target_object_id": object_id, "recommended_datasets": recs}


@app.post("/api/agents/execute", summary="Execute Agent Capability")
async def execute_agent(req: AgentExecutionRequest):
    agents = {
        "agent_research": dataos.multi_agent.research_agent,
        "agent_analysis": dataos.multi_agent.analysis_agent,
        "agent_quality": dataos.multi_agent.quality_agent,
        "agent_report": dataos.multi_agent.report_agent,
    }
    agent = agents.get(req.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown built-in agent")
    try:
        capability = Capability(req.capability)
        return agent.execute_capability(capability, req.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid capability: {req.capability}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Agent capability is not permitted") from exc


@app.post("/api/workflows/execute", summary="Execute a bounded built-in Workflow DAG")
async def execute_workflow(req: WorkflowExecutionRequest):
    try:
        return execute_safe_workflow(workflow_engine, req.definition, req.context)
    except WorkflowRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# =============================================================================
# GOVERNANCE, SHARING & FEDERATION ROUTES (Rule #58, Rule #61, Rule #64, Rule #65)
# =============================================================================

@app.get("/api/governance/duplicates", summary="Fuzzy Duplicate Detection (Rule #58)")
async def detect_duplicates_api(
    object_id: Optional[str] = None,
    min_similarity: float = 0.75
):
    raise HTTPException(
        status_code=501,
        detail="Fuzzy duplicate detection is not implemented in the current DataOS runtime.",
    )


@app.get("/api/governance/quota/{principal_id}", summary="Get Principal Quota & Usage Status (Rule #61)")
async def get_quota_status_api(principal_id: str):
    return dataos.governor.get_principal_status(principal_id)


class IssueSharingTokenRequest(BaseModel):
    issuer: str = Field(min_length=1, max_length=200)
    subject_principal: str = Field(min_length=1, max_length=200)
    subgraph_root_id: str = Field(min_length=1, max_length=200)
    allowed_object_ids: Optional[List[str]] = Field(default=None, max_length=500)
    allowed_capabilities: Optional[List[str]] = Field(default=None, max_length=50)
    duration_seconds: int = Field(default=3600, ge=1, le=86400)


@app.post("/api/sharing/issue_token", summary="Issue Cryptographically Signed Subgraph Token (Rule #65)")
async def issue_sharing_token_api(req: IssueSharingTokenRequest):
    if not os.getenv("DATAOS_SHARING_TOKEN_SECRET"):
        raise HTTPException(
            status_code=503,
            detail="Sharing tokens are disabled until DATAOS_SHARING_TOKEN_SECRET is configured.",
        )
    if not 1 <= req.duration_seconds <= 86400:
        raise HTTPException(status_code=422, detail="duration_seconds must be between 1 and 86400")
    token = dataos.tokens.issue_token(
        issuer=req.issuer,
        subject_principal=req.subject_principal,
        subgraph_root_id=req.subgraph_root_id,
        allowed_object_ids=req.allowed_object_ids,
        allowed_capabilities=req.allowed_capabilities,
        duration_seconds=req.duration_seconds,
    )
    return {"token": token, "expires_in_seconds": req.duration_seconds}


class VerifySharingTokenRequest(BaseModel):
    token: str


@app.post("/api/sharing/verify_token", summary="Verify and Decode Sharing Token (Rule #65)")
async def verify_sharing_token_api(req: VerifySharingTokenRequest):
    if not os.getenv("DATAOS_SHARING_TOKEN_SECRET"):
        raise HTTPException(
            status_code=503,
            detail="Sharing tokens are disabled until DATAOS_SHARING_TOKEN_SECRET is configured.",
        )
    try:
        payload = dataos.tokens.verify_and_decode_token(req.token)
        import dataclasses
        return {"status": "valid", "payload": dataclasses.asdict(payload)}
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/api/federation/search", summary="Federated Cross-Instance Search (Rule #64)")
async def federated_search_api(
    q: str = FastQuery(..., description="Query string"),
    top_k: int = FastQuery(default=10, ge=1, le=100),
):
    return dataos.federation.federated_search(query=q, top_k=top_k)


# =============================================================================
# EXPLANATION, IMPACT & ASK DATAOS ROUTES
# =============================================================================

@app.get("/api/objects/{object_id}/why", summary="Explain Object Origin, Provenance & Transformations")
async def explain_object_why(object_id: str):
    res = dataos.why(object_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@app.get("/api/objects/{object_id}/impact", summary="Explain Downstream Breaking Impact")
async def explain_object_impact(object_id: str):
    res = dataos.impact(object_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


class AskDataOSRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)


@app.post("/api/ask", summary="Ask DataOS Grounded System Query")
async def ask_dataos_api(req: AskDataOSRequest):
    res = dataos.ask(req.query)
    return res


@app.post("/api/ingest/universal", summary="Universal Multi-Format Ingestion")
async def universal_ingest_api(
    filename: str = Form("data_artifact"),
    content: str = Form(...),
    discover_relations: bool = Form(True)
):
    res = dataos.ingest(content, filename=filename, discover_relations=discover_relations)
    return res


# =============================================================================
# I/O, IMPORT & EXPORT ROUTES
# =============================================================================

@app.post("/api/io/ingest_text", summary="Ingest Text Content directly")
async def ingest_text(
    filename: str = Form(...),
    content: str = Form(...),
    format_type: str = Form("text")
):
    # Ingest content directly; never construct a temporary path from client input.
    safe_name = os.path.basename(filename.strip().replace("\\", "/")) or "text.txt"
    if not os.path.splitext(safe_name)[1]:
        safe_name = f"{safe_name}.txt"
    return dataos.ingest(content, filename=safe_name, discover_relations=True)


@app.get("/api/io/export", summary="Export DataOS Graph")
async def export_graph(format: str = "json_ld"):
    if format == "json_ld":
        return dataos.exporter.export_json_ld()
    elif format == "graphml":
        return PlainTextResponse(dataos.exporter.export_graphml(), media_type="application/xml")
    elif format == "dot":
        return PlainTextResponse(dataos.exporter.export_dot(), media_type="text/plain")
    elif format == "sql":
        return PlainTextResponse(dataos.exporter.export_sql_dump(), media_type="text/plain")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")


# =============================================================================
# CATALOG & HEALTH ROUTES
# =============================================================================

@app.get("/api/catalog/health", summary="System Health & Catalog Overview")
async def get_health_overview():
    try:
        # A bounded read verifies that the configured storage backend is reachable.
        dataos.storage.list_objects(limit=1)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="DataOS storage is unavailable") from exc
    return {
        "status": "operational",
        "storage_backend": type(dataos.storage).__name__,
        "storage_reachable": True,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@app.get("/health", summary="Basic Health Check")
async def health_check():
    return await get_health_overview()


# =============================================================================
# STATIC FILES MOUNTING FOR WEB UI
# =============================================================================

# Frontend is served by Next.js dev server (npm run dev) on port 3000.
# API calls are proxied from Next.js → FastAPI via rewrites in next.config.js.
# No static file mounting needed here.