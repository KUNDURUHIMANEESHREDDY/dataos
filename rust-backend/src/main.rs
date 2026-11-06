mod auth;
mod db;
mod parity;
mod sql_engine;

#[cfg(test)]
mod api_tests;

use std::collections::{HashMap, HashSet};
use std::env;
use std::sync::Arc;

use axum::{
    Json,
    extract::{DefaultBodyLimit, FromRequest, Multipart, Path, Query, Request, State},
    http::{Method, StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Router,
};
use serde::Deserialize;
use serde_json::{Value, json};
use auth::{User, decode_token, issue_token, jwt_configured, role_capabilities, user_payload};
use db::Db;

#[derive(Clone)]
struct AppState {
    db: Arc<Db>,
}

#[derive(Clone)]
struct CurrentUser(Option<User>);

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    detail: Value,
}

impl ApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self { status, detail: Value::String(detail.into()) }
    }

    /// Structured `detail`, matching FastAPI's `HTTPException(detail={...})`.
    fn with_detail(status: StatusCode, detail: Value) -> Self {
        Self { status, detail }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({"detail": self.detail}))).into_response()
    }
}

fn production_enabled() -> bool {
    ["DATAOS_ENV", "APP_ENV", "ENVIRONMENT"].iter().any(|name| {
        env::var(name).ok().map(|v| v.trim().eq_ignore_ascii_case("production") || v.trim().eq_ignore_ascii_case("prod")).unwrap_or(false)
    })
}

fn valid_secret(secret: &str) -> bool {
    !secret.is_empty() && secret.len() >= 32 && secret.trim() == secret
}

fn shared_token() -> Option<String> {
    env::var("DATAOS_API_TOKEN").ok().filter(|s| valid_secret(s))
}

fn capability_for(method: &Method, path: &str) -> Option<&'static str> {
    if method == Method::OPTIONS {
        return None;
    }
    if (method == Method::POST && path == "/api/auth/register") || (method == Method::POST && path == "/api/auth/login") {
        return None;
    }
    if (method == Method::POST && path == "/api/query/") || (method == Method::POST && path == "/api/agents/execute") {
        return None;
    }
    if method == Method::POST {
        match path {
            "/api/compute/python" | "/api/python" => return Some("compute_python"),
            "/api/compute/sql" => return Some("query_sql"),
            "/api/workflows/execute" => return Some("execute_workflow"),
            "/api/vectors/recompute" => return Some("transform_data"),
            "/api/objects" | "/api/objects/" => return Some("create_object"),
            "/api/io/ingest_text" | "/api/ingest/universal" | "/api/ingest" => return Some("create_object"),
            "/api/notebooks/ingest" => return Some("create_object"),
            "/api/documents/extract_rich" => return Some("extract_knowledge"),
            "/api/relationships" | "/api/relationships/" => return Some("create_relation"),
            "/api/sync/resolve_conflict" => return Some("update_object"),
            "/api/sharing/issue_token" => return Some("call_connector"),
            "/api/sharing/verify_token" => return Some("read_object"),
            _ => {
                if path.starts_with("/api/agents/pipeline/") { return Some("execute_workflow"); }
                if path.starts_with("/api/knowledge/query") { return Some("extract_knowledge"); }
                if path.starts_with("/api/quality/") { return Some("update_object"); }
                return Some("update_object");
            }
        }
    }
    if method == Method::GET {
        if path.starts_with("/api/io/export") { return Some("export_data"); }
        if path.starts_with("/api/search/") || path.starts_with("/api/vectors/search") || path.starts_with("/api/ask") || path.starts_with("/api/federation/search") || path.starts_with("/api/recommendations/") || path.starts_with("/api/governance/duplicates") {
            return Some("search");
        }
        return Some("read_object");
    }
    if method == Method::DELETE {
        if path.starts_with("/api/relationships/") { return Some("delete_relation"); }
        return Some("delete_object");
    }
    if method == Method::PUT || method == Method::PATCH { return Some("update_object"); }
    None
}

fn json_error_response(status: StatusCode, detail: &str) -> Response {
    (status, Json(json!({"detail": detail}))).into_response()
}

fn resource_id_for_path(path: &str) -> Option<&str> {
    let segments: Vec<&str> = path.trim_matches('/').split('/').collect();
    match segments.as_slice() {
        ["api", "objects", id] if !id.is_empty() => Some(id),
        ["api", "objects", id, "why" | "impact"] if !id.is_empty() => Some(id),
        ["api", "graph", "neighbors" | "traverse", id] if !id.is_empty() => Some(id),
        ["api", "time_travel", "object", id] if !id.is_empty() => Some(id),
        ["api", "provenance", "lineage", id] if !id.is_empty() => Some(id),
        ["api", "profiling" | "quality", id] if !id.is_empty() => Some(id),
        ["api", "governance", "quota", id] if !id.is_empty() => Some(id),
        ["api", "recommendations", "datasets" | "connections", id] if !id.is_empty() => Some(id),
        _ => None,
    }
}

fn is_global_data_route(path: &str) -> bool {
    matches!(path,
        "/api/catalog/health" |
        "/api/graph/analytics" |
        "/api/time_travel/graph" |
        "/api/io/export" |
        "/api/governance/duplicates" |
        "/api/federation/search" |
        "/api/search" |
        "/api/search/" |
        "/api/vectors/search" |
        "/api/ask"
    )
}

async fn security_middleware(
    State(state): State<AppState>,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    let path = request.uri().path().to_string();
    if !path.starts_with("/api/") {
        return next.run(request).await;
    }

    let mut user: Option<User> = None;
    let authorization = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
        .unwrap_or_default();
    let token = authorization.strip_prefix("Bearer ").or_else(|| authorization.strip_prefix("bearer ")).unwrap_or("").to_string();
    let production = production_enabled();
    let has_bearer = !token.is_empty();

    if production && !matches!(path.as_str(), "/api/auth/register" | "/api/auth/login") {
        // A shared API token authenticates an application, not an individual
        // principal. Production data routes require a resolvable user identity.
        if !jwt_configured() {
            return json_error_response(StatusCode::SERVICE_UNAVAILABLE, "Production user authentication is unavailable; configure DATAOS_JWT_SECRET with at least 32 UTF-8 bytes.");
        }
        if !has_bearer {
            return json_error_response(StatusCode::UNAUTHORIZED, "A user bearer token is required.");
        }
        match decode_token(&token) {
            Ok(claims) => match state.db.user_by_id(&claims.sub) {
                Ok(Some(found)) => user = Some(found),
                Ok(None) => return json_error_response(StatusCode::UNAUTHORIZED, "Unknown user."),
                Err(_) => return json_error_response(StatusCode::UNAUTHORIZED, "Unable to resolve the authenticated user."),
            },
            Err(error) => return json_error_response(StatusCode::UNAUTHORIZED, &error),
        }
    } else if jwt_configured() && has_bearer {
        match decode_token(&token) {
            Ok(claims) => {
                match state.db.user_by_id(&claims.sub) {
                    Ok(Some(found)) => user = Some(found),
                    Ok(None) => return json_error_response(StatusCode::UNAUTHORIZED, "Unknown user."),
                    Err(_) => return json_error_response(StatusCode::UNAUTHORIZED, "Unable to resolve the authenticated user."),
                }
            }
            Err(error) => return json_error_response(StatusCode::UNAUTHORIZED, &error),
        }
    }

    if let Some(current_user) = user.as_ref() {
        if let Some(required) = capability_for(request.method(), &path) {
            if !role_capabilities(&current_user.role).contains(&required) {
                return json_error_response(StatusCode::FORBIDDEN, &format!("Capability '{}' is not permitted for role '{}'.", required, current_user.role));
            }
        }
        if current_user.role != "admin" && is_global_data_route(&path) {
            return json_error_response(StatusCode::FORBIDDEN, "This aggregate or export endpoint is restricted until principal-scoped query support is enabled.");
        }
        if let Some(object_id) = resource_id_for_path(&path) {
            let allowed = state.db.can_access_object(object_id, &current_user.id, current_user.role == "admin").unwrap_or(false);
            if !allowed {
                return json_error_response(StatusCode::NOT_FOUND, "Object not found.");
            }
        }
    }

    let mut request = request;
    request.extensions_mut().insert(CurrentUser(user));
    next.run(request).await
}

fn clamp_i64(value: Option<i64>, default: i64, min: i64, max: i64) -> i64 {
    value.unwrap_or(default).clamp(min, max)
}

fn ok_json(value: Value) -> Result<Json<Value>, ApiError> {
    Ok(Json(value))
}

#[derive(Deserialize)]
struct ListParams {
    object_type: Option<String>,
    source: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

#[derive(Deserialize)]
struct RelationshipParams {
    source_id: Option<String>,
    target_id: Option<String>,
    relation_type: Option<String>,
    min_confidence: Option<f64>,
    limit: Option<i64>,
    offset: Option<i64>,
}

#[derive(Deserialize)]
struct DeleteParams {
    soft: Option<bool>,
}

#[derive(Deserialize)]
struct RegisterRequest {
    username: String,
    email: String,
    password: String,
}

#[derive(Deserialize)]
struct LoginRequest {
    login: String,
    password: String,
}

#[derive(Deserialize)]
struct ObjectCreateRequest {
    #[serde(rename = "type")]
    object_type: Option<String>,
    schema_ref: Option<String>,
    properties: Option<Value>,
    content: Option<Value>,
    source: Option<String>,
    metadata: Option<Value>,
}

#[derive(Deserialize)]
struct RelationshipCreateRequest {
    source_id: String,
    target_id: String,
    relation_type: Option<String>,
    confidence: Option<f64>,
    metadata: Option<Value>,
}

#[derive(Deserialize)]
struct QueryRequest {
    query: String,
    query_type: Option<String>,
    #[allow(dead_code)]
    context_object_id: Option<String>,
}

#[derive(Deserialize)]
struct AskRequest {
    query: String,
}

#[derive(Deserialize)]
struct ExportQuery {
    format: Option<String>,
}

#[derive(Deserialize)]
struct FederationQuery {
    q: String,
    top_k: Option<i64>,
}

async fn health(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    state.db.health_check().map_err(|_| ApiError::new(StatusCode::SERVICE_UNAVAILABLE, "DataOS storage is unavailable"))?;
    ok_json(json!({
        "status": "operational",
        "storage_backend": "RustObjectsSqlite",
        "storage_reachable": true,
        "timestamp": chrono::Utc::now().to_rfc3339()
    }))
}

async fn auth_register(State(state): State<AppState>, Json(req): Json<RegisterRequest>) -> Result<Json<Value>, ApiError> {
    if !jwt_configured() {
        return Err(ApiError::new(StatusCode::SERVICE_UNAVAILABLE, "User auth is disabled until DATAOS_JWT_SECRET is configured."));
    }
    let user = state.db.user_register(&req.username, &req.email, &req.password, "viewer")
        .map_err(|error| ApiError::new(StatusCode::BAD_REQUEST, error))?;
    ok_json(user_payload(&user))
}

async fn auth_login(State(state): State<AppState>, Json(req): Json<LoginRequest>) -> Result<Json<Value>, ApiError> {
    if !jwt_configured() {
        return Err(ApiError::new(StatusCode::SERVICE_UNAVAILABLE, "User auth is disabled until DATAOS_JWT_SECRET is configured."));
    }
    let user = state.db.user_login(&req.login, &req.password)
        .map_err(|error| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, error))?
        .ok_or_else(|| ApiError::new(StatusCode::UNAUTHORIZED, "Invalid credentials."))?;
    let token = issue_token(&user.id, &user.role).map_err(|error| ApiError::new(StatusCode::SERVICE_UNAVAILABLE, error))?;
    ok_json(json!({"access_token": token, "token_type": "bearer", "user": user_payload(&user)}))
}

async fn auth_me(Extension(CurrentUser(user)): Extension<CurrentUser>) -> Json<Value> {
    if let Some(user) = user {
        Json(json!({"authenticated": true, "user": user_payload(&user)}))
    } else if jwt_configured() {
        Json(json!({"authenticated": false, "detail": "A bearer token is required for /api/auth/me when JWT auth is configured."}))
    } else {
        Json(json!({"authenticated": false, "detail": "JWT auth is not configured; running in shared-token/dev mode."}))
    }
}

async fn auth_users(State(state): State<AppState>, Extension(CurrentUser(user)): Extension<CurrentUser>) -> Result<Json<Value>, ApiError> {
    let user = user.ok_or_else(|| ApiError::new(StatusCode::SERVICE_UNAVAILABLE, "User auth is not configured."))?;
    if user.role != "admin" {
        return Err(ApiError::new(StatusCode::FORBIDDEN, "Admin role required."));
    }
    let users = state.db.list_users().map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    ok_json(json!({"total": users.len(), "users": users}))
}

async fn compute_sql(State(state): State<AppState>, Json(req): Json<QueryRequest>) -> Json<Value> {
    Json(sql_engine::execute_sql(&req.query, &state.db))
}

async fn compute_python() -> (StatusCode, Json<Value>) {
    (StatusCode::FORBIDDEN, Json(json!({
        "detail": "Python compute is not available in the Rust backend until an equivalent sandbox is implemented and reviewed."
    })))
}

async fn ask_dataos(Json(req): Json<AskRequest>) -> (StatusCode, Json<Value>) {
    (StatusCode::NOT_IMPLEMENTED, Json(json!({
        "error": "The natural-language Ask engine has not been migrated to the Rust backend yet.",
        "query": req.query
    })))
}

async fn unified_query(State(state): State<AppState>, Extension(CurrentUser(user)): Extension<CurrentUser>, Json(req): Json<QueryRequest>) -> Result<Json<Value>, ApiError> {
    let query_type = req.query_type.as_deref().unwrap_or("auto").trim().to_lowercase();
    let resolved = if query_type == "auto" {
        let lowered = req.query.trim_start().to_lowercase();
        if lowered.starts_with("select ") || lowered.starts_with("with ") { "sql".to_string() } else { "ask".to_string() }
    } else {
        query_type
    };

    let required = match resolved.as_str() {
        "sql" => Some("query_sql"),
        "python" => Some("compute_python"),
        "ask" | "natural_language" | "search" => Some("search"),
        _ => None,
    };
    if let Some(user) = user {
        if let Some(required) = required {
            if !role_capabilities(&user.role).contains(&required) {
                return Err(ApiError::new(StatusCode::FORBIDDEN, format!("Capability '{}' is not permitted for role '{}'.", required, user.role)));
            }
        }
    }

    match resolved.as_str() {
        "sql" => Ok(Json(sql_engine::execute_sql(&req.query, &state.db))),
        "python" => Err(ApiError::new(StatusCode::FORBIDDEN, "Python compute is not available in the Rust backend until an equivalent sandbox is implemented and reviewed.")),
        "search" => Ok(Json(search_objects(&state.db, &req.query, 20))),
        "ask" | "natural_language" => Err(ApiError::new(StatusCode::NOT_IMPLEMENTED, "The natural-language Ask engine has not been migrated to the Rust backend yet.")),
        _ => Err(ApiError::new(StatusCode::BAD_REQUEST, "Unsupported query_type. Use auto, sql, python, ask, or search.")),
    }
}

fn search_objects(db: &Db, query: &str, limit: i64) -> Value {
    let query = query.trim().to_lowercase();
    let objects = db.list_objects(None, None, 1000, 0).unwrap_or_default();
    let mut matches = Vec::new();
    for object in objects {
        let haystack = serde_json::to_string(&object).unwrap_or_default().to_lowercase();
        if haystack.contains(&query) {
            matches.push(json!({
                "id": object.get("id").cloned().unwrap_or(Value::Null),
                "type": object.get("type").cloned().unwrap_or(Value::Null),
                "score": 1.0,
                "snippet": {
                    "name": object.pointer("/properties/filename").or_else(|| object.pointer("/properties/name")).cloned().unwrap_or(Value::Null),
                    "source": object.get("source").cloned().unwrap_or(Value::Null)
                },
                "object": object
            }));
        }
        if matches.len() as i64 >= limit { break; }
    }
    json!({"query": query, "total_matches": matches.len(), "results": matches})
}

async fn search(State(state): State<AppState>, Query(params): Query<HashMap<String, String>>) -> Result<Json<Value>, ApiError> {
    let query = params.get("q").cloned().unwrap_or_default();
    let limit = clamp_i64(params.get("limit").and_then(|v| v.parse().ok()), 20, 1, 100);
    ok_json(search_objects(&state.db, &query, limit))
}

fn type_counts(objects: &[Value]) -> HashMap<String, i64> {
    let mut counts = HashMap::new();
    for object in objects {
        if let Some(kind) = object.get("type").and_then(Value::as_str) {
            *counts.entry(kind.to_string()).or_insert(0) += 1;
        }
    }
    counts
}

async fn analytics(State(state): State<AppState>, Query(params): Query<HashMap<String, String>>) -> Result<Json<Value>, ApiError> {
    let algorithm = params.get("algorithm").map(String::as_str).unwrap_or("pagerank");
    let objects = state.db.list_objects(None, None, 10000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let relationships = state.db.list_relationships(None, None, None, 0.0, 50000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let mut outgoing: HashMap<String, Vec<String>> = HashMap::new();
    let mut inbound: HashMap<String, Vec<String>> = HashMap::new();
    let mut degrees: HashMap<String, i64> = HashMap::new();
    for object in &objects {
        if let Some(id) = object.get("id").and_then(Value::as_str) {
            outgoing.insert(id.to_string(), Vec::new());
            inbound.insert(id.to_string(), Vec::new());
            degrees.insert(id.to_string(), 0);
        }
    }
    for relation in &relationships {
        let source = relation.get("source").and_then(Value::as_str).unwrap_or("");
        let target = relation.get("target").and_then(Value::as_str).unwrap_or("");
        if source.is_empty() || target.is_empty() { continue; }
        outgoing.entry(source.to_string()).or_default().push(target.to_string());
        inbound.entry(target.to_string()).or_default().push(source.to_string());
        *degrees.entry(source.to_string()).or_insert(0) += 1;
        *degrees.entry(target.to_string()).or_insert(0) += 1;
    }
    let node_count = objects.len();
    let scores = {
        let mut values: HashMap<String, f64> = HashMap::from_iter(objects.iter().filter_map(|o| o.get("id").and_then(Value::as_str)).map(|id| (id.to_string(), 1.0 / node_count.max(1) as f64)));
        let damping = 0.85;
        for _ in 0..25 {
            let mut next = HashMap::from_iter(values.keys().cloned().map(|id| (id, (1.0 - damping) / node_count.max(1) as f64)));
            for (node, rank) in &values {
                let outgoing_nodes = outgoing.get(node).cloned().unwrap_or_default();
                let share = if outgoing_nodes.is_empty() { *rank / node_count.max(1) as f64 } else { *rank / outgoing_nodes.len() as f64 };
                let targets: Vec<String> = if outgoing_nodes.is_empty() { values.keys().cloned().collect() } else { outgoing_nodes };
                for target in targets {
                    *next.entry(target).or_insert(0.0) += damping * share;
                }
            }
            values = next;
        }
        values
    };
    match algorithm {
        "pagerank" => ok_json(json!({"algorithm": "pagerank", "scores": scores})),
        "centrality" => ok_json(json!({
            "degree_centrality": degrees,
            "betweenness_centrality": {}
        })),
        "communities" => ok_json(json!({"communities": []})),
        _ => Err(ApiError::new(StatusCode::BAD_REQUEST, format!("Unsupported algorithm: {}", algorithm))),
    }
}

/// Form fields accepted by the ingest routes.
///
/// FastAPI declares these as `Form(...)`, and the Next.js UI posts
/// `application/x-www-form-urlencoded`. Accepting only `multipart/form-data`
/// silently broke drag-and-drop upload, so both encodings are supported here.
struct FormFields(HashMap<String, String>);

impl<S> FromRequest<S> for FormFields
where
    S: Send + Sync,
{
    type Rejection = ApiError;

    async fn from_request(req: Request, state: &S) -> Result<Self, Self::Rejection> {
        let content_type = req
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("")
            .to_ascii_lowercase();

        if content_type.starts_with("multipart/form-data") {
            let mut multipart = Multipart::from_request(req, state)
                .await
                .map_err(|error| ApiError::new(StatusCode::BAD_REQUEST, error.to_string()))?;
            let mut fields = HashMap::new();
            while let Some(field) = multipart
                .next_field()
                .await
                .map_err(|error| ApiError::new(StatusCode::BAD_REQUEST, error.to_string()))?
            {
                let Some(name) = field.name().map(str::to_string) else {
                    continue;
                };
                let value = field
                    .text()
                    .await
                    .map_err(|error| ApiError::new(StatusCode::BAD_REQUEST, error.to_string()))?;
                fields.insert(name, value);
            }
            return Ok(Self(fields));
        }

        if content_type.starts_with("application/x-www-form-urlencoded") {
            let form = axum::extract::Form::<HashMap<String, String>>::from_request(req, state)
                .await
                .map_err(|error| ApiError::new(StatusCode::BAD_REQUEST, error.to_string()))?;
            return Ok(Self(form.0));
        }

        Err(ApiError::new(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "content-type must be application/x-www-form-urlencoded or multipart/form-data",
        ))
    }
}

async fn universal_ingest(
    State(state): State<AppState>,
    fields: FormFields,
) -> Result<Json<Value>, ApiError> {
    ingest_into_storage(state, fields, "")
}

async fn ingest_text(State(state): State<AppState>, fields: FormFields) -> Result<Json<Value>, ApiError> {
    ingest_into_storage(state, fields, "")
}

fn ingest_into_storage(state: AppState, fields: FormFields, _name: &str) -> Result<Json<Value>, ApiError> {
    let fields = fields.0;
    let filename = fields
        .get("filename")
        .filter(|value| !value.trim().is_empty())
        .cloned()
        .unwrap_or_else(|| "data_artifact".to_string());
    let content = fields.get("content").cloned().unwrap_or_default();
    if content.is_empty() { return Err(ApiError::new(StatusCode::BAD_REQUEST, "content is required")); }
    let lowered = filename.to_lowercase();
    let object_type = if lowered.ends_with(".csv") { "dataset" } else if lowered.ends_with(".json") { "dataset" } else if lowered.ends_with(".ipynb") { "notebook" } else { "document" };
    let mut properties = json!({"filename": filename});
    if lowered.ends_with(".csv") { properties["raw_csv"] = Value::String(content.clone()); }
    let stored = state.db.create_object(object_type, "generic.v1", properties, Value::String(content), "api://rust-ingest", json!({}))
        .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    ok_json(json!({
        "status": "ok",
        "primary_object_id": stored.get("id").cloned().unwrap_or(Value::Null),
        "objects_created": 1,
        "relations_created": 0
    }))
}

async fn export_graph(State(state): State<AppState>, Query(params): Query<ExportQuery>) -> Result<Response, ApiError> {
    let format = params.format.as_deref().unwrap_or("json_ld");
    let objects = state.db.list_objects(None, None, 10000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let relationships = state.db.list_relationships(None, None, None, 0.0, 50000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    if format == "json_ld" {
        return Ok(Json(json!({
            "@context": "https://dataos.example/context.jsonld",
            "@type": "DataOSGraph",
            "objects": objects,
            "relationships": relationships
        })).into_response());
    }
    let text = match format {
        "dot" => format!("digraph DataOS {{\n{}\n}}", relationships.iter().filter_map(|r| Some(format!("  \"{}\" -> \"{}\" [label=\"{}\"];", r.get("source")?.as_str()?, r.get("target")?.as_str()?, r.get("relation_type")?.as_str()?))).collect::<Vec<_>>().join("\n")),
        "graphml" => "<graphml xmlns=\"http://graphml.graphdrawing.org/graphml\"><graph edgedefault=\"directed\"></graph></graphml>".to_string(),
        "sql" => "-- DataOS SQLite dump is not implemented by the Rust backend yet".to_string(),
        _ => return Err(ApiError::new(StatusCode::BAD_REQUEST, format!("Unsupported format: {}", format))),
    };
    Ok(([(header::CONTENT_TYPE, if format == "dot" { "text/plain; charset=utf-8" } else if format == "graphml" { "application/xml" } else { "text/plain; charset=utf-8" })], text).into_response())
}

async fn catalog_health(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    let objects = state.db.list_objects(None, None, 10000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let relationships = state.db.list_relationships(None, None, None, 0.0, 50000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let counts = type_counts(&objects);
    ok_json(json!({
        "status": "operational",
        "total_objects": objects.len(),
        "total_relationships": relationships.len(),
        "object_types": counts,
        "data_health_score": if objects.is_empty() { 0.0 } else { 100.0 },
        "health_grade": if objects.is_empty() { "C" } else { "A" }
    }))
}

async fn duplicates(State(state): State<AppState>, Query(params): Query<HashMap<String, String>>) -> Result<Json<Value>, ApiError> {
    let min_similarity = params.get("min_similarity").and_then(|v| v.parse().ok()).unwrap_or(0.75);
    let target_id = params.get("object_id").cloned();
    let objects = state.db.list_objects(None, None, 1000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let mut hashes: HashMap<String, Vec<Value>> = HashMap::new();
    for object in objects {
        let hash = object.pointer("/metadata/content_hash").and_then(Value::as_str).map(str::to_string).unwrap_or_else(|| serde_json::to_string(object.get("content").unwrap_or(&Value::Null)).unwrap_or_default());
        hashes.entry(hash).or_default().push(object);
    }
    let mut groups: Vec<Value> = hashes.into_iter().filter_map(|(hash, members)| {
        if members.len() < 2 { return None; }
        let ids: Vec<Value> = members.iter().filter_map(|o| o.get("id").cloned()).collect();
        if target_id.as_ref().map(|id| !members.iter().any(|o| o.get("id").and_then(Value::as_str) == Some(id.as_str()))).unwrap_or(false) {
            return None;
        }
        Some(json!({"content_hash": hash, "similarity": 1.0, "object_ids": ids, "count": members.len(), "method": "exact_hash"}))
    }).collect();
    groups.sort_by(|a, b| b["count"].as_i64().cmp(&a["count"].as_i64()));
    ok_json(json!({"total": groups.len(), "duplicates": groups, "min_similarity": min_similarity}))
}

async fn quota(Path(principal_id): Path<String>) -> Json<Value> {
    Json(json!({
        "principal_id": principal_id,
        "remaining": {"queries": 1000, "compute_python": 100},
        "usage": {"queries": 0, "compute_python": 0},
        "status": "within_quota",
        "detail": "Rust backend quota accounting is local and in-memory; persistent accounting is not implemented yet."
    }))
}

async fn federation_search(State(state): State<AppState>, Query(params): Query<FederationQuery>) -> Result<Json<Value>, ApiError> {
    let top_k = clamp_i64(params.top_k, 10, 1, 100);
    let local = search_objects(&state.db, &params.q, top_k);
    if let Some(results) = local.get("results").cloned() {
        return ok_json(json!({
            "query": params.q,
            "local_results": results,
            "federated_results": [],
            "detail": "No external federation peers are configured; results are local only."
        }));
    }
    ok_json(local)
}

async fn recommendations_datasets(State(state): State<AppState>, Path(object_id): Path<String>) -> Result<Json<Value>, ApiError> {
    let datasets = state.db.list_objects(Some("dataset"), None, 5, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    ok_json(json!({"target_object_id": object_id, "recommended_datasets": datasets.into_iter().filter(|o| o.get("id").and_then(Value::as_str) != Some(object_id.as_str())).collect::<Vec<_>>()}))
}

async fn recommendations_connections(State(state): State<AppState>, Path(object_id): Path<String>) -> Result<Json<Value>, ApiError> {
    let relationships = state.db.list_relationships(Some(&object_id), None, None, 0.0, 10, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    ok_json(json!({"target_object_id": object_id, "recommendations": relationships}))
}

async fn fallback_route() -> (StatusCode, Json<Value>) {
    (StatusCode::NOT_IMPLEMENTED, Json(json!({
        "detail": "This route has not been migrated to the Rust backend yet."
    })))
}

#[tokio::main]
async fn main() {
    let db_path = env::var("DATAOS_DB_PATH").unwrap_or_else(|_| "dataos.db".to_string());
    let db = Db::open(&db_path).unwrap_or_else(|error| {
        eprintln!("failed to open database at {}: {}", db_path, error);
        std::process::exit(1);
    });
    let state = AppState { db: Arc::new(db) };
    let app = build_router(state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8000").await.expect("bind 0.0.0.0:8000");
    axum::serve(listener, app).await.expect("serve");
}

fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/api/catalog/health", get(catalog_health))
        .route("/api/auth/register", post(auth_register))
        .route("/api/auth/login", post(auth_login))
        .route("/api/auth/me", get(auth_me))
        .route("/api/auth/users", get(auth_users))
        .route("/api/objects", get(list_objects).post(create_object))
        .route("/api/objects/", get(list_objects).post(create_object))
        .route("/api/objects/{id}", get(get_object).delete(delete_object))
        .route("/api/objects/{id}/why", get(why_object))
        .route("/api/objects/{id}/impact", get(impact_object))
        .route("/api/relationships", get(list_relationships).post(create_relationship))
        .route("/api/relationships/", get(list_relationships).post(create_relationship))
        .route("/api/graph/neighbors/{id}", get(neighbors))
        .route("/api/graph/traverse/{id}", get(parity::traverse))
        .route("/api/graph/analytics", get(analytics))
        .route("/api/time_travel/object/{id}", get(parity::time_travel_object))
        .route("/api/time_travel/graph", get(parity::time_travel_graph))
        .route("/api/time_travel/changes", get(parity::time_travel_changes))
        .route("/api/provenance/lineage/{id}", get(parity::lineage))
        .route("/api/profiling/{id}", get(parity::profiling))
        .route("/api/quality/{id}", post(parity::quality))
        .route("/api/sync/resolve_conflict", post(parity::resolve_conflict))
        .route("/api/vectors/search", get(parity::vectors_search))
        .route("/api/vectors/recompute", post(parity::vectors_recompute))
        .route("/api/notebooks/ingest", post(parity::notebooks_ingest))
        .route("/api/documents/extract_rich", post(parity::documents_extract_rich))
        .route("/api/sharing/issue_token", post(parity::sharing_issue_token))
        .route("/api/sharing/verify_token", post(parity::sharing_verify_token))
        .route("/api/workflows/execute", post(parity::workflows_execute))
        .route("/api/agents/pipeline/research", post(parity::pipeline_research))
        .route("/api/agents/execute", post(parity::agents_execute))
        .route("/api/knowledge/query", post(parity::knowledge_query))
        .route("/api/search/", get(search))
        .route("/api/search", get(search))
        .route("/api/compute/sql", post(compute_sql))
        .route("/api/compute/python", post(compute_python))
        .route("/api/query", post(unified_query))
        .route("/api/query/", post(unified_query))
        .route("/api/ask", post(ask_dataos))
        .route("/api/ingest/universal", post(universal_ingest))
        .route("/api/io/ingest_text", post(ingest_text))
        .route("/api/io/export", get(export_graph))
        .route("/api/governance/duplicates", get(duplicates))
        .route("/api/governance/quota/{id}", get(quota))
        .route("/api/federation/search", get(federation_search))
        .route("/api/recommendations/datasets/{id}", get(recommendations_datasets))
        .route("/api/recommendations/connections/{id}", get(recommendations_connections))
        .layer(middleware::from_fn_with_state(state.clone(), security_middleware))
        .with_state(state)
        .layer(DefaultBodyLimit::max(32 * 1024 * 1024))
        .fallback(fallback_route)
}

async fn list_objects(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Query(params): Query<ListParams>,
) -> Result<Json<Value>, ApiError> {
    let limit = clamp_i64(params.limit, 100, 1, 500);
    let offset = clamp_i64(params.offset, 0, 0, 1_000_000);
    let (objects, total) = if let Some(user) = user {
        if user.role == "admin" {
            (
                state.db.list_objects(params.object_type.as_deref(), params.source.as_deref(), limit, offset),
                state.db.count_objects(params.object_type.as_deref(), params.source.as_deref()),
            )
        } else {
            let all = state.db.list_objects_for_owner(&user.id, params.object_type.as_deref(), 10000, 0)
                .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
            let filtered: Vec<Value> = all.into_iter().filter(|object| params.source.as_deref().map(|source| object.get("source").and_then(Value::as_str).unwrap_or("").contains(source)).unwrap_or(true)).collect();
            let total = filtered.len() as i64;
            let objects = filtered.into_iter().skip(offset as usize).take(limit as usize).collect();
            (Ok(objects), Ok(total))
        }
    } else {
        (
            state.db.list_objects(params.object_type.as_deref(), params.source.as_deref(), limit, offset),
            state.db.count_objects(params.object_type.as_deref(), params.source.as_deref()),
        )
    };
    let objects = objects.map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let total = total.map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    ok_json(json!({"total": total, "objects": objects}))
}

async fn create_object(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Json(req): Json<ObjectCreateRequest>,
) -> Result<Json<Value>, ApiError> {
    let object = state.db.create_object(
        req.object_type.as_deref().unwrap_or("document"),
        req.schema_ref.as_deref().unwrap_or("generic.v1"),
        req.properties.unwrap_or(json!({})),
        req.content.unwrap_or(json!({})),
        req.source.as_deref().unwrap_or("api://rust"),
        req.metadata.unwrap_or(json!({})),
    ).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let object = if let Some(user) = user {
        state.db.set_object_owner(object["id"].as_str().unwrap_or_default(), &user.id)
            .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?
            .ok_or_else(|| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, "Created object disappeared before ownership was assigned."))?
    } else { object };
    ok_json(object)
}

async fn get_object(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Path(object_id): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let object = state.db.get_object(&object_id)
        .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?
        .ok_or_else(|| ApiError::new(StatusCode::NOT_FOUND, "Object not found"))?;
    if let Some(user) = user {
        let allowed = state.db.can_access_object(&object_id, &user.id, user.role == "admin")
            .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        if !allowed { return Err(ApiError::new(StatusCode::NOT_FOUND, "Object not found")); }
    }
    Ok(Json(object))
}

async fn delete_object(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Path(object_id): Path<String>,
    Query(params): Query<DeleteParams>,
) -> Result<Json<Value>, ApiError> {
    if let Some(user) = user {
        let allowed = state.db.can_access_object(&object_id, &user.id, user.role == "admin")
            .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        if !allowed { return Err(ApiError::new(StatusCode::NOT_FOUND, "Object not found")); }
    }
    let soft = params.soft.unwrap_or(true);
    let deleted = state.db.delete_object(&object_id, soft).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    if !deleted { return Err(ApiError::new(StatusCode::NOT_FOUND, "Object not found or already deleted")); }
    ok_json(json!({"status": "deleted", "object_id": object_id, "soft": soft}))
}

async fn list_relationships(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Query(params): Query<RelationshipParams>,
) -> Result<Json<Value>, ApiError> {
    let limit = clamp_i64(params.limit, 1000, 1, 1000);
    let offset = clamp_i64(params.offset, 0, 0, 1_000_000);
    let confidence = params.min_confidence.unwrap_or(0.0).clamp(0.0, 1.0);
    let mut relationships = state.db.list_relationships(params.source_id.as_deref(), params.target_id.as_deref(), params.relation_type.as_deref(), confidence, limit, offset)
        .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let total = if let Some(user) = user {
        if user.role == "admin" {
            state.db.count_relationships(params.source_id.as_deref(), params.target_id.as_deref(), params.relation_type.as_deref(), confidence)
                .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?
        } else {
            relationships.retain(|rel| {
                let source = rel.get("source").and_then(Value::as_str).unwrap_or_default();
                let target = rel.get("target").and_then(Value::as_str).unwrap_or_default();
                state.db.can_access_object(source, &user.id, false).unwrap_or(false)
                    && state.db.can_access_object(target, &user.id, false).unwrap_or(false)
            });
            relationships.len() as i64
        }
    } else {
        state.db.count_relationships(params.source_id.as_deref(), params.target_id.as_deref(), params.relation_type.as_deref(), confidence)
            .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?
    };
    ok_json(json!({"total": total, "relationships": relationships}))
}

async fn create_relationship(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Json(req): Json<RelationshipCreateRequest>,
) -> Result<Json<Value>, ApiError> {
    if let Some(user) = user {
        let admin = user.role == "admin";
        for object_id in [&req.source_id, &req.target_id] {
            let allowed = state.db.can_access_object(object_id, &user.id, admin)
                .map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
            if !allowed {
                return Err(ApiError::new(StatusCode::NOT_FOUND, "One or more relationship objects were not found."));
            }
        }
    }
    let rel = state.db.create_relationship(
        &req.source_id,
        &req.target_id,
        req.relation_type.as_deref().unwrap_or("references"),
        req.confidence.unwrap_or(1.0),
        req.metadata.unwrap_or(json!({})),
    ).map_err(|e| ApiError::new(StatusCode::BAD_REQUEST, e))?;
    ok_json(rel)
}

fn lineage_response(state: &Db, object_id: &str, upstream: bool) -> Result<Value, ApiError> {
    let relationships = state.list_relationships(
        if upstream { None } else { Some(object_id) },
        if upstream { Some(object_id) } else { None },
        None,
        0.0,
        500,
        0,
    ).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    let lineage_types = ["derived_from", "transforms_to", "reads_from", "produces", "depends_on"];
    let edges: Vec<Value> = relationships.into_iter().filter(|rel| rel.get("relation_type").and_then(Value::as_str).map(|kind| lineage_types.contains(&kind)).unwrap_or(false)).collect();
    Ok(json!({
        "object_id": object_id,
        "direction": if upstream { "upstream" } else { "downstream" },
        "lineage": edges,
        "explanation": "Direct lineage edges as stored in DataOS; this is dependency-graph traversal, not an unverified audit verdict."
    }))
}

async fn why_object(State(state): State<AppState>, Path(object_id): Path<String>) -> Result<Json<Value>, ApiError> {
    state.db.get_object(&object_id).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?
        .ok_or_else(|| ApiError::new(StatusCode::NOT_FOUND, "Object not found"))?;
    ok_json(lineage_response(state.db.as_ref(), &object_id, true)?)
}

async fn impact_object(State(state): State<AppState>, Path(object_id): Path<String>) -> Result<Json<Value>, ApiError> {
    state.db.get_object(&object_id).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?
        .ok_or_else(|| ApiError::new(StatusCode::NOT_FOUND, "Object not found"))?;
    ok_json(lineage_response(state.db.as_ref(), &object_id, false)?)
}

async fn neighbors(State(state): State<AppState>, Path(object_id): Path<String>, Query(direction): Query<HashMap<String, String>>) -> Result<Json<Value>, ApiError> {
    let direction = direction.get("direction").map(String::as_str).unwrap_or("both");
    let mut rels = Vec::new();
    if matches!(direction, "both" | "outgoing") {
        rels.extend(state.db.list_relationships(Some(&object_id), None, None, 0.0, 1000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?);
    }
    if matches!(direction, "both" | "incoming") {
        rels.extend(state.db.list_relationships(None, Some(&object_id), None, 0.0, 1000, 0).map_err(|e| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, e))?);
    }
    let mut neighbors = Vec::new();
    let mut seen = HashSet::new();
    for rel in rels {
        let neighbor_id = if rel.get("source").and_then(Value::as_str) == Some(object_id.as_str()) {
            rel.get("target").and_then(Value::as_str).unwrap_or_default().to_string()
        } else {
            rel.get("source").and_then(Value::as_str).unwrap_or_default().to_string()
        };
        if neighbor_id.is_empty() || !seen.insert(neighbor_id.clone()) { continue; }
        match state.db.get_object(&neighbor_id) {
            Ok(Some(object)) => neighbors.push(json!({
                "id": neighbor_id,
                "type": object.get("type").cloned().unwrap_or(Value::Null),
                "name": object.pointer("/properties/filename").or_else(|| object.pointer("/properties/name")).cloned().unwrap_or(Value::String(neighbor_id.chars().take(8).collect())),
                "relation": rel,
                "properties": object.get("properties").cloned().unwrap_or(json!({}))
            })),
            _ => neighbors.push(json!({"id": neighbor_id, "relation": rel, "missing": true})),
        }
    }
    ok_json(json!({"object_id": object_id, "total": neighbors.len(), "neighbors": neighbors}))
}
