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
import threading
from typing import Annotated, Dict, Any, List, Literal, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header, Request, Response, Query as FastQuery
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ConfigDict

from dataos_system import DataOS
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from core.permissions.policy import Capability
from core.permissions.auth import (
    UserStore,
    User,
    issue_jwt,
    decode_jwt,
    jwt_configured,
    DEFAULT_TTL_SECONDS,
)
from backend.knowledge_rag import create_knowledge_router
from backend.cors_config import cors_middleware_options
from backend.authorization import CapabilityMiddleware, get_user_store
from backend.sql_authorization import datasets_readable_by_user, requires_per_user_identity
from backend.workflow_api import WorkflowRequestError, execute_safe_workflow
from runtime.workflows.workflow_engine import WorkflowEngine

def _parse_time_travel_timestamp(value: str, field_name: str) -> datetime.datetime:
    """Parse an offset-aware ISO 8601 timestamp and normalize it to UTC.

    The time-travel engine compares persisted ISO timestamps lexicographically,
    so callers must not pass mixed offsets or timezone-naive values.
    """
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 64:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be an ISO 8601 timestamp with an explicit UTC offset",
        )

    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(candidate)
    except (ValueError, OverflowError):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be an ISO 8601 timestamp with an explicit UTC offset",
        ) from None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must include a UTC offset",
        )
    try:
        return parsed.astimezone(datetime.timezone.utc)
    except (OverflowError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be representable as a UTC timestamp",
        ) from None


def _production_mode() -> bool:
    return any(
        marker.strip().lower() in {"production", "prod"}
        for marker in (
            os.getenv("DATAOS_ENV", ""),
            os.getenv("APP_ENV", ""),
            os.getenv("ENVIRONMENT", ""),
        )
    )


def require_production_api_token(
    request: Request,
    authorization: Annotated[Optional[str], Header()] = None,
) -> None:
    """Require an application bearer or per-user JWT for protected production API routes.

    Login and registration must remain reachable before a browser has a session.
    All other API routes accept a JWT from the HttpOnly session cookie or an
    explicit Bearer header. The shared application token is accepted only from
    the Authorization header and never treated as a user identity.
    """
    path = request.url.path
    if not path.startswith("/api/"):
        return
    if path in {"/api/auth/login", "/api/auth/register"}:
        return
    if not _production_mode():
        return

    expected = os.getenv("DATAOS_API_TOKEN", "")
    shared_ready = not (not expected or expected.strip() != expected or len(expected.encode("utf-8")) < 32)
    jwt_ready = jwt_configured()
    if not shared_ready and not jwt_ready:
        raise HTTPException(
            status_code=503,
            detail=(
                "Production API authentication is unavailable; configure either "
                "DATAOS_API_TOKEN or DATAOS_JWT_SECRET (each with at least 32 UTF-8 bytes)."
            ),
        )

    scheme, separator, bearer_value = (authorization or "").partition(" ")
    bearer_token = bearer_value.strip() if separator and scheme.lower() == "bearer" else ""
    cookie_token = request.cookies.get("dataos_session", "")
    token = bearer_token or cookie_token
    if not token:
        raise HTTPException(
            status_code=401,
            detail="A valid session cookie or Bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if bearer_token and shared_ready and hmac.compare_digest(bearer_token.encode("utf-8"), expected.encode("utf-8")):
        return
    if jwt_ready:
        try:
            decode_jwt(token)
            return
        except (ValueError, RuntimeError):
            pass
    raise HTTPException(
        status_code=401,
        detail="A valid session cookie or Bearer token is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_python_compute_enabled() -> None:
    """Require explicit opt-in before exposing Python execution in production.

    The shared API bearer token is not a per-user authorization boundary, so
    production deployments must deliberately enable this high-risk capability
    after reviewing their sandbox and access controls. Development behavior is
    unchanged.
    """
    production_markers = (
        os.getenv("DATAOS_ENV", ""),
        os.getenv("APP_ENV", ""),
        os.getenv("ENVIRONMENT", ""),
    )
    if not any(marker.strip().lower() in {"production", "prod"} for marker in production_markers):
        return
    enabled = os.getenv("DATAOS_ALLOW_PYTHON_COMPUTE", "").strip().lower()
    if enabled not in {"1", "true", "yes"}:
        raise HTTPException(
            status_code=403,
            detail=(
                "Python compute is disabled in production. Set "
                "DATAOS_ALLOW_PYTHON_COMPUTE=true only after reviewing sandbox "
                "isolation and access controls."
            ),
        )


# Initialize single DataOS kernel using deployment-configured paths.
dataos = DataOS(
    db_path=os.getenv("DATAOS_DB_PATH", "dataos.db"),
    blob_dir=os.getenv("DATAOS_BLOB_DIR", ".dataos_blobs"),
)
workflow_engine = WorkflowEngine(storage=dataos.storage)
# Bound concurrent synchronous DAG runs so API clients cannot exhaust the worker pool.
workflow_slots = threading.BoundedSemaphore(value=4)

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
app.add_middleware(CapabilityMiddleware)


app.include_router(create_knowledge_router(dataos))


async def get_current_user(
    request: Request,
    authorization: Annotated[Optional[str], Header()] = None,
) -> Optional[User]:
    """Resolve a per-user JWT from an HttpOnly session cookie or Bearer header."""
    if not jwt_configured():
        return None

    scheme, separator, bearer_value = (authorization or "").partition(" ")
    bearer_token = bearer_value.strip() if separator and scheme.lower() == "bearer" else ""
    token = bearer_token or request.cookies.get("dataos_session", "")
    if not token:
        return None

    try:
        claims = decode_jwt(token)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    store = await run_in_threadpool(get_user_store)
    user = await run_in_threadpool(store.get_by_id, str(claims.get("sub", "")))
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Unknown user.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_capability(capability: str):
    """Build a FastAPI dependency that enforces a capability for the JWT user."""
    async def dependency(
        current_user: Optional[User] = Depends(get_current_user),
    ) -> User:
        if current_user is None:
            raise HTTPException(
                status_code=401,
                detail="A bearer token is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not current_user.has_capability(capability):
            raise HTTPException(
                status_code=403,
                detail=f"Capability '{capability}' is not permitted for role '{current_user.role}'.",
            )
        return current_user

    return dependency


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


class RegisterRequest(BaseModel):
    # Public self-registration never accepts a caller-selected role.
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=1024)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


# =============================================================================
# AUTH ROUTES
# =============================================================================

@app.post("/api/auth/register", summary="Register a new DataOS user", status_code=201)
async def register_user(req: RegisterRequest):
    if not jwt_configured():
        raise HTTPException(
            status_code=503,
            detail="User auth is disabled until DATAOS_JWT_SECRET is configured.",
        )
    try:
        store = await run_in_threadpool(get_user_store)
        user = await run_in_threadpool(store.register, req.username, req.email, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return user.to_dict()


@app.post("/api/auth/login", summary="Authenticate and receive a JWT")
async def login_user(req: LoginRequest, response: Response):
    if not jwt_configured():
        raise HTTPException(
            status_code=503,
            detail="User auth is disabled until DATAOS_JWT_SECRET is configured.",
        )
    store = await run_in_threadpool(get_user_store)
    user = await run_in_threadpool(store.authenticate, req.login, req.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = issue_jwt(user.id, user.role)
    response.set_cookie(
        key="dataos_session",
        value=token,
        max_age=DEFAULT_TTL_SECONDS,
        httponly=True,
        secure=_production_mode(),
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"access_token": token, "token_type": "bearer", "user": user.to_dict()}


@app.post("/api/auth/logout", summary="Clear the current browser session", status_code=204)
async def logout_user(response: Response):
    response.delete_cookie(
        key="dataos_session",
        path="/",
        httponly=True,
        secure=_production_mode(),
        samesite="strict",
    )
    response.status_code = 204
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/auth/me", summary="Current authenticated user")
async def get_me(current_user: Optional[User] = Depends(get_current_user)):
    if current_user is None:
        if jwt_configured():
            return {"authenticated": False, "detail": "A session cookie or bearer token is required."}
        return {"authenticated": False, "detail": "JWT auth is not configured; running in shared-token/dev mode."}
    return {"authenticated": True, "user": current_user.to_dict()}


@app.get("/api/auth/users", summary="List registered users (admin)", dependencies=[Depends(require_capability(Capability.EXPORT_DATA.value))])
async def list_users(current_user: Optional[User] = Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=503, detail="User auth is not configured.")
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    store = await run_in_threadpool(get_user_store)
    users = await run_in_threadpool(store.list_users)
    return {"total": len(users), "users": users}


# =============================================================================
# OBJECT ROUTES
# =============================================================================

@app.get("/api/objects/", summary="List DataOS Objects")
async def list_objects(
    object_type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = FastQuery(default=100, ge=1, le=500),
    offset: int = FastQuery(default=0, ge=0, le=1_000_000)
):
    objs = dataos.storage.list_objects(object_type=object_type, source=source, limit=limit, offset=offset)
    total = dataos.storage.count_objects(object_type=object_type, source=source)
    return {"total": total, "objects": [o.to_dict() for o in objs]}


@app.post("/api/objects/", summary="Create DataOS Object")
async def create_object(req: ObjectCreateRequest):
    # These fields are owned by trusted ingestion/storage code. Accepting
    # caller-supplied values would let clients forge duplicate hashes or attach
    # arbitrary blob references to objects.
    server_managed_metadata = {"blob", "content_hash"}
    supplied_managed_fields = sorted(server_managed_metadata.intersection(req.metadata))
    if supplied_managed_fields:
        raise HTTPException(
            status_code=422,
            detail=(
                "Object metadata fields are managed by DataOS: "
                + ", ".join(supplied_managed_fields)
            ),
        )

    obj = DataObject(
        type=req.type,
        schema=req.schema_ref,
        properties=req.properties,
        content=req.content,
        source=req.source,
        metadata=dict(req.metadata),
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
    min_confidence: float = FastQuery(default=0.0, ge=0.0, le=1.0),
    limit: int = FastQuery(default=1000, ge=1, le=1000),
    offset: int = FastQuery(default=0, ge=0, le=1_000_000),
):
    rels = dataos.storage.list_relationships(
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    total = dataos.storage.count_relationships(
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        min_confidence=min_confidence,
    )
    return {"total": total, "relationships": [r.to_dict() for r in rels]}


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
async def get_neighbors(
    object_id: str,
    direction: Literal["outgoing", "incoming", "both"] = "both",
):
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
    require_python_compute_enabled()
    res = dataos.python(req.code, input_object_ids=req.input_object_ids)
    return res


@app.post("/api/query/", summary="Unified Query Execution")
async def query_unified(req: UnifiedQueryRequest, current_user: Optional[User] = Depends(get_current_user)):
    query_type = req.query_type.strip().lower()
    if query_type == "auto":
        query_type = "sql" if req.query.lstrip().lower().startswith(("select ", "with ")) else "ask"

    required_capability: Optional[str] = None
    if query_type == "sql":
        required_capability = Capability.QUERY_SQL.value
    elif query_type == "python":
        required_capability = Capability.COMPUTE_PYTHON.value
    elif query_type in {"ask", "natural_language", "search"}:
        required_capability = Capability.SEARCH.value

    if current_user is not None and required_capability and not current_user.has_capability(required_capability):
        raise HTTPException(
            status_code=403,
            detail=f"Capability '{required_capability}' is not permitted for role '{current_user.role}'.",
        )

    if query_type == "sql":
        # A deployment-wide bearer token proves access to the API, not which
        # tenant's datasets the caller may query. Once JWT auth is configured
        # (or production mode is active), require a per-user identity and pass
        # only datasets visible to that user into the SQL engine.
        if requires_per_user_identity(
            current_user,
            production_mode=_production_mode(),
            jwt_auth_configured=jwt_configured(),
        ):
                raise HTTPException(
                    status_code=401,
                    detail="A per-user session is required for SQL queries.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Preserve the unauthenticated local-development workflow only
            # when per-user authentication has not been configured.
            return dataos.sql(req.query)

        readable_datasets = datasets_readable_by_user(dataos.storage, current_user)
        return dataos.sql_engine.execute_sql(
            req.query,
            table_objects=readable_datasets,
            agent_or_user=f"user:{current_user.id}",
        )
    if query_type == "python":
        require_python_compute_enabled()
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
    as_of: str = FastQuery(..., min_length=17, max_length=64, description="Offset-aware ISO 8601 timestamp"),
    temporal_axis: Literal["system_time", "validity_time"] = "system_time"
):
    timestamp = _parse_time_travel_timestamp(as_of, "as_of")
    normalized_as_of = timestamp.isoformat()
    obj = dataos.time_travel.get_object_as_of(object_id, normalized_as_of, temporal_axis=temporal_axis)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Object {object_id} not found as of {normalized_as_of}")
    return obj.to_dict()


@app.get("/api/time_travel/graph", summary="Time-Travel Point-in-Time Graph Topology Query (Rule #27)")
async def time_travel_graph(
    as_of: str = FastQuery(..., min_length=17, max_length=64, description="Offset-aware ISO 8601 timestamp"),
    temporal_axis: Literal["system_time", "validity_time"] = "system_time"
):
    timestamp = _parse_time_travel_timestamp(as_of, "as_of")
    return dataos.time_travel.get_graph_as_of(timestamp.isoformat(), temporal_axis=temporal_axis)


@app.get("/api/time_travel/changes", summary="Changes Between Two Historical Timestamps (Rule #27)")
async def time_travel_changes(
    t1: str = FastQuery(..., min_length=17, max_length=64, description="Start offset-aware ISO 8601 timestamp"),
    t2: str = FastQuery(..., min_length=17, max_length=64, description="End offset-aware ISO 8601 timestamp"),
    temporal_axis: Literal["system_time", "validity_time"] = "system_time"
):
    start = _parse_time_travel_timestamp(t1, "t1")
    end = _parse_time_travel_timestamp(t2, "t2")
    if start > end:
        raise HTTPException(status_code=422, detail="t1 must be earlier than or equal to t2")
    return dataos.time_travel.changes_between(start.isoformat(), end.isoformat(), temporal_axis=temporal_axis)

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
async def get_lineage(
    object_id: str,
    direction: Literal["upstream", "downstream"] = FastQuery(default="upstream"),
    max_depth: int = FastQuery(default=10, ge=1, le=32),
):
    # Direct Python callers bypass FastAPI's request validation, so keep the
    # same contract at the engine boundary as well.
    if direction not in {"upstream", "downstream"}:
        raise HTTPException(status_code=400, detail="direction must be upstream or downstream")
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= 32:
        raise HTTPException(status_code=422, detail="max_depth must be between 1 and 32")
    if direction == "upstream":
        return dataos.lineage.trace_upstream_lineage(object_id, max_depth=max_depth)
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
async def execute_agent(req: AgentExecutionRequest, current_user: Optional[User] = Depends(get_current_user)):
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
        if current_user is not None and not current_user.has_capability(capability.value):
            raise HTTPException(
                status_code=403,
                detail=f"Capability '{capability.value}' is not permitted for role '{current_user.role}'.",
            )
        return agent.execute_capability(capability, req.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid capability: {req.capability}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Agent capability is not permitted") from exc


@app.post("/api/workflows/execute", summary="Execute a bounded built-in Workflow DAG")
async def execute_workflow(req: WorkflowExecutionRequest):
    # Do not queue an unbounded number of workflow requests behind the shared
    # ASGI worker pool. Reject overload explicitly so clients can retry.
    if not workflow_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="Workflow execution capacity is full; retry shortly.",
            headers={"Retry-After": "1"},
        )
    try:
        try:
            # The DAG engine performs synchronous work and bounded retry sleeps.
            # Run it in Starlette's worker pool so API requests and health checks
            # are not blocked while a workflow is executing.
            return await run_in_threadpool(
                execute_safe_workflow, workflow_engine, req.definition, req.context
            )
        except WorkflowRequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        workflow_slots.release()


# =============================================================================
# GOVERNANCE, SHARING & FEDERATION ROUTES (Rule #58, Rule #61, Rule #64, Rule #65)
# =============================================================================

@app.get("/api/governance/duplicates", summary="Fuzzy Duplicate Detection (Rule #58)")
async def detect_duplicates_api(
    object_id: Optional[str] = None,
    min_similarity: float = 0.75
):
    results = dataos.duplicates.find_duplicates(
        target_object_id=object_id,
        min_similarity=min_similarity,
    )
    return {"total": len(results), "duplicates": results}


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