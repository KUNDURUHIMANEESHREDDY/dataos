//! Rust ports of the remaining Python API surface.
//!
//! Every handler here mirrors a Python route contract from `backend/app.py`.
//! Anything that cannot be implemented faithfully without the Python/LLM
//! runtime is left to the router fallback (HTTP 501) instead of being faked.

use std::cmp::Ordering;
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::OnceLock;
use std::time::Instant;

use axum::{
    Json,
    extract::{Path, Query, State},
    http::StatusCode,
    Extension,
};
use chrono::{Duration, Utc};
use hmac::{Hmac, Mac};
use serde::Deserialize;
use serde_json::{Map, Value, json};
use sha2::Sha256;

use crate::sql_engine;
use crate::{AppState, ApiError, CurrentUser, clamp_i64, search_objects};
use base64::Engine as _;

const DERIVATION_TYPES: &[&str] = &["derived_from", "transforms_to", "reads_from", "produces"];
const DOWNSTREAM_TYPES: &[&str] = &["derived_from", "transforms_to", "reads_from", "produces", "depends_on"];
const CAPABILITIES: &[&str] = &[
    "search",
    "read_object",
    "create_object",
    "update_object",
    "delete_object",
    "create_relation",
    "delete_relation",
    "query_sql",
    "compute_python",
    "transform_data",
    "extract_knowledge",
    "execute_workflow",
    "call_connector",
    "export_data",
];

fn now_rfc3339() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
}

fn rel_side<'a>(rel: &'a Value, curr: &str) -> Option<&'a str> {
    let source = rel.get("source").and_then(Value::as_str)?;
    let target = rel.get("target").and_then(Value::as_str)?;
    if source == curr {
        Some(target)
    } else if target == curr {
        Some(source)
    } else {
        None
    }
}

fn relationship_visible_to(
    db: &crate::db::Db,
    relation: &Value,
    user: Option<&crate::auth::User>,
) -> Result<bool, ApiError> {
    let Some(user) = user else { return Ok(true) };
    if user.role == "admin" { return Ok(true); }
    let Some(source) = relation.get("source").and_then(Value::as_str) else { return Ok(false) };
    let Some(target) = relation.get("target").and_then(Value::as_str) else { return Ok(false) };
    if !db.can_access_object(source, &user.id, false).map_err(internal)? {
        return Ok(false);
    }
    db.can_access_object(target, &user.id, false).map_err(internal)
}

// ---------------------------------------------------------------------------
// Tabular extraction (shared by profiling + quality)
// ---------------------------------------------------------------------------

fn is_null_cell(value: &Value) -> bool {
    match value {
        Value::Null => true,
        Value::String(text) => text.trim().is_empty(),
        _ => false,
    }
}

fn rows_from_json_array(rows_value: &[Value]) -> (Vec<String>, Vec<Vec<Value>>) {
    let mut columns: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for row in rows_value {
        if let Some(object) = row.as_object() {
            for key in object.keys() {
                if seen.insert(key.clone()) {
                    columns.push(key.clone());
                }
            }
        }
    }
    let mut out = Vec::with_capacity(rows_value.len());
    for row in rows_value {
        if let Some(object) = row.as_object() {
            out.push(
                columns
                    .iter()
                    .map(|column| object.get(column).cloned().unwrap_or(Value::Null))
                    .collect(),
            );
        }
    }
    (columns, out)
}

/// Extract `(columns, rows)` from a DataOS object the same way the Python
/// profiler/quality engine does: `content` rows, `raw_csv`, or `sample_rows`.
fn tabular(object: &Value) -> Option<(Vec<String>, Vec<Vec<Value>>)> {
    if let Some(rows) = object.get("content").and_then(Value::as_array) {
        if !rows.is_empty() && rows.iter().all(|row| row.is_object()) {
            let (columns, values) = rows_from_json_array(rows);
            if !columns.is_empty() {
                return Some((columns, values));
            }
        }
    }
    if let Some(raw_csv) = object.pointer("/properties/raw_csv").and_then(Value::as_str) {
        let mut reader = csv::ReaderBuilder::new()
            .flexible(true)
            .has_headers(true)
            .from_reader(raw_csv.as_bytes());
        let headers: Vec<String> = reader
            .headers()
            .map(|header| header.iter().map(ToString::to_string).collect())
            .unwrap_or_default();
        if !headers.is_empty() {
            let mut values = Vec::new();
            for record in reader.records().flatten() {
                values.push(record.iter().map(|cell| Value::String(cell.to_string())).collect());
            }
            return Some((headers, values));
        }
    }
    if let Some(rows) = object.pointer("/properties/sample_rows").and_then(Value::as_array) {
        let (columns, values) = rows_from_json_array(rows);
        if !columns.is_empty() {
            return Some((columns, values));
        }
    }
    None
}

fn object_name(object: &Value) -> String {
    object
        .pointer("/properties/filename")
        .or_else(|| object.pointer("/properties/name"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| {
            object
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("dataset")
                .to_string()
        })
}

// ---------------------------------------------------------------------------
// GET /api/graph/traverse/{object_id}
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct TraverseParams {
    max_hops: Option<i64>,
    min_confidence: Option<f64>,
    direction: Option<String>,
}

pub(crate) async fn traverse(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Path(root_id): Path<String>,
    Query(params): Query<TraverseParams>,
) -> Result<Json<Value>, ApiError> {
    let max_hops = clamp_i64(params.max_hops, 3, 1, 10);
    let min_confidence = params.min_confidence.unwrap_or(0.0).clamp(0.0, 1.0);
    let direction = params.direction.as_deref().unwrap_or("outgoing");
    if !matches!(direction, "outgoing" | "incoming" | "both") {
        return Err(ApiError::new(
            StatusCode::BAD_REQUEST,
            "direction must be outgoing, incoming, or both",
        ));
    }

    let mut visited: HashSet<String> = HashSet::new();
    visited.insert(root_id.clone());
    let mut queue: VecDeque<(String, i64, Vec<String>)> = VecDeque::new();
    queue.push_back((root_id.clone(), 0, vec![root_id.clone()]));

    let mut nodes: Vec<Value> = Vec::new();
    let mut node_ids: HashSet<String> = HashSet::new();
    let mut edges: Vec<Value> = Vec::new();
    let mut paths: Vec<Value> = Vec::new();

    if let Some(root_obj) = state.db.get_object(&root_id).map_err(internal)? {
        node_ids.insert(root_id.clone());
        nodes.push(json!({
            "id": root_id,
            "depth": 0,
            "type": root_obj.get("type"),
            "schema": root_obj.get("schema"),
            "source": root_obj.get("source")
        }));
    }

    while let Some((curr, depth, path)) = queue.pop_front() {
        if depth >= max_hops {
            continue;
        }
        let mut relations: Vec<Value> = Vec::new();
        if direction == "outgoing" || direction == "both" {
            relations.extend(
                state
                    .db
                    .list_relationships(Some(&curr), None, None, min_confidence, 5000, 0)
                    .map_err(internal)?,
            );
        }
        if direction == "incoming" || direction == "both" {
            relations.extend(
                state
                    .db
                    .list_relationships(None, Some(&curr), None, min_confidence, 5000, 0)
                    .map_err(internal)?,
            );
        }

        for relation in relations {
            if !relationship_visible_to(state.db.as_ref(), &relation, user.as_ref())? {
                continue;
            }
            let Some(neighbor) = rel_side(&relation, &curr).map(str::to_string) else {
                continue;
            };
            edges.push(relation.clone());
            let mut new_path = path.clone();
            new_path.push(neighbor.clone());
            paths.push(json!({
                "path": new_path,
                "length": new_path.len().saturating_sub(1),
                "confidence": relation.get("confidence").cloned().unwrap_or(json!(1.0))
            }));

            if visited.insert(neighbor.clone()) {
                let info = match state.db.get_object(&neighbor).map_err(internal)? {
                    Some(object) => json!({
                        "id": neighbor,
                        "depth": depth + 1,
                        "type": object.get("type"),
                        "schema": object.get("schema"),
                        "source": object.get("source")
                    }),
                    None => json!({
                        "id": neighbor,
                        "depth": depth + 1,
                        "type": "unknown",
                        "schema": "unknown",
                        "source": "unknown"
                    }),
                };
                node_ids.insert(neighbor.clone());
                nodes.push(info);
                queue.push_back((neighbor, depth + 1, new_path));
            }
        }
    }

    Ok(Json(json!({
        "root_id": root_id,
        "max_hops": max_hops,
        "direction": direction,
        "total_nodes_reached": node_ids.len(),
        "total_edges_traversed": edges.len(),
        "nodes": nodes,
        "edges": edges,
        "paths": paths
    })))
}

// ---------------------------------------------------------------------------
// GET /api/time_travel/*
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct TimeTravelObjectParams {
    as_of: String,
    temporal_axis: Option<String>,
}

fn check_axis(axis: &str) -> Result<(), ApiError> {
    if matches!(axis, "system_time" | "validity_time") {
        Ok(())
    } else {
        Err(ApiError::new(
            StatusCode::BAD_REQUEST,
            "temporal_axis must be system_time or validity_time",
        ))
    }
}

pub(crate) async fn time_travel_object(
    State(state): State<AppState>,
    Path(object_id): Path<String>,
    Query(params): Query<TimeTravelObjectParams>,
) -> Result<Json<Value>, ApiError> {
    let axis = params.temporal_axis.as_deref().unwrap_or("system_time");
    check_axis(axis)?;

    if axis == "system_time" {
        return match state
            .db
            .object_version_as_of(&object_id, &params.as_of)
            .map_err(internal)?
        {
            Some(snapshot) => Ok(Json(snapshot)),
            None => Err(ApiError::new(
                StatusCode::NOT_FOUND,
                format!("Object {} not found as of {}", object_id, params.as_of),
            )),
        };
    }

    let object = state
        .db
        .get_object(&object_id)
        .map_err(internal)?
        .ok_or_else(|| {
            ApiError::new(
                StatusCode::NOT_FOUND,
                format!("Object {} not found as of {}", object_id, params.as_of),
            )
        })?;
    let valid_from = object.pointer("/timestamps/valid_from").and_then(Value::as_str);
    let valid_to = object.pointer("/timestamps/valid_to").and_then(Value::as_str);
    let after_start = valid_from.map(|start| params.as_of.as_str() >= start).unwrap_or(true);
    let before_end = valid_to.map(|end| params.as_of.as_str() < end).unwrap_or(true);
    if after_start && before_end {
        Ok(Json(object))
    } else {
        Err(ApiError::new(
            StatusCode::NOT_FOUND,
            format!("Object {} not found as of {}", object_id, params.as_of),
        ))
    }
}

#[derive(Deserialize)]
pub struct TimeTravelParams {
    as_of: Option<String>,
    t1: Option<String>,
    t2: Option<String>,
    temporal_axis: Option<String>,
}

pub(crate) async fn time_travel_graph(
    State(state): State<AppState>,
    Query(params): Query<TimeTravelParams>,
) -> Result<Json<Value>, ApiError> {
    let axis = params.temporal_axis.as_deref().unwrap_or("system_time");
    check_axis(axis)?;
    let as_of = params
        .as_of
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| ApiError::new(StatusCode::BAD_REQUEST, "as_of is required"))?;
    let objects = state.db.objects_alive_at(&as_of).map_err(internal)?;
    let relationships = state
        .db
        .relationships_alive_at(&as_of)
        .map_err(internal)?;
    Ok(Json(json!({
        "as_of": as_of,
        "temporal_axis": axis,
        "total_objects": objects.len(),
        "total_relationships": relationships.len(),
        "objects": objects,
        "relationships": relationships
    })))
}

pub(crate) async fn time_travel_changes(
    State(state): State<AppState>,
    Query(params): Query<TimeTravelParams>,
) -> Result<Json<Value>, ApiError> {
    let axis = params.temporal_axis.as_deref().unwrap_or("system_time");
    check_axis(axis)?;
    let t1 = params
        .t1
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| ApiError::new(StatusCode::BAD_REQUEST, "t1 is required"))?;
    let t2 = params
        .t2
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| ApiError::new(StatusCode::BAD_REQUEST, "t2 is required"))?;
    let changes = state.db.changes_between(&t1, &t2).map_err(internal)?;
    Ok(Json(changes))
}

// ---------------------------------------------------------------------------
// GET /api/provenance/lineage/{object_id}
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct LineageParams {
    direction: Option<String>,
    max_depth: Option<i64>,
}

pub(crate) async fn lineage(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Path(object_id): Path<String>,
    Query(params): Query<LineageParams>,
) -> Result<Json<Value>, ApiError> {
    let max_depth = clamp_i64(params.max_depth, 10, 1, 50);
    if params.direction.as_deref().unwrap_or("upstream") == "upstream" {
        upstream_lineage(&state, &object_id, max_depth, user.as_ref())
    } else {
        downstream_impact(&state, &object_id, max_depth, user.as_ref())
    }
}

fn upstream_lineage(state: &AppState, object_id: &str, max_depth: i64, user: Option<&crate::auth::User>) -> Result<Json<Value>, ApiError> {
    let mut visited: HashSet<String> = HashSet::new();
    visited.insert(object_id.to_string());
    let mut queue: VecDeque<(String, i64)> = VecDeque::new();
    queue.push_back((object_id.to_string(), 0));

    let mut lineage_nodes: Vec<Value> = Vec::new();
    let mut root_sources: Vec<Value> = Vec::new();

    while let Some((curr, depth)) = queue.pop_front() {
        if depth >= max_depth {
            continue;
        }
        let incoming_raw = state.db.list_relationships(None, Some(&curr), None, 0.0, 5000, 0).map_err(internal)?;
        let outgoing_raw = state.db.list_relationships(Some(&curr), None, None, 0.0, 5000, 0).map_err(internal)?;
        let mut incoming = Vec::new();
        let mut outgoing = Vec::new();
        for relation in incoming_raw {
            if relationship_visible_to(state.db.as_ref(), &relation, user)? { incoming.push(relation); }
        }
        for relation in outgoing_raw {
            if relationship_visible_to(state.db.as_ref(), &relation, user)? { outgoing.push(relation); }
        }

        let mut parents: Vec<String> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        for relation in &incoming {
            let kind = relation.get("relation_type").and_then(Value::as_str).unwrap_or("");
            if DERIVATION_TYPES.contains(&kind) {
                if let Some(source) = relation.get("source").and_then(Value::as_str) {
                    if seen.insert(source.to_string()) {
                        parents.push(source.to_string());
                    }
                }
            }
        }
        for relation in &outgoing {
            let kind = relation.get("relation_type").and_then(Value::as_str).unwrap_or("");
            if kind == "derived_from" {
                if let Some(target) = relation.get("target").and_then(Value::as_str) {
                    if seen.insert(target.to_string()) {
                        parents.push(target.to_string());
                    }
                }
            }
        }

        let current_object = state.db.get_object(&curr).map_err(internal)?;
        let node = json!({
            "object_id": curr,
            "type": current_object.as_ref().map(|o| o.get("type").cloned()).flatten().unwrap_or(Value::String("unknown".into())),
            "depth": depth,
            "source": current_object.as_ref().map(|o| o.get("source").cloned()).flatten().unwrap_or(Value::String("unknown".into())),
            "parent_count": parents.len()
        });
        if parents.is_empty() && depth > 0 {
            root_sources.push(node.clone());
        }
        lineage_nodes.push(node);

        for parent in parents {
            if visited.insert(parent.clone()) {
                queue.push_back((parent, depth + 1));
            }
        }
    }

    let total_ancestors = lineage_nodes.len().saturating_sub(1);
    Ok(Json(json!({
        "target_object_id": object_id,
        "max_depth": max_depth,
        "total_ancestors": total_ancestors,
        "lineage_nodes": lineage_nodes,
        "root_sources": root_sources,
        "traced_at": now_rfc3339()
    })))
}

fn downstream_impact(state: &AppState, object_id: &str, max_depth: i64, user: Option<&crate::auth::User>) -> Result<Json<Value>, ApiError> {
    let mut visited: HashSet<String> = HashSet::new();
    visited.insert(object_id.to_string());
    let mut queue: VecDeque<(String, i64)> = VecDeque::new();
    queue.push_back((object_id.to_string(), 0));

    let mut impacted_nodes: Vec<Value> = Vec::new();

    while let Some((curr, depth)) = queue.pop_front() {
        if depth >= max_depth {
            continue;
        }
        let relations = state.db.list_relationships(Some(&curr), None, None, 0.0, 5000, 0).map_err(internal)?;
        for relation in relations {
            if !relationship_visible_to(state.db.as_ref(), &relation, user)? { continue; }
            let kind = relation.get("relation_type").and_then(Value::as_str).unwrap_or("");
            if !DOWNSTREAM_TYPES.contains(&kind) {
                continue;
            }
            let Some(child) = relation.get("target").and_then(Value::as_str) else {
                continue;
            };
            if !visited.insert(child.to_string()) {
                continue;
            }
            let child_object = state.db.get_object(child).map_err(internal)?;
            impacted_nodes.push(json!({
                "object_id": child,
                "type": child_object.as_ref().map(|o| o.get("type").cloned()).flatten().unwrap_or(Value::String("unknown".into())),
                "depth": depth + 1,
                "relation_type": kind,
                "source": child_object.as_ref().map(|o| o.get("source").cloned()).flatten().unwrap_or(Value::String("unknown".into()))
            }));
            queue.push_back((child.to_string(), depth + 1));
        }
    }

    Ok(Json(json!({
        "root_object_id": object_id,
        "total_downstream_dependents": impacted_nodes.len(),
        "impacted_nodes": impacted_nodes,
        "analyzed_at": now_rfc3339()
    })))
}

// ---------------------------------------------------------------------------
// GET /api/profiling/{object_id}
// ---------------------------------------------------------------------------

fn parse_number(value: &Value) -> Option<f64> {
    match value {
        Value::Number(number) => number.as_f64(),
        Value::String(text) => text.trim().parse::<f64>().ok(),
        Value::Bool(flag) => Some(if *flag { 1.0 } else { 0.0 }),
        _ => None,
    }
}

fn quantile(sorted: &[f64], q: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    if sorted.len() == 1 {
        return sorted[0];
    }
    let position = q * (sorted.len() - 1) as f64;
    let lower = position.floor() as usize;
    let upper = position.ceil() as usize;
    let weight = position - lower as f64;
    sorted[lower] * (1.0 - weight) + sorted[upper] * weight
}

fn round4(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}

pub(crate) async fn profiling(
    State(state): State<AppState>,
    Path(object_id): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let object = state
        .db
        .get_object(&object_id)
        .map_err(internal)?
        .ok_or_else(|| ApiError::new(StatusCode::NOT_FOUND, "Object not found"))?;
    let (columns, rows) = tabular(&object).ok_or_else(|| {
        ApiError::new(
            StatusCode::BAD_REQUEST,
            "Object does not contain tabular dataset content",
        )
    })?;
    let dataset_name = object_name(&object);

    if rows.is_empty() {
        return Ok(Json(json!({
            "dataset_name": dataset_name,
            "row_count": 0,
            "column_count": columns.len(),
            "columns": {},
            "correlations": {},
            "summary": {"completeness_ratio": 0.0}
        })));
    }

    let total_rows = rows.len();
    let total_cells = total_rows * columns.len();
    let mut total_nulls = 0usize;
    let mut column_profiles = Map::new();
    let mut numeric_column_count = 0usize;

    for (index, column) in columns.iter().enumerate() {
        let cells: Vec<&Value> = rows
            .iter()
            .map(|row| row.get(index).unwrap_or(&Value::Null))
            .collect();
        let null_count = cells.iter().filter(|cell| is_null_cell(cell)).count();
        total_nulls += null_count;
        let non_null: Vec<&Value> = cells
            .iter()
            .copied()
            .filter(|cell| !is_null_cell(cell))
            .collect();
        let unique_count = non_null
            .iter()
            .map(|cell| cell.to_string())
            .collect::<HashSet<String>>()
            .len();

        let numeric_values: Vec<f64> = non_null.iter().filter_map(|cell| parse_number(cell)).collect();
        let is_numeric = !non_null.is_empty() && numeric_values.len() == non_null.len();
        let is_integer = is_numeric
            && non_null.iter().all(|cell| match cell {
                Value::Number(number) => number.is_i64() || number.is_u64(),
                Value::String(text) => text.trim().parse::<i64>().is_ok(),
                _ => false,
            });
        let dtype = if is_numeric {
            if is_integer { "int64" } else { "float64" }
        } else {
            "object"
        };

        let mut profile = json!({
            "name": column,
            "dtype": dtype,
            "null_count": null_count,
            "null_ratio": round4(null_count as f64 / total_rows as f64),
            "unique_count": unique_count,
            "uniqueness_ratio": round4(unique_count as f64 / total_rows as f64),
            "is_unique": unique_count == total_rows && null_count == 0,
        });

        if is_numeric {
            numeric_column_count += 1;
            let mut sorted = numeric_values.clone();
            sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            let count = sorted.len();
            let mean = sorted.iter().sum::<f64>() / count as f64;
            let variance = if count > 1 {
                sorted.iter().map(|value| (value - mean).powi(2)).sum::<f64>() / (count - 1) as f64
            } else {
                0.0
            };
            let q25 = quantile(&sorted, 0.25);
            let median = quantile(&sorted, 0.5);
            let q75 = quantile(&sorted, 0.75);
            let iqr = q75 - q25;
            let lower_bound = q25 - 1.5 * iqr;
            let upper_bound = q75 + 1.5 * iqr;
            let outlier_count = sorted
                .iter()
                .filter(|value| **value < lower_bound || **value > upper_bound)
                .count();
            profile["stats"] = json!({
                "count": count,
                "mean": mean,
                "std": variance.sqrt(),
                "min": sorted.first().copied().unwrap_or(0.0),
                "max": sorted.last().copied().unwrap_or(0.0),
                "q25": q25,
                "median": median,
                "q75": q75,
                "iqr": iqr,
                "outlier_count": outlier_count
            });
        }

        column_profiles.insert(column.clone(), profile);
    }

    Ok(Json(json!({
        "dataset_name": dataset_name,
        "row_count": total_rows,
        "column_count": columns.len(),
        "columns": column_profiles,
        "correlations": {},
        "summary": {
            "completeness_ratio": round4(1.0 - (total_nulls as f64 / total_cells.max(1) as f64)),
            "total_nulls": total_nulls,
            "numeric_column_count": numeric_column_count
        }
    })))
}

// ---------------------------------------------------------------------------
// POST /api/quality/{object_id}
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct QualityRequest {
    rules: Option<Vec<Value>>,
}

fn check(name: &str, passed: bool, severity: &str, message: String, details: Value) -> Value {
    json!({
        "check_name": name,
        "passed": passed,
        "severity": if passed { "INFO" } else { severity },
        "message": message,
        "details": details
    })
}

pub(crate) async fn quality(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Path(object_id): Path<String>,
    Json(request): Json<QualityRequest>,
) -> Result<Json<Value>, ApiError> {
    let object = state
        .db
        .get_object(&object_id)
        .map_err(internal)?
        .ok_or_else(|| ApiError::new(StatusCode::NOT_FOUND, "Object not found"))?;
    let (columns, rows) = tabular(&object).ok_or_else(|| {
        ApiError::new(StatusCode::BAD_REQUEST, "Object is not tabular")
    })?;
    let rules = match request.rules {
        Some(rules) if !rules.is_empty() => rules,
        _ => vec![json!({"type": "row_count_min", "min_rows": 1})],
    };
    let checks = evaluate_quality_checks(&columns, &rows, rules)?;

    let total_checks = checks.len();
    let passed_checks = checks
        .iter()
        .filter(|entry| entry.get("passed").and_then(Value::as_bool).unwrap_or(false))
        .count();
    let failed_checks = total_checks - passed_checks;
    let report_properties = json!({
        "target_object_id": object_id,
        "overall_pass": failed_checks == 0,
        "quality_score": round4(passed_checks as f64 / total_checks.max(1) as f64 * 100.0),
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "evaluated_at": now_rfc3339()
    });
    let report = if let Some(user) = user {
        state.db.create_object_for_owner(
            "quality_report",
            "quality_report.v1",
            report_properties,
            json!({"checks": checks}),
            "dataos://engine/quality",
            json!({}),
            &user.id,
        )
    } else {
        state.db.create_object(
            "quality_report",
            "quality_report.v1",
            report_properties,
            json!({"checks": checks}),
            "dataos://engine/quality",
            json!({}),
        )
    }.map_err(internal)?;
    Ok(Json(report))
}

/// Evaluate quality rules against tabular rows. Shared by `POST /api/quality/{id}`
/// and stage 3 of the research pipeline.
fn evaluate_quality_checks(
    columns: &[String],
    rows: &[Vec<Value>],
    rules: Vec<Value>,
) -> Result<Vec<Value>, ApiError> {
    let total_rows = rows.len();
    let column_index: HashMap<&str, usize> = columns
        .iter()
        .enumerate()
        .map(|(index, name)| (name.as_str(), index))
        .collect();

    let mut checks: Vec<Value> = Vec::new();
    for rule in rules {
        let rule_type = rule.get("type").and_then(Value::as_str).unwrap_or("");
        let column = rule.get("column").and_then(Value::as_str);

        if rule_type == "row_count_min" {
            let min_rows = rule.get("min_rows").and_then(Value::as_u64).unwrap_or(1) as usize;
            let passed = total_rows >= min_rows;
            checks.push(check(
                "row_count_min",
                passed,
                "ERROR",
                if passed {
                    format!("Row count {total_rows} >= {min_rows}")
                } else {
                    format!("Row count {total_rows} is below minimum {min_rows}")
                },
                json!({"actual_rows": total_rows, "min_rows": min_rows}),
            ));
            continue;
        }

        let Some(column) = column else { continue };
        let Some(&index) = column_index.get(column) else {
            checks.push(check(
                &format!("column_exists_{column}"),
                false,
                "ERROR",
                format!("Required column '{column}' does not exist in dataset"),
                json!({"missing_column": column}),
            ));
            continue;
        };

        let cells: Vec<&Value> = rows
            .iter()
            .map(|row| row.get(index).unwrap_or(&Value::Null))
            .collect();

        match rule_type {
            "not_null" => {
                let threshold = rule.get("max_null_ratio").and_then(Value::as_f64).unwrap_or(0.0);
                let null_count = cells.iter().filter(|cell| is_null_cell(cell)).count();
                let actual = null_count as f64 / total_rows.max(1) as f64;
                let passed = actual <= threshold;
                checks.push(check(
                    &format!("not_null_{column}"),
                    passed,
                    "ERROR",
                    if passed {
                        format!("Column '{column}' null ratio {} <= threshold {threshold}", round4(actual))
                    } else {
                        format!("Column '{column}' null ratio {} exceeds {threshold}", round4(actual))
                    },
                    json!({"actual_null_ratio": actual, "threshold": threshold}),
                ));
            }
            "unique" => {
                let unique_count = cells
                    .iter()
                    .filter(|cell| !is_null_cell(cell))
                    .map(|cell| cell.to_string())
                    .collect::<HashSet<String>>()
                    .len();
                let passed = unique_count == total_rows;
                checks.push(check(
                    &format!("unique_{column}"),
                    passed,
                    "ERROR",
                    if passed {
                        format!("Column '{column}' is strictly unique")
                    } else {
                        format!("Column '{column}' has duplicates ({unique_count} unique of {total_rows} rows)")
                    },
                    json!({"unique_count": unique_count, "total_rows": total_rows}),
                ));
            }
            "range" => {
                let min = rule.get("min").and_then(Value::as_f64);
                let max = rule.get("max").and_then(Value::as_f64);
                let mut violations = 0usize;
                for cell in &cells {
                    if is_null_cell(cell) {
                        continue;
                    }
                    let Some(value) = parse_number(cell) else {
                        violations += 1;
                        continue;
                    };
                    if min.map(|bound| value < bound).unwrap_or(false)
                        || max.map(|bound| value > bound).unwrap_or(false)
                    {
                        violations += 1;
                    }
                }
                let passed = violations == 0;
                checks.push(check(
                    &format!("range_{column}"),
                    passed,
                    "ERROR",
                    if passed {
                        format!("Column '{column}' all values within range [{min:?}, {max:?}]")
                    } else {
                        format!("Column '{column}' has {violations} values outside [{min:?}, {max:?}]")
                    },
                    json!({"violations": violations, "min": min, "max": max}),
                ));
            }
            "regex" => {
                let pattern = rule.get("pattern").and_then(Value::as_str).unwrap_or(".*");
                let compiled = regex::Regex::new(pattern).map_err(|error| {
                    ApiError::new(StatusCode::BAD_REQUEST, format!("Invalid regex pattern: {error}"))
                })?;
                let failing = cells
                    .iter()
                    .filter(|cell| !is_null_cell(cell))
                    .filter(|cell| !compiled.is_match(&cell.to_string()))
                    .count();
                let passed = failing == 0;
                checks.push(check(
                    &format!("regex_{column}"),
                    passed,
                    "ERROR",
                    if passed {
                        format!("Column '{column}' matches regex '{pattern}'")
                    } else {
                        format!("Column '{column}' has {failing} values failing regex '{pattern}'")
                    },
                    json!({"failing_rows": failing, "pattern": pattern}),
                ));
            }
            _ => {}
        }
    }

    Ok(checks)
}

// ---------------------------------------------------------------------------
// POST /api/knowledge/query — scoped evidence retrieval
// ---------------------------------------------------------------------------

const STOP_WORDS: &[&str] = &[
    "about", "after", "again", "also", "and", "are", "been", "before", "between", "both", "but",
    "can", "could", "does", "for", "from", "have", "into", "its", "more", "most", "not", "our",
    "out", "over", "same", "should", "some", "such", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "through", "under", "use", "using", "was",
    "were", "what", "when", "where", "which", "while", "who", "why", "will", "with", "would",
    "you", "your",
];

const TEXT_PROPERTY_KEYS: &[&str] = &[
    "filename",
    "name",
    "title",
    "description",
    "summary",
    "text",
    "extracted_text",
    "raw_text",
    "content_text",
    "raw_csv",
];

fn query_terms(query: &str) -> Vec<String> {
    static TOKENS: OnceLock<regex::Regex> = OnceLock::new();
    let pattern = TOKENS.get_or_init(|| regex::Regex::new(r"[a-zA-Z0-9_]{2,}").expect("valid token pattern"));
    pattern
        .find_iter(query)
        .map(|found| found.as_str().to_lowercase())
        .filter(|term| !STOP_WORDS.contains(&term.as_str()))
        .collect()
}

fn rank_text(query: &str, text: &str) -> f64 {
    let terms: HashSet<String> = query_terms(query).into_iter().collect();
    if terms.is_empty() || text.is_empty() {
        return 0.0;
    }
    let lowered = text.to_lowercase();
    let matched: Vec<&String> = terms
        .iter()
        .filter(|term| lowered.contains(term.as_str()))
        .collect();
    if matched.is_empty() {
        return 0.0;
    }
    let coverage = matched.len() as f64 / terms.len() as f64;
    let frequency: usize = matched
        .iter()
        .map(|term| lowered.matches(term.as_str()).count().min(4))
        .sum();
    let freq_ratio = (frequency as f64 / (terms.len().max(1) * 2) as f64).min(1.0);
    round4(0.8 * coverage + 0.2 * freq_ratio)
}

fn find_char(haystack: &[char], needle: &[char]) -> Option<usize> {
    if needle.is_empty() || needle.len() > haystack.len() {
        return None;
    }
    (0..=haystack.len() - needle.len()).find(|&index| &haystack[index..index + needle.len()] == needle)
}

fn extract_snippet(text: &str, query: &str, max_chars: usize) -> String {
    let compact: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    let chars: Vec<char> = compact.chars().collect();
    if chars.len() <= max_chars {
        return compact;
    }
    let lowered: Vec<char> = compact.to_lowercase().chars().collect();
    let hits: Vec<usize> = query_terms(query)
        .iter()
        .filter_map(|term| find_char(&lowered, &term.chars().collect::<Vec<_>>()))
        .collect();
    if hits.is_empty() {
        let truncated: String = chars.iter().take(max_chars).collect();
        return format!("{}\u{2026}", truncated.trim_end());
    }

    let mut start = hits.into_iter().min().unwrap_or(0).saturating_sub(max_chars / 4);
    if start > 0 {
        start = match chars[start..].iter().position(|&c| c == ' ') {
            Some(offset) => start + offset,
            None => 0,
        };
    }
    let mut end = chars.len().min(start + max_chars);
    if end < chars.len() {
        if let Some(space) = (start..end).rev().find(|&index| chars[index] == ' ') {
            if space > start {
                end = space;
            }
        }
    }
    let body: String = chars[start..end].iter().collect();
    format!(
        "{}{}{}",
        if start > 0 { "\u{2026}" } else { "" },
        body.trim(),
        if end < chars.len() { "\u{2026}" } else { "" }
    )
}

fn flatten_value(value: &Value, limit: usize) -> String {
    let text = match value {
        Value::String(text) => text.clone(),
        other => serde_json::to_string(other).unwrap_or_default(),
    };
    text.chars().take(limit).collect()
}

/// Same property-key precedence as the Python `object_text`.
fn knowledge_object_text(object: &Value) -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Some(properties) = object.get("properties") {
        for key in TEXT_PROPERTY_KEYS {
            if let Some(value) = properties.get(*key) {
                if !value.is_null() {
                    let flat = flatten_value(value, 30_000);
                    if !flat.is_empty() {
                        parts.push(flat);
                    }
                }
            }
        }
    }
    if let Some(content) = object.get("content") {
        let flat = flatten_value(content, 100_000);
        if !flat.is_empty() {
            parts.push(flat);
        }
    }
    parts
        .join("\n")
        .trim()
        .chars()
        .take(120_000)
        .collect::<String>()
}

fn display_name(object: &Value, fallback: &str) -> String {
    object
        .pointer("/properties/filename")
        .or_else(|| object.pointer("/properties/name"))
        .or_else(|| object.pointer("/properties/title"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| fallback.to_string())
}

fn resolve_related_files(
    selected_ids: &[String],
    relationships: &[Value],
    max_related: usize,
    min_confidence: f64,
) -> Vec<Value> {
    let selected: HashSet<&str> = selected_ids.iter().map(String::as_str).collect();
    let mut candidates: HashMap<String, Value> = HashMap::new();

    for relation in relationships {
        let source = relation.get("source").and_then(Value::as_str);
        let target = relation.get("target").and_then(Value::as_str);
        let (Some(source), Some(target)) = (source, target) else {
            continue;
        };
        let confidence = relation
            .get("confidence")
            .and_then(Value::as_f64)
            .unwrap_or(1.0);
        if confidence < min_confidence {
            continue;
        }
        let neighbor = if selected.contains(source) && !selected.contains(target) {
            Some(target)
        } else if selected.contains(target) && !selected.contains(source) {
            Some(source)
        } else {
            None
        };
        let Some(neighbor) = neighbor else { continue };
        let connected_to = if selected.contains(source) { source } else { target };
        let relationship_type = relation
            .get("relation_type")
            .or_else(|| relation.get("type"))
            .and_then(Value::as_str)
            .unwrap_or("related_to")
            .to_string();

        let candidate = json!({
            "file_id": neighbor,
            "confidence": confidence,
            "relationship_type": relationship_type,
            "connected_to": connected_to
        });
        let better = match candidates.get(neighbor) {
            Some(existing) => {
                confidence > existing.get("confidence").and_then(Value::as_f64).unwrap_or(0.0)
            }
            None => true,
        };
        if better {
            candidates.insert(neighbor.to_string(), candidate);
        }
    }

    let mut resolved: Vec<Value> = candidates.into_values().collect();
    resolved.sort_by(|left, right| {
        let left_conf = left.get("confidence").and_then(Value::as_f64).unwrap_or(0.0);
        let right_conf = right.get("confidence").and_then(Value::as_f64).unwrap_or(0.0);
        right_conf
            .partial_cmp(&left_conf)
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                left.get("file_id")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .cmp(right.get("file_id").and_then(Value::as_str).unwrap_or(""))
            })
    });
    resolved.truncate(max_related);
    resolved
}

#[derive(Deserialize)]
pub struct KnowledgeQueryRequest {
    query: String,
    selected_file_ids: Vec<String>,
    include_related: Option<bool>,
    max_related_files: Option<i64>,
    min_confidence: Option<f64>,
}

pub(crate) async fn knowledge_query(
    State(state): State<AppState>,
    Json(request): Json<KnowledgeQueryRequest>,
) -> Result<Json<Value>, ApiError> {
    let unprocessable =
        |message: &str| ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, message.to_string());
    if request.query.is_empty() || request.query.len() > 4000 {
        return Err(unprocessable("query must be between 1 and 4000 characters"));
    }
    if request.selected_file_ids.is_empty() || request.selected_file_ids.len() > 200 {
        return Err(unprocessable(
            "selected_file_ids must contain between 1 and 200 ids",
        ));
    }
    let include_related = request.include_related.unwrap_or(true);
    let max_related = clamp_i64(request.max_related_files, 10, 0, 50) as usize;
    let min_confidence = request.min_confidence.unwrap_or(0.75).clamp(0.0, 1.0);

    let mut selected_ids: Vec<String> = Vec::new();
    let mut seen_ids: HashSet<String> = HashSet::new();
    for file_id in &request.selected_file_ids {
        if seen_ids.insert(file_id.clone()) {
            selected_ids.push(file_id.clone());
        }
    }

    let mut selected: HashMap<String, Value> = HashMap::new();
    let mut missing: Vec<String> = Vec::new();
    for file_id in &selected_ids {
        match state.db.get_object(file_id).map_err(internal)? {
            Some(object) => {
                selected.insert(file_id.clone(), object);
            }
            None => missing.push(file_id.clone()),
        }
    }
    if !missing.is_empty() {
        return Err(ApiError::with_detail(
            StatusCode::NOT_FOUND,
            json!({
                "message": "One or more selected files no longer exist.",
                "missing_file_ids": missing
            }),
        ));
    }

    let mut relationships: Vec<Value> = Vec::new();
    if include_related && max_related > 0 {
        let mut seen_relationships: HashSet<String> = HashSet::new();
        for file_id in &selected_ids {
            let outgoing = state
                .db
                .list_relationships(Some(file_id), None, None, 0.0, 5000, 0)
                .map_err(internal)?;
            let incoming = state
                .db
                .list_relationships(None, Some(file_id), None, 0.0, 5000, 0)
                .map_err(internal)?;
            for relation in outgoing.into_iter().chain(incoming) {
                let key = format!(
                    "{}|{}|{}|{}",
                    relation.get("id").and_then(Value::as_str).unwrap_or(""),
                    relation.get("source").and_then(Value::as_str).unwrap_or(""),
                    relation.get("target").and_then(Value::as_str).unwrap_or(""),
                    relation
                        .get("relation_type")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                );
                if seen_relationships.insert(key) {
                    relationships.push(relation);
                }
            }
        }
    }

    let related = resolve_related_files(
        &selected_ids,
        &relationships,
        if include_related { max_related } else { 0 },
        min_confidence,
    );

    let mut related_objects: HashMap<String, Value> = HashMap::new();
    for item in &related {
        let file_id = item.get("file_id").and_then(Value::as_str).unwrap_or("");
        if let Some(object) = state.db.get_object(file_id).map_err(internal)? {
            related_objects.insert(file_id.to_string(), object);
        }
    }

    // Python merges `{**selected, **related_objects}`: selected order first.
    let mut eligible: Vec<(String, Value)> = Vec::new();
    for file_id in &selected_ids {
        if let Some(object) = selected.get(file_id) {
            eligible.push((file_id.clone(), object.clone()));
        }
    }
    for item in &related {
        let file_id = item.get("file_id").and_then(Value::as_str).unwrap_or("");
        if !selected.contains_key(file_id) {
            if let Some(object) = related_objects.get(file_id) {
                eligible.push((file_id.to_string(), object.clone()));
            }
        }
    }

    let mut evidence: Vec<Value> = Vec::new();
    for (file_id, object) in &eligible {
        let text = knowledge_object_text(object);
        let score = rank_text(&request.query, &text);
        if text.is_empty() || score <= 0.0 {
            continue;
        }
        let is_selected = selected.contains_key(file_id);
        let related_info = related
            .iter()
            .find(|item| item.get("file_id").and_then(Value::as_str) == Some(file_id.as_str()))
            .cloned();
        let inclusion_reason = match &related_info {
            Some(info) if !is_selected => format!(
                "{} ({:.2})",
                info.get("relationship_type").and_then(Value::as_str).unwrap_or("related_to"),
                info.get("confidence").and_then(Value::as_f64).unwrap_or(1.0)
            ),
            _ => "explicitly selected".to_string(),
        };
        evidence.push(json!({
            "file_id": file_id,
            "name": display_name(object, file_id),
            "score": score,
            "excerpt": extract_snippet(&text, &request.query, 720),
            "selected": is_selected,
            "inclusion_reason": inclusion_reason,
            "relationship": related_info
        }));
    }
    evidence.sort_by(|left, right| {
        right
            .get("score")
            .and_then(Value::as_f64)
            .unwrap_or(0.0)
            .partial_cmp(&left.get("score").and_then(Value::as_f64).unwrap_or(0.0))
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                left.get("selected")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                    .cmp(&right.get("selected").and_then(Value::as_bool).unwrap_or(false))
                    .reverse()
            })
            .then_with(|| {
                left.get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_lowercase()
                    .cmp(
                        &right
                            .get("name")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_lowercase(),
                    )
            })
    });
    evidence.truncate(12);

    let related_response: Vec<Value> = related
        .iter()
        .filter(|item| {
            let file_id = item.get("file_id").and_then(Value::as_str).unwrap_or("");
            related_objects.contains_key(file_id)
        })
        .map(|item| {
            let mut entry = item.clone();
            let file_id = item.get("file_id").and_then(Value::as_str).unwrap_or("");
            if let Some(object) = related_objects.get(file_id) {
                entry["name"] = json!(display_name(object, file_id));
            }
            entry
        })
        .collect();

    let eligible_ids: Vec<&str> = eligible.iter().map(|(id, _)| id.as_str()).collect();
    let answer = if evidence.is_empty() {
        "No matching text was found inside the selected files or their eligible related files. Try a more specific query or inspect the stored document content."
            .to_string()
    } else {
        format!(
            "Retrieved {} matching evidence passages from {} eligible files. Results are restricted to selected files and the configured one-hop related-file set.",
            evidence.len(),
            eligible.len()
        )
    };

    Ok(Json(json!({
        "query": request.query,
        "mode": "scoped_evidence_retrieval",
        "selected_file_ids": selected_ids,
        "related_files": related_response,
        "eligible_file_ids": eligible_ids,
        "eligible_file_count": eligible.len(),
        "evidence": evidence,
        "answer": answer,
        "generation_available": false,
        "generation_note": "This endpoint currently performs scope-constrained evidence retrieval. Provider-backed answer synthesis is not wired into the current DataOS API, so it does not call the global /api/ask endpoint or claim an LLM-generated answer."
    })))
}

// ---------------------------------------------------------------------------
// POST /api/agents/pipeline/research — 4-stage deterministic pipeline
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct ResearchPipelineRequest {
    goal_prompt: String,
    target_dataset_id: String,
    analysis_sql_or_python: String,
    quality_rules: Option<Vec<Value>>,
}

fn ms_since(start: Instant) -> f64 {
    round4(start.elapsed().as_secs_f64() * 1_000.0)
}

/// Python-style repr, truncated, used by the deterministic report provider.
fn py_repr(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => format!("'{}'", text.replace('\\', "\\\\").replace('\'', "\\'")),
        Value::Array(items) => format!(
            "[{}]",
            items.iter().map(py_repr).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(map) => format!(
            "{{{}}}",
            map.iter()
                .map(|(key, value)| format!("'{}': {}", key, py_repr(value)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

fn py_str_short(value: &Value) -> String {
    py_repr(value).chars().take(60).collect()
}

pub(crate) async fn pipeline_research(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    Json(request): Json<ResearchPipelineRequest>,
) -> Result<Json<Value>, ApiError> {
    if request.goal_prompt.trim().is_empty() {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "goal_prompt must be a non-empty string",
        ));
    }
    if request.target_dataset_id.trim().is_empty() {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "target_dataset_id must be a non-empty string",
        ));
    }

    if let Some(user) = user.as_ref() {
        let allowed = state.db.can_access_object(
            &request.target_dataset_id,
            &user.id,
            user.role == "admin",
        ).map_err(internal)?;
        if !allowed {
            return Err(ApiError::new(StatusCode::NOT_FOUND, "Dataset not found."));
        }
    }

    let started = Instant::now();
    let pipeline_id = format!(
        "pipeline_{}",
        &uuid::Uuid::new_v4().simple().to_string()[..8]
    );
    let mut stages: Vec<Value> = Vec::new();

    // Stage 1 — research agent: search for contextual objects.
    let stage_started = Instant::now();
    let found_objects = if let Some(user) = user.as_ref().filter(|user| user.role != "admin") {
        let owned = state.db.list_objects_for_owner(&user.id, None, None, 1000, 0).map_err(internal)?;
        let needle = request.goal_prompt.trim().to_lowercase();
        owned.iter().filter(|object| {
            serde_json::to_string(object).unwrap_or_default().to_lowercase().contains(&needle)
        }).count() as u64
    } else {
        search_objects(&state.db, &request.goal_prompt, 5)
            .get("total_matches")
            .and_then(Value::as_u64)
            .unwrap_or(0)
    };
    stages.push(json!({
        "stage": 1,
        "agent": "agent_research",
        "action": "hybrid_search",
        "found_objects_count": found_objects,
        "duration_ms": ms_since(stage_started)
    }));

    // Stage 2 — analysis agent: verified computation. The Rust runtime has no
    // Python sandbox, so only read-only SQL can be honoured here.
    let analysis = request.analysis_sql_or_python.trim();
    if !analysis.to_uppercase().starts_with("SELECT") {
        return Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "Stage 2 of the research pipeline requires Python compute for non-SELECT analysis, which has not been migrated to Rust. Pass a read-only SELECT statement.",
        ));
    }
    let stage_started = Instant::now();
    let compute_result = if let Some(user) = user.as_ref().filter(|user| user.role != "admin") {
        sql_engine::execute_sql_for_owner(&request.analysis_sql_or_python, &state.db, &user.id)
    } else {
        sql_engine::execute_sql(&request.analysis_sql_or_python, &state.db)
    };
    let compute_success = compute_result
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !compute_success {
        let detail = compute_result.get("error").and_then(Value::as_str)
            .unwrap_or("The requested analysis could not be executed.");
        return Err(ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, detail));
    }
    stages.push(json!({
        "stage": 2,
        "agent": "agent_analysis",
        "action": "verified_computation",
        "success": compute_success,
        "duration_ms": ms_since(stage_started)
    }));

    // Stage 3 — quality agent: contract evaluation.
    let stage_started = Instant::now();
    let target_object = state
        .db
        .get_object(&request.target_dataset_id)
        .map_err(internal)?;
    let rules = match request.quality_rules {
        Some(rules) if !rules.is_empty() => rules,
        _ => vec![json!({"type": "row_count_min", "min_rows": 1})],
    };
    let mut quality_pass = true;
    if let Some(object) = &target_object {
        if let Some((columns, rows)) = tabular(object) {
            let checks = evaluate_quality_checks(&columns, &rows, rules)?;
            let failed = checks
                .iter()
                .filter(|entry| !entry.get("passed").and_then(Value::as_bool).unwrap_or(false))
                .count();
            let total = checks.len();
            quality_pass = failed == 0;
            let properties = json!({
                "target_object_id": request.target_dataset_id,
                "overall_pass": quality_pass,
                "quality_score": round4((total - failed) as f64 / total.max(1) as f64 * 100.0),
                "total_checks": total,
                "passed_checks": total - failed,
                "failed_checks": failed,
                "evaluated_at": now_rfc3339()
            });
            let content = json!({"checks": checks});
            if let Some(user) = user.as_ref() {
                state.db.create_object_for_owner(
                    "quality_report", "quality_report.v1", properties, content,
                    "dataos://engine/quality", json!({}), &user.id,
                ).map_err(internal)?;
            } else {
                state.db.create_object(
                    "quality_report", "quality_report.v1", properties, content,
                    "dataos://engine/quality", json!({}),
                ).map_err(internal)?;
            }
        }
    }
    stages.push(json!({
        "stage": 3,
        "agent": "agent_quality",
        "action": "contract_evaluation",
        "quality_pass": quality_pass,
        "duration_ms": ms_since(stage_started)
    }));

    // Stage 4 — report agent: deterministic grounded summary.
    // Mirrors MockDeterministicProvider (the default provider in Python).
    let stage_started = Instant::now();
    let prompt = format!("Create verified executive summary for {}", request.goal_prompt);
    let context_data = vec![
        json!({"computation_output": compute_result}),
        json!({"target_dataset": request.target_dataset_id}),
        json!({"quality_pass": quality_pass}),
    ];
    let mut summary_lines: Vec<String> = Vec::new();
    summary_lines.push(format!("Analysis for: '{}'", prompt.chars().take(50).collect::<String>()));
    summary_lines.push(format!(
        "Synthesized from {} grounded evidence items.",
        context_data.len()
    ));
    for context in context_data.iter().take(3) {
        summary_lines.push(format!("- Fact: {}", py_str_short(context)));
    }
    let summary = summary_lines.join("\n");
    let prompt_tokens = prompt.split_whitespace().count() + 10;
    let completion_tokens = summary.split_whitespace().count();

    let report_properties = json!({
        "pipeline_id": pipeline_id,
        "goal": request.goal_prompt,
        "target_dataset_id": request.target_dataset_id,
        "quality_pass": quality_pass,
        "ai_model": "dataos_deterministic_v1",
        "total_tokens": prompt_tokens + completion_tokens,
        "cost_usd": 0.0
    });
    let report_source = format!("dataos://pipeline/{pipeline_id}/report");
    let report = if let Some(user) = user.as_ref() {
        state.db.create_object_for_owner(
            "report", "report.v1", report_properties, json!(summary),
            &report_source, json!({}), &user.id,
        )
    } else {
        state.db.create_object(
            "report", "report.v1", report_properties, json!(summary),
            &report_source, json!({}),
        )
    }.map_err(internal)?;
    let report_id = report
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();

    state
        .db
        .create_relationship(
            &report_id,
            &request.target_dataset_id,
            "derived_from",
            1.0,
            json!({"pipeline": pipeline_id}),
        )
        .map_err(internal)?;

    stages.push(json!({
        "stage": 4,
        "agent": "agent_report",
        "action": "grounded_report_synthesis",
        "report_object_id": report_id,
        "duration_ms": ms_since(stage_started)
    }));

    let total_duration_ms = round4(started.elapsed().as_secs_f64() * 1_000.0);
    Ok(Json(json!({
        "status": "completed",
        "pipeline_id": pipeline_id,
        "report_object_id": report_id,
        "report_content": summary,
        "total_duration_ms": total_duration_ms,
        "trace": {
            "pipeline_id": pipeline_id,
            "goal": request.goal_prompt,
            "stages": stages
        },
        "cost_summary": {
            "session_started_at": now_rfc3339(),
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "total_cost_usd": 0.0,
            "agent_breakdown": {}
        }
    })))
}

// ---------------------------------------------------------------------------
// POST /api/sharing/issue_token + /api/sharing/verify_token (Rule #65)
// ---------------------------------------------------------------------------

fn sharing_secret() -> Result<Vec<u8>, ApiError> {
    let secret = std::env::var("DATAOS_SHARING_TOKEN_SECRET").unwrap_or_default();
    if secret.is_empty() {
        return Err(ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "Sharing tokens are disabled until DATAOS_SHARING_TOKEN_SECRET is configured.",
        ));
    }
    if secret.len() < 32 || secret.trim() != secret {
        return Err(ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "Sharing-token signing secret must be at least 32 UTF-8 bytes.",
        ));
    }
    Ok(secret.into_bytes())
}

#[derive(Deserialize)]
pub struct IssueSharingTokenRequest {
    issuer: String,
    subject_principal: String,
    subgraph_root_id: String,
    allowed_object_ids: Option<Vec<String>>,
    allowed_capabilities: Option<Vec<String>>,
    duration_seconds: Option<i64>,
    max_hops: Option<i64>,
}

pub(crate) async fn sharing_issue_token(
    Json(request): Json<IssueSharingTokenRequest>,
) -> Result<Json<Value>, ApiError> {
    let secret = sharing_secret()?;
    let duration = request.duration_seconds.unwrap_or(3600);
    if !(1..=86400).contains(&duration) {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "duration_seconds must be between 1 and 86400",
        ));
    }
    if request.issuer.trim().is_empty()
        || request.subject_principal.trim().is_empty()
        || request.subgraph_root_id.trim().is_empty()
    {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "issuer, subject_principal, and subgraph_root_id are required",
        ));
    }

    let now = Utc::now();
    let payload = json!({
        "token_id": format!("tok_{}", &uuid::Uuid::new_v4().simple().to_string()[..12]),
        "issuer": request.issuer,
        "subject_principal": request.subject_principal,
        "subgraph_root_id": request.subgraph_root_id,
        "allowed_object_ids": request.allowed_object_ids.filter(|ids| !ids.is_empty())
            .unwrap_or_else(|| vec![request.subgraph_root_id.clone()]),
        "allowed_capabilities": request.allowed_capabilities.filter(|caps| !caps.is_empty())
            .unwrap_or_else(|| vec!["read_object".to_string()]),
        "max_hops": request.max_hops.unwrap_or(2),
        "issued_at": now.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        "expires_at": (now + Duration::seconds(duration)).to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
    });

    let payload_json = serde_json::to_string(&payload)
        .map_err(|error| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    let payload_b64 = base64::engine::general_purpose::URL_SAFE.encode(payload_json.as_bytes());
    let mut mac = Hmac::<Sha256>::new_from_slice(&secret)
        .map_err(|error| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    mac.update(payload_b64.as_bytes());
    let signature = hex::encode(mac.finalize().into_bytes());

    Ok(Json(json!({
        "token": format!("{payload_b64}.{signature}"),
        "expires_in_seconds": duration
    })))
}

#[derive(Deserialize)]
pub struct VerifySharingTokenRequest {
    token: String,
}

pub(crate) async fn sharing_verify_token(
    Json(request): Json<VerifySharingTokenRequest>,
) -> Result<Json<Value>, ApiError> {
    let secret = sharing_secret()?;
    let parts: Vec<&str> = request.token.split('.').collect();
    if parts.len() != 2 {
        return Err(ApiError::new(StatusCode::FORBIDDEN, "Malformed sharing token format."));
    }
    let (payload_b64, signature) = (parts[0], parts[1]);

    let mut mac = Hmac::<Sha256>::new_from_slice(&secret)
        .map_err(|error| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    mac.update(payload_b64.as_bytes());
    let expected = hex::encode(mac.finalize().into_bytes());
    if !constant_time_eq(expected.as_bytes(), signature.as_bytes()) {
        return Err(ApiError::new(
            StatusCode::FORBIDDEN,
            "Invalid cryptographic signature on sharing token (tampering detected).",
        ));
    }

    let decoded = base64::engine::general_purpose::URL_SAFE
        .decode(payload_b64)
        .map_err(|_| ApiError::new(StatusCode::FORBIDDEN, "Malformed sharing token format."))?;
    let payload: Value = serde_json::from_slice(&decoded)
        .map_err(|_| ApiError::new(StatusCode::FORBIDDEN, "Malformed sharing token format."))?;

    if let Some(expires_at) = payload.get("expires_at").and_then(Value::as_str) {
        let expired = chrono::DateTime::parse_from_rfc3339(expires_at)
            .map(|timestamp| timestamp.with_timezone(&Utc) < Utc::now())
            .unwrap_or(true);
        if expired {
            let token_id = payload
                .get("token_id")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            return Err(ApiError::new(
                StatusCode::FORBIDDEN,
                format!("Sharing token '{token_id}' expired at {expires_at}."),
            ));
        }
    }

    Ok(Json(json!({"status": "valid", "payload": payload})))
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right.iter())
        .fold(0u8, |acc, (a, b)| acc | (a ^ b))
        == 0
}

// ---------------------------------------------------------------------------
// GET /api/vectors/search + POST /api/vectors/recompute (Rule #45)
// ---------------------------------------------------------------------------

const EMBEDDING_DIMENSIONS: usize = 128;

fn tokenize(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|token| token.len() > 1)
        .map(str::to_string)
        .collect()
}

/// Deterministic hashed bag-of-words embedding (L2-normalised).
/// This is a real, reproducible vector representation — not a fabricated score.
fn embed(text: &str) -> Vec<f64> {
    let mut vector = vec![0.0f64; EMBEDDING_DIMENSIONS];
    for token in tokenize(text) {
        let mut hash: u64 = 0xcbf29ce484222325;
        for byte in token.as_bytes() {
            hash ^= u64::from(*byte);
            hash = hash.wrapping_mul(0x100000001b3);
        }
        let index = (hash as usize) % EMBEDDING_DIMENSIONS;
        let sign = if hash & 1 == 0 { 1.0 } else { -1.0 };
        vector[index] += sign;
    }
    let norm = vector.iter().map(|value| value * value).sum::<f64>().sqrt();
    if norm > 0.0 {
        for value in &mut vector {
            *value /= norm;
        }
    }
    vector
}

fn object_text(object: &Value) -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Some(name) = object_name(object).into() {
        parts.push(name);
    }
    if let Some(source) = object.get("source").and_then(Value::as_str) {
        parts.push(source.to_string());
    }
    if let Some(properties) = object.get("properties") {
        parts.push(properties.to_string());
    }
    if let Some(content) = object.get("content") {
        let text = content.to_string();
        parts.push(text.chars().take(4096).collect());
    }
    parts.join(" ")
}

pub(crate) async fn vectors_recompute(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    let objects = state.db.list_objects(None, None, 10_000, 0).map_err(internal)?;
    let mut recomputed = 0usize;
    for mut object in objects {
        let embedding = embed(&object_text(&object));
        if let Some(map) = object.get_mut("metadata").and_then(Value::as_object_mut) {
            map.insert("embedding".to_string(), json!(embedding));
            map.insert(
                "embedding_method".to_string(),
                json!("hashed-bag-of-words-128"),
            );
        }
        state.db.save_object(&object).map_err(internal)?;
        recomputed += 1;
    }
    Ok(Json(json!({
        "status": "ok",
        "recomputed": recomputed,
        "dimensions": EMBEDDING_DIMENSIONS,
        "method": "hashed-bag-of-words-128",
        "note": "Deterministic lexical embeddings; a model-backed semantic index has not been migrated to Rust yet."
    })))
}

#[derive(Deserialize)]
pub struct VectorSearchParams {
    q: String,
    top_k: Option<i64>,
}

pub(crate) async fn vectors_search(
    State(state): State<AppState>,
    Query(params): Query<VectorSearchParams>,
) -> Result<Json<Value>, ApiError> {
    let top_k = clamp_i64(params.top_k, 10, 1, 100);
    let query_vector = embed(&params.q);
    let objects = state.db.list_objects(None, None, 10_000, 0).map_err(internal)?;

    let mut scored: Vec<(f64, Value)> = Vec::new();
    for object in objects {
        let Some(embedding) = object.pointer("/metadata/embedding").and_then(Value::as_array) else {
            continue;
        };
        let values: Vec<f64> = embedding.iter().filter_map(Value::as_f64).collect();
        if values.len() != EMBEDDING_DIMENSIONS {
            continue;
        }
        let score: f64 = query_vector
            .iter()
            .zip(values.iter())
            .map(|(a, b)| a * b)
            .sum();
        if score > 0.0 {
            scored.push((score, object));
        }
    }
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    let total_matches = scored.len();
    let results: Vec<Value> = scored
        .into_iter()
        .take(top_k as usize)
        .map(|(score, object)| {
            json!({
                "id": object.get("id").cloned().unwrap_or(Value::Null),
                "type": object.get("type").cloned().unwrap_or(Value::Null),
                "score": score,
                "name": object_name(&object),
                "object": object
            })
        })
        .collect();

    Ok(Json(json!({
        "query": params.q,
        "total_matches": total_matches,
        "results": results
    })))
}

// ---------------------------------------------------------------------------
// POST /api/sync/resolve_conflict (Rule #59)
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct ConflictResolutionRequest {
    conflict_object_id: String,
    strategy: Option<String>,
    manual_properties: Option<Value>,
}

pub(crate) async fn resolve_conflict(
    State(state): State<AppState>,
    Json(request): Json<ConflictResolutionRequest>,
) -> Result<Json<Value>, ApiError> {
    let strategy = request.strategy.as_deref().unwrap_or("last_write_wins");
    if !matches!(strategy, "last_write_wins" | "source_priority" | "manual_merge") {
        return Err(ApiError::new(
            StatusCode::BAD_REQUEST,
            format!("Unsupported resolution strategy: {strategy}"),
        ));
    }

    let mut conflict = state
        .db
        .get_object(&request.conflict_object_id)
        .map_err(internal)?
        .filter(|object| object.get("schema").and_then(Value::as_str) == Some("conflict.v1"))
        .ok_or_else(|| {
            ApiError::new(
                StatusCode::BAD_REQUEST,
                format!("Invalid conflict object: {}", request.conflict_object_id),
            )
        })?;

    let target_id = conflict
        .pointer("/properties/target_object_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::new(StatusCode::BAD_REQUEST, "Conflict object is missing target_object_id"))?
        .to_string();
    let mut target = state.db.get_object(&target_id).map_err(internal)?.ok_or_else(|| {
        ApiError::new(StatusCode::BAD_REQUEST, format!("Target object not found: {target_id}"))
    })?;

    let local = conflict
        .pointer("/content/local_properties")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let incoming = conflict
        .pointer("/content/incoming_properties")
        .cloned()
        .unwrap_or_else(|| json!({}));

    let resolved_properties = match strategy {
        "last_write_wins" => merge(&local, &incoming),
        "source_priority" => merge(&incoming, &local),
        _ => match request.manual_properties {
            Some(properties) if properties.is_object() => properties,
            _ => {
                return Err(ApiError::new(
                    StatusCode::BAD_REQUEST,
                    "manual_properties must be provided for manual_merge strategy",
                ))
            }
        },
    };

    let next_version = target.get("version").and_then(Value::as_i64).unwrap_or(1) + 1;
    let now = now_rfc3339();
    target["properties"] = resolved_properties.clone();
    target["version"] = json!(next_version);
    if let Some(timestamps) = target.get_mut("timestamps").and_then(Value::as_object_mut) {
        timestamps.insert("updated_at".to_string(), json!(now));
    }
    if let Some(provenance) = target.get_mut("provenance").and_then(Value::as_object_mut) {
        let mut transformation = json!({
            "description": format!("Resolved conflict {} using strategy '{}'", request.conflict_object_id, strategy),
            "timestamp": now,
            "agent_or_user": "api_user"
        });
        if let Some(list) = provenance.get_mut("transformations").and_then(Value::as_array_mut) {
            list.push(transformation.take());
        }
    }
    state.db.save_object(&target).map_err(internal)?;

    conflict["properties"]["resolved"] = json!(true);
    conflict["properties"]["resolution_strategy"] = json!(strategy);
    if let Some(content) = conflict.get_mut("content").and_then(Value::as_object_mut) {
        content.insert("resolved_properties".to_string(), resolved_properties.clone());
    }
    state.db.save_object(&conflict).map_err(internal)?;

    Ok(Json(json!({
        "status": "resolved",
        "conflict_id": request.conflict_object_id,
        "strategy": strategy,
        "resolved_object_id": target.get("id").cloned().unwrap_or(Value::Null),
        "resolved_version": next_version,
        "properties": resolved_properties
    })))
}

fn merge(base: &Value, overlay: &Value) -> Value {
    let mut result = match base.as_object() {
        Some(map) => map.clone(),
        None => Map::new(),
    };
    if let Some(overlay_map) = overlay.as_object() {
        for (key, value) in overlay_map {
            result.insert(key.clone(), value.clone());
        }
    }
    Value::Object(result)
}

// ---------------------------------------------------------------------------
// POST /api/workflows/execute — bounded built-in DAG (Rule #44)
// ---------------------------------------------------------------------------

const ALLOWED_ACTIONS: &[&str] = &["noop", "set_variable", "log"];
const ALLOWED_CONDITIONS: &[&str] = &["==", "!=", "exists", "not_exists", "in"];
const MAX_NODES: usize = 25;
const MAX_PAYLOAD_BYTES: usize = 128 * 1024;
const MAX_RETRIES: i64 = 3;
const MAX_RETRY_DELAY_SECONDS: f64 = 0.25;

#[derive(Deserialize)]
pub struct WorkflowRequest {
    definition: Value,
    context: Option<Value>,
}

fn workflow_error(message: impl Into<String>) -> ApiError {
    ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, message)
}

pub(crate) async fn workflows_execute(
    Json(request): Json<WorkflowRequest>,
) -> Result<Json<Value>, ApiError> {
    let definition = request.definition;
    if !definition.is_object() {
        return Err(workflow_error("definition must be an object"));
    }
    let allowed_top = ["name", "nodes", "trigger", "context", "description"];
    if let Some(object) = definition.as_object() {
        if let Some(extra) = object.keys().find(|key| !allowed_top.contains(&key.as_str())) {
            return Err(workflow_error(format!("definition contains unsupported top-level field '{extra}'")));
        }
    }

    let name = definition
        .get("name")
        .cloned()
        .unwrap_or_else(|| json!("unnamed"));
    let name = name.as_str().unwrap_or("");
    if name.trim().is_empty() || name.len() > 128 {
        return Err(workflow_error("workflow name must be a non-empty string up to 128 characters"));
    }
    let description = definition.get("description").cloned().unwrap_or_else(|| json!(""));
    if !description.is_string() || description.as_str().unwrap_or("").len() > 500 {
        return Err(workflow_error("workflow description must be a string up to 500 characters"));
    }

    let trigger = definition
        .get("trigger")
        .cloned()
        .unwrap_or_else(|| json!({"type": "manual"}));
    if !trigger.is_object() || trigger.get("type").and_then(Value::as_str) != Some("manual") {
        return Err(workflow_error(
            "only manual workflow execution is supported by this endpoint",
        ));
    }

    let nodes = definition
        .get("nodes")
        .and_then(Value::as_object)
        .ok_or_else(|| workflow_error(format!("nodes must be an object containing 1 to {MAX_NODES} nodes")))?;
    if nodes.is_empty() || nodes.len() > MAX_NODES {
        return Err(workflow_error(format!("nodes must be an object containing 1 to {MAX_NODES} nodes")));
    }

    let definition_context = definition.get("context").cloned().unwrap_or_else(|| json!({}));
    let call_context = request.context.clone().unwrap_or_else(|| json!({}));
    if !definition_context.is_object() || !call_context.is_object() {
        return Err(workflow_error("workflow context must be an object"));
    }
    let mut merged_context = match definition_context.as_object() {
        Some(map) => map.clone(),
        None => Map::new(),
    };
    if let Some(map) = call_context.as_object() {
        for (key, value) in map {
            merged_context.insert(key.clone(), value.clone());
        }
    }

    let payload = json!({"definition": definition, "context": Value::Object(merged_context.clone())});
    let payload_bytes = serde_json::to_vec(&payload)
        .map_err(|_| workflow_error("workflow definition and context must contain JSON values only"))?;
    if payload_bytes.len() > MAX_PAYLOAD_BYTES {
        return Err(workflow_error(format!(
            "workflow request exceeds the {MAX_PAYLOAD_BYTES}-byte limit"
        )));
    }

    let node_id_pattern = regex::Regex::new(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
        .map_err(|error| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;

    let mut ordered: Vec<String> = Vec::new();
    let mut dependencies: HashMap<String, Vec<String>> = HashMap::new();

    for (node_id, node) in nodes {
        if !node_id_pattern.is_match(node_id) {
            return Err(workflow_error(format!(
                "node IDs must be 1-64 safe ASCII letters, digits, dots, underscores, or hyphens (invalid: '{node_id}')"
            )));
        }
        let node = node.as_object().ok_or_else(|| workflow_error(format!("node {node_id:?} must be an object")))?;
        let allowed_node_fields = [
            "action_type",
            "parameters",
            "depends_on",
            "retry",
            "condition",
            "timeout_seconds",
        ];
        if let Some(extra) = node.keys().find(|key| !allowed_node_fields.contains(&key.as_str())) {
            return Err(workflow_error(format!("node {node_id:?} contains unsupported field '{extra}'")));
        }
        if node.get("timeout_seconds").is_some_and(|value| !value.is_null()) {
            return Err(workflow_error(
                "per-node timeouts are not supported until runtime enforcement is available",
            ));
        }

        let action = node.get("action_type").and_then(Value::as_str).unwrap_or("");
        if !ALLOWED_ACTIONS.contains(&action) {
            return Err(workflow_error(format!(
                "node {node_id:?} action_type must be one of: {}",
                ALLOWED_ACTIONS.join(", ")
            )));
        }

        let parameters = node.get("parameters").cloned().unwrap_or_else(|| json!({}));
        if !parameters.is_object() {
            return Err(workflow_error(format!("node {node_id:?} parameters must be an object")));
        }
        if action == "set_variable" {
            let variable = parameters.get("name").and_then(Value::as_str).unwrap_or("");
            if variable.is_empty() || variable.len() > 128 || variable == "execution_id" {
                return Err(workflow_error(format!(
                    "node {node_id:?} set_variable requires a name up to 128 characters"
                )));
            }
        }
        if action == "log" {
            let message = parameters.get("message").cloned().unwrap_or_else(|| json!(""));
            if !message.is_string() || message.as_str().unwrap_or("").len() > 1000 {
                return Err(workflow_error(format!(
                    "node {node_id:?} log message must be a string up to 1000 characters"
                )));
            }
        }

        let deps = node.get("depends_on").cloned().unwrap_or_else(|| json!([]));
        let deps = deps.as_array().cloned().unwrap_or_default();
        if deps.len() > MAX_NODES
            || deps.iter().any(|dep| !dep.is_string())
        {
            return Err(workflow_error(format!("node {node_id:?} depends_on must be a unique list of node IDs")));
        }
        let mut dep_names: Vec<String> = deps.iter().filter_map(Value::as_str).map(str::to_string).collect();
        let unique_len = dep_names.iter().collect::<HashSet<_>>().len();
        if unique_len != dep_names.len() {
            return Err(workflow_error(format!("node {node_id:?} depends_on must be a unique list of node IDs")));
        }
        for dep in &dep_names {
            if !nodes.contains_key(dep) {
                return Err(workflow_error(format!(
                    "node {node_id:?} depends_on references unknown node '{dep}'"
                )));
            }
        }
        dep_names.sort();
        dependencies.insert(node_id.clone(), dep_names);

        if let Some(retry) = node.get("retry") {
            if !retry.is_object() {
                return Err(workflow_error(format!("node {node_id:?} retry must contain only max_attempts and delay_seconds")));
            }
            if let Some(extra) = retry.as_object().unwrap().keys().find(|key| {
                !["max_attempts", "delay_seconds"].contains(&key.as_str())
            }) {
                return Err(workflow_error(format!(
                    "node {node_id:?} retry must contain only max_attempts and delay_seconds (unexpected '{extra}')"
                )));
            }
            let attempts = retry.get("max_attempts").cloned().unwrap_or(json!(1));
            let delay = retry.get("delay_seconds").cloned().unwrap_or(json!(0));
            let attempts = attempts.as_i64().unwrap_or(0);
            if !(1..=MAX_RETRIES).contains(&attempts) {
                return Err(workflow_error(format!(
                    "node {node_id:?} max_attempts must be between 1 and {MAX_RETRIES}"
                )));
            }
            let delay = delay.as_f64().unwrap_or(-1.0);
            if !(0.0..=MAX_RETRY_DELAY_SECONDS).contains(&delay) {
                return Err(workflow_error(format!(
                    "node {node_id:?} delay_seconds must be between 0 and {MAX_RETRY_DELAY_SECONDS}"
                )));
            }
        }

        if let Some(condition) = node.get("condition") {
            if !condition.is_object() {
                return Err(workflow_error(format!("node {node_id:?} condition is invalid")));
            }
            let condition = condition.as_object().unwrap();
            if let Some(extra) = condition.keys().find(|key| !["field", "operator", "value"].contains(&key.as_str())) {
                return Err(workflow_error(format!("node {node_id:?} condition is invalid (unexpected '{extra}')")));
            }
            let field = condition.get("field").and_then(Value::as_str).unwrap_or("");
            if field.is_empty() || field.len() > 128 {
                return Err(workflow_error(format!("node {node_id:?} condition field must be a non-empty string")));
            }
            let operator = condition.get("operator").and_then(Value::as_str).unwrap_or("==");
            if !ALLOWED_CONDITIONS.contains(&operator) {
                return Err(workflow_error(format!("node {node_id:?} condition operator is unsupported")));
            }
            if operator == "in" && !condition.get("value").is_some_and(Value::is_array) {
                return Err(workflow_error(format!("node {node_id:?} 'in' condition requires a list value")));
            }
        }

        ordered.push(node_id.clone());
    }

    // Topological sort (Kahn) with cycle detection.
    let mut in_degree: HashMap<String, usize> = ordered
        .iter()
        .map(|id| (id.clone(), dependencies.get(id).map(Vec::len).unwrap_or(0)))
        .collect();
    let mut ready: Vec<String> = ordered
        .iter()
        .filter(|id| in_degree.get(*id) == Some(&0))
        .cloned()
        .collect();
    let mut execution_order: Vec<String> = Vec::new();
    while let Some(node_id) = ready.pop() {
        execution_order.push(node_id.clone());
        for other in ordered.iter() {
            if dependencies.get(other).is_some_and(|deps| deps.contains(&node_id)) {
                if let Some(degree) = in_degree.get_mut(other) {
                    *degree -= 1;
                    if *degree == 0 {
                        ready.push(other.clone());
                    }
                }
            }
        }
    }
    if execution_order.len() != ordered.len() {
        return Err(workflow_error("workflow contains a dependency cycle"));
    }

    // Execute built-in actions in dependency order.
    let mut variables: Map<String, Value> = Map::new();
    let mut logs: Vec<Value> = Vec::new();
    let mut executed: Vec<Value> = Vec::new();

    for node_id in execution_order {
        let node = nodes.get(&node_id).and_then(Value::as_object).unwrap();
        let action = node.get("action_type").and_then(Value::as_str).unwrap_or("noop");
        let parameters = node.get("parameters").cloned().unwrap_or_else(|| json!({}));

        if let Some(condition) = node.get("condition") {
            if !evaluate_condition(condition, &variables, &merged_context) {
                executed.push(json!({"id": node_id, "action": action, "status": "skipped"}));
                continue;
            }
        }

        let status = match action {
            "set_variable" => {
                let key = parameters.get("name").and_then(Value::as_str).unwrap_or("").to_string();
                let value = parameters.get("value").cloned().unwrap_or(Value::Null);
                variables.insert(key, value);
                "completed"
            }
            "log" => {
                let message = parameters
                    .get("message")
                    .cloned()
                    .unwrap_or_else(|| json!(""));
                logs.push(json!({"node": node_id, "message": message, "at": now_rfc3339()}));
                "completed"
            }
            _ => "completed",
        };
        executed.push(json!({"id": node_id, "action": action, "status": status}));
    }

    let execution_id = format!("wf_{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
    Ok(Json(json!({
        "status": "completed",
        "execution_id": execution_id,
        "workflow": name,
        "nodes_total": ordered.len(),
        "nodes_executed": executed,
        "variables": Value::Object(variables),
        "logs": logs,
        "context": Value::Object(merged_context),
        "executed_at": now_rfc3339(),
        "note": "Rust runtime executes only the bounded built-in actions (noop, set_variable, log); custom handlers are not exposed by this API."
    })))
}

fn lookup_field<'a>(key: &str, variables: &'a Map<String, Value>, context: &'a Map<String, Value>) -> Option<&'a Value> {
    variables.get(key).or_else(|| context.get(key))
}

fn evaluate_condition(condition: &Value, variables: &Map<String, Value>, context: &Map<String, Value>) -> bool {
    let field = condition.get("field").and_then(Value::as_str).unwrap_or("");
    let operator = condition.get("operator").and_then(Value::as_str).unwrap_or("==");
    let expected = condition.get("value");
    let actual = lookup_field(field, variables, context);

    match operator {
        "exists" => actual.is_some(),
        "not_exists" => actual.is_none(),
        "==" => actual == expected,
        "!=" => actual != expected,
        "in" => match (actual, expected.and_then(Value::as_array)) {
            (Some(value), Some(list)) => list.contains(value),
            _ => false,
        },
        _ => true,
    }
}

// ---------------------------------------------------------------------------
// POST /api/agents/execute
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct AgentExecutionRequest {
    agent_id: String,
    capability: String,
    params: Option<Value>,
}

pub(crate) async fn agents_execute(
    State(state): State<AppState>,
    Json(request): Json<AgentExecutionRequest>,
) -> Result<Json<Value>, ApiError> {
    let known_agents = ["agent_research", "agent_analysis", "agent_quality", "agent_report"];
    if !known_agents.contains(&request.agent_id.as_str()) {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "Unknown built-in agent"));
    }
    if !CAPABILITIES.contains(&request.capability.as_str()) {
        return Err(ApiError::new(
            StatusCode::BAD_REQUEST,
            format!("Invalid capability: {}", request.capability),
        ));
    }
    let params = request.params.unwrap_or_else(|| json!({}));

    // Deterministic capabilities are executed for real; the LLM-backed agent
    // behaviours are not available in the Rust runtime yet.
    match request.capability.as_str() {
        "search" => {
            let query = params.get("query").and_then(Value::as_str).unwrap_or("");
            Ok(Json(json!({
                "agent_id": request.agent_id,
                "capability": request.capability,
                "result": search_objects(&state.db, query, 20),
                "runtime": "rust-deterministic"
            })))
        }
        "query_sql" => {
            let query = params.get("query").and_then(Value::as_str).unwrap_or("");
            if query.trim().is_empty() {
                return Err(ApiError::new(StatusCode::BAD_REQUEST, "params.query is required for query_sql"));
            }
            Ok(Json(json!({
                "agent_id": request.agent_id,
                "capability": request.capability,
                "result": sql_engine::execute_sql(query, &state.db),
                "runtime": "rust-deterministic"
            })))
        }
        "read_object" => {
            let object_id = params.get("object_id").and_then(Value::as_str).unwrap_or("");
            let object = state.db.get_object(object_id).map_err(internal)?.ok_or_else(|| {
                ApiError::new(StatusCode::NOT_FOUND, format!("Object not found: {object_id}"))
            })?;
            Ok(Json(json!({
                "agent_id": request.agent_id,
                "capability": request.capability,
                "result": object,
                "runtime": "rust-deterministic"
            })))
        }
        "export_data" => {
            let objects = state.db.list_objects(None, None, 1000, 0).map_err(internal)?;
            Ok(Json(json!({
                "agent_id": request.agent_id,
                "capability": request.capability,
                "result": {"total": objects.len(), "objects": objects},
                "runtime": "rust-deterministic"
            })))
        }
        other => Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            format!(
                "Capability '{other}' on {} requires the Python/LLM agent runtime and has not been migrated to Rust yet.",
                request.agent_id
            ),
        )),
    }
}

// ---------------------------------------------------------------------------
// POST /api/notebooks/ingest + POST /api/documents/extract_rich
// ---------------------------------------------------------------------------

pub(crate) async fn notebooks_ingest(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    fields: crate::FormFields,
) -> Result<Json<Value>, ApiError> {
    ingest_with_default_filename(state, fields, "analysis.ipynb", "notebook", user.as_ref().map(|principal| principal.id.as_str()))
}

pub(crate) async fn documents_extract_rich(
    State(state): State<AppState>,
    Extension(CurrentUser(user)): Extension<CurrentUser>,
    fields: crate::FormFields,
) -> Result<Json<Value>, ApiError> {
    ingest_with_default_filename(state, fields, "paper.md", "document", user.as_ref().map(|principal| principal.id.as_str()))
}

fn ingest_with_default_filename(
    state: AppState,
    fields: crate::FormFields,
    default_filename: &str,
    default_type: &str,
    owner_id: Option<&str>,
) -> Result<Json<Value>, ApiError> {
    let fields = fields.0;
    let mut filename = fields
        .get("filename")
        .cloned()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| default_filename.to_string());
    let content = fields.get("content").cloned().unwrap_or_default();
    if content.is_empty() {
        return Err(ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, "content is required"));
    }
    if filename.trim().is_empty() {
        filename = default_filename.to_string();
    }

    let lowered = filename.to_lowercase();
    let object_type = if lowered.ends_with(".csv") || lowered.ends_with(".json") {
        "dataset"
    } else if lowered.ends_with(".ipynb") {
        "notebook"
    } else if default_type == "notebook" {
        "notebook"
    } else {
        "document"
    };

    let mut properties = json!({"filename": filename});
    if lowered.ends_with(".csv") {
        properties["raw_csv"] = Value::String(content.clone());
    }
    if lowered.ends_with(".ipynb") || object_type == "notebook" {
        properties["notebook_cells"] = count_notebook_cells(&content);
    }
    if object_type == "document" {
        let (tables, citations) = document_stats(&content);
        properties["extracted_tables"] = json!(tables);
        properties["extracted_citations"] = json!(citations);
    }

    let stored = if let Some(owner_id) = owner_id {
        state.db.create_object_for_owner(
            object_type,
            "generic.v1",
            properties,
            Value::String(content),
            "api://rust-ingest",
            json!({}),
            owner_id,
        )
    } else {
        state.db.create_object(
            object_type,
            "generic.v1",
            properties,
            Value::String(content),
            "api://rust-ingest",
            json!({}),
        )
    }.map_err(internal)?;

    Ok(Json(json!({
        "status": "ok",
        "primary_object_id": stored.get("id").cloned().unwrap_or(Value::Null),
        "objects_created": 1,
        "relations_created": 0,
        "filename": object_name(&stored)
    })))
}

fn count_notebook_cells(content: &str) -> Value {
    match serde_json::from_str::<Value>(content) {
        Ok(Value::Object(notebook)) => {
            let cells = notebook
                .get("cells")
                .and_then(Value::as_array)
                .map(|list| list.len())
                .unwrap_or(0);
            let mut code_cells = 0usize;
            let mut markdown_cells = 0usize;
            if let Some(list) = notebook.get("cells").and_then(Value::as_array) {
                for cell in list {
                    match cell.get("cell_type").and_then(Value::as_str) {
                        Some("code") => code_cells += 1,
                        Some("markdown") => markdown_cells += 1,
                        _ => {}
                    }
                }
            }
            json!({"total": cells, "code": code_cells, "markdown": markdown_cells})
        }
        _ => json!({"total": 0, "code": 0, "markdown": 0, "error": "content is not valid notebook JSON"}),
    }
}

fn document_stats(content: &str) -> (usize, usize) {
    let mut tables = 0usize;
    let mut citations = 0usize;
    let mut in_table = false;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('|') && trimmed.ends_with('|') {
            if !in_table {
                tables += 1;
                in_table = true;
            }
        } else {
            in_table = false;
        }
        let mut rest = trimmed;
        while let Some(position) = rest.find('[') {
            rest = &rest[position + 1..];
            if let Some(end) = rest.find(']') {
                let label = &rest[..end];
                if label.starts_with('^') || label.chars().all(|c| c.is_ascii_digit()) {
                    citations += 1;
                }
                rest = &rest[end + 1..];
            } else {
                break;
            }
        }
    }
    (tables, citations)
}

// ---------------------------------------------------------------------------

fn internal(error: String) -> ApiError {
    ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, error)
}
