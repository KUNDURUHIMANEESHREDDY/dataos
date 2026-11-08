use std::{collections::{HashMap, HashSet}, time::{Duration, Instant}};

use csv::StringRecord;
use rusqlite::{Connection, hooks::{AuthAction, AuthContext, Authorization}, types::ValueRef};
use serde_json::{Value, json};

use crate::db::Db;

const MAX_QUERY_BYTES: usize = 64 * 1024;
const MAX_QUERY_SECONDS: u64 = 5;
const MAX_RESULT_ROWS: usize = 10_000;

const FORBIDDEN_KEYWORDS: &[&str] = &[
    "insert", "update", "delete", "drop", "alter", "attach", "detach", "pragma",
    "vacuum", "replace", "create", "truncate",
];

fn is_read_only(query: &str) -> bool {
    let lowered = query.to_lowercase();
    let normalized = lowered.replace(['\n', '\r', '\t'], " ");
    let starts_ok = normalized.split_whitespace().next().map(|word| {
        matches!(word.trim_start_matches('('), "select" | "with")
    }).unwrap_or(false);
    if !starts_ok {
        return false;
    }
    FORBIDDEN_KEYWORDS.iter().all(|keyword| !contains_word(&normalized, keyword))
}

fn contains_word(haystack: &str, needle: &str) -> bool {
    haystack.split(|c: char| !c.is_ascii_alphanumeric() && c != '_')
        .any(|token| token == needle)
}


const ALLOWED_FUNCTIONS: &[&str] = &[
    "abs", "avg", "coalesce", "count", "date", "datetime", "dense_rank",
    "first_value", "glob", "group_concat", "ifnull", "instr", "julianday",
    "lag", "last_value", "lead", "length", "like", "lower", "ltrim", "max",
    "min", "nullif", "nth_value", "ntile", "percent_rank", "rank", "replace",
    "round", "row_number", "rtrim", "strftime", "substr", "sum", "time",
    "total", "trim", "typeof", "unixepoch", "upper",
    "json", "json_array", "json_array_length", "json_extract", "json_insert",
    "json_object", "json_patch", "json_quote", "json_remove", "json_replace",
    "json_set", "json_type", "json_valid", "json_group_array",
    "json_group_object",
];

fn is_allowed_function(name: &str) -> bool {
    ALLOWED_FUNCTIONS.iter().any(|allowed| name.eq_ignore_ascii_case(allowed))
}

fn sanitize_table_name(input: &str) -> String {
    let sanitized: String = input
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '_' { c } else { '_' })
        .collect();
    if sanitized.chars().next().map(|c| c.is_ascii_digit()).unwrap_or(true) {
        format!("tbl_{}", sanitized)
    } else {
        sanitized
    }
}

fn base_name(filename: &str) -> String {
    let normalized = filename.rsplit(['/', '\\']).next().unwrap_or(filename);
    normalized.split_once('.').map(|(head, _)| head.to_string()).unwrap_or_else(|| normalized.to_string())
}

fn table_names(object: &Value) -> Vec<String> {
    let mut names = HashSet::new();
    if let Some(table) = object.pointer("/properties/table_name").and_then(Value::as_str) {
        if !table.trim().is_empty() {
            names.insert(sanitize_table_name(table));
        }
    }
    let filename = object.pointer("/properties/filename").and_then(Value::as_str).unwrap_or("");
    if !filename.trim().is_empty() {
        names.insert(sanitize_table_name(filename));
        let base = base_name(filename);
        if !base.is_empty() {
            names.insert(sanitize_table_name(&base));
        }
    }
    if let Some(id) = object.get("id").and_then(Value::as_str) {
        names.insert(format!("tbl_{}", &id[..id.len().min(8)]));
    }
    names.into_iter().collect()
}

fn rows_from_object(object: &Value) -> (Vec<String>, Vec<Vec<Value>>) {
    if let Some(raw_csv) = object.pointer("/properties/raw_csv").and_then(Value::as_str) {
        return rows_from_csv(raw_csv);
    }
    let rows_value = object.pointer("/properties/sample_rows").and_then(Value::as_array)
        .cloned()
        .or_else(|| object.get("content").and_then(Value::as_array).cloned());
    let rows_value = rows_value.unwrap_or_default();
    rows_from_json_rows(&rows_value)
}

fn rows_from_csv(raw: &str) -> (Vec<String>, Vec<Vec<Value>>) {
    let mut reader = csv::ReaderBuilder::new().flexible(true).has_headers(true).from_reader(raw.as_bytes());
    let headers: Vec<String> = reader.headers().map(StringRecord::iter).map(|iter| iter.map(ToString::to_string).collect()).unwrap_or_default();
    let mut rows = Vec::new();
    for record in reader.records().flatten() {
        rows.push(record.iter().map(|cell| Value::String(cell.to_string())).collect());
    }
    (headers, rows)
}

fn rows_from_json_rows(rows: &[Value]) -> (Vec<String>, Vec<Vec<Value>>) {
    let mut columns = Vec::new();
    let mut seen = HashSet::new();
    for row in rows {
        if let Some(object) = row.as_object() {
            for key in object.keys() {
                if seen.insert(key.clone()) {
                    columns.push(key.clone());
                }
            }
        }
    }
    let mut out = Vec::with_capacity(rows.len());
    for row in rows {
        if let Some(object) = row.as_object() {
            out.push(columns.iter().map(|column| object.get(column).cloned().unwrap_or(Value::Null)).collect());
        }
    }
    (columns, out)
}

fn is_real_column(rows: &[Vec<Value>], index: usize) -> bool {
    rows.iter().all(|row| match row.get(index).unwrap_or(&Value::Null) {
        Value::Null => true,
        Value::Number(number) => number.is_f64() || number.is_i64() || number.is_u64(),
        Value::String(text) => text.trim().parse::<f64>().is_ok(),
        _ => false,
    })
}

fn cell_value(value: &Value, real: bool) -> rusqlite::types::Value {
    if real {
        match value {
            Value::Number(number) => number.as_f64().map(rusqlite::types::Value::Real).unwrap_or(rusqlite::types::Value::Null),
            Value::String(text) => text.trim().parse::<f64>().map(rusqlite::types::Value::Real).unwrap_or(rusqlite::types::Value::Null),
            Value::Bool(boolean) => rusqlite::types::Value::Real(if *boolean { 1.0 } else { 0.0 }),
            _ => rusqlite::types::Value::Null,
        }
    } else {
        match value {
            Value::Null => rusqlite::types::Value::Null,
            Value::String(text) => rusqlite::types::Value::Text(text.clone()),
            other => rusqlite::types::Value::Text(other.to_string()),
        }
    }
}

fn create_table(conn: &Connection, name: &str, columns: &[String], rows: &[Vec<Value>]) -> Result<(), String> {
    let real_columns: Vec<bool> = columns.iter().enumerate().map(|(idx, _)| is_real_column(rows, idx)).collect();
    let mut ddl = format!("CREATE TABLE \"{}\" (", name.replace('"', ""));
    for (index, column) in columns.iter().enumerate() {
        if index > 0 {
            ddl.push_str(", ");
        }
        let safe_column = column.replace('"', "");
        ddl.push_str(&format!("\"{}\" {}", safe_column, if real_columns[index] { "REAL" } else { "TEXT" }));
    }
    ddl.push(')');
    conn.execute(&ddl, []).map_err(|e| e.to_string())?;
    if columns.is_empty() {
        return Ok(());
    }
    let placeholders = columns.iter().map(|_| "?").collect::<Vec<_>>().join(", ");
    let insert = format!(
        "INSERT INTO \"{}\" ({}) VALUES ({})",
        name.replace('"', ""),
        columns.iter().map(|c| format!("\"{}\"", c.replace('"', ""))).collect::<Vec<_>>().join(", "),
        placeholders
    );
    for row in rows {
        let mut stmt = conn.prepare(&insert).map_err(|e| e.to_string())?;
        let params: Vec<rusqlite::types::Value> = columns.iter().enumerate().map(|(index, _)| cell_value(row.get(index).unwrap_or(&Value::Null), real_columns[index])).collect();
        stmt.execute(rusqlite::params_from_iter(params)).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn value_ref_to_json(value: ValueRef<'_>) -> Value {
    match value {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(number) => Value::from(number),
        ValueRef::Real(number) => json!(number),
        ValueRef::Text(text) => Value::String(String::from_utf8_lossy(text).to_string()),
        ValueRef::Blob(bytes) => Value::String(format!("<{} bytes>", bytes.len())),
    }
}

pub fn execute_sql(query: &str, db: &Db) -> Value {
    execute_sql_scoped(query, db, None)
}

/// Execute a read-only query against only the datasets owned by one principal.
/// This is used by user-scoped workflows; global SQL remains an admin-only route.
pub fn execute_sql_for_owner(query: &str, db: &Db, owner_id: &str) -> Value {
    execute_sql_scoped(query, db, Some(owner_id))
}

fn execute_sql_scoped(query: &str, db: &Db, owner_id: Option<&str>) -> Value {
    if query.as_bytes().len() > MAX_QUERY_BYTES {
        let error = format!("SQL query exceeds the {MAX_QUERY_BYTES}-byte limit");
        return json!({
            "success": false,
            "query": query,
            "columns": [],
            "row_count": 0,
            "rows": [],
            "execution_time_ms": 0.0,
            "registered_tables": [], "ambiguous_table_names": [],
            "provenance": {"engine": "rust-sqlite", "query_text": query, "error": error},
            "error": error
        });
    }

    if !is_read_only(query) {
        return json!({
            "success": false,
            "query": query,
            "columns": [],
            "row_count": 0,
            "rows": [],
            "execution_time_ms": 0.0,
            "registered_tables": [], "ambiguous_table_names": [],
            "provenance": {"engine": "rust-sqlite", "query_text": query, "error": "Only read-only SELECT/WITH queries are permitted"},
            "error": "Only read-only SELECT/WITH queries are permitted"
        });
    }

    match execute_sql_inner(query, db, owner_id) {
        Ok(value) => value,
        Err(error) => json!({
            "success": false,
            "query": query,
            "columns": [],
            "row_count": 0,
            "rows": [],
            "execution_time_ms": 0.0,
            "registered_tables": [], "ambiguous_table_names": [],
            "provenance": {"engine": "rust-sqlite", "query_text": query, "error": error},
            "error": error
        }),
    }
}

fn execute_sql_inner(query: &str, db: &Db, owner_id: Option<&str>) -> Result<Value, String> {
    let start = std::time::Instant::now();
    let datasets = if let Some(owner_id) = owner_id {
        db.list_objects_readable(owner_id, Some("dataset"), None, 100, 0)?
    } else {
        db.list_objects(Some("dataset"), None, 100, 0)?
    };
    let conn = Connection::open_in_memory().map_err(|e| e.to_string())?;
    let mut registered_tables = Vec::new();
    let mut source_object_ids = Vec::new();

    // Build the alias ownership map before registering any table. SQLite treats
    // identifiers case-insensitively, so aliases shared by multiple datasets must
    // be omitted for every owner instead of letting iteration order choose a winner.
    let mut prepared_datasets = Vec::new();
    let mut alias_owners: HashMap<String, HashSet<usize>> = HashMap::new();
    for (index, object) in datasets.iter().enumerate() {
        let (columns, rows) = rows_from_object(object);
        if columns.is_empty() || rows.is_empty() {
            continue;
        }
        let mut names = table_names(object);
        names.sort_by_key(|name| name.to_ascii_lowercase());
        names.dedup_by(|left, right| left.eq_ignore_ascii_case(right));
        for table in &names {
            alias_owners
                .entry(table.to_ascii_lowercase())
                .or_default()
                .insert(index);
        }
        prepared_datasets.push((index, object, columns, rows, names));
    }

    let mut ambiguous_table_names = Vec::new();
    for (_index, object, columns, rows, names) in prepared_datasets {
        let mut tables_for_object = Vec::new();
        for table in names {
            let normalized = table.to_ascii_lowercase();
            if alias_owners
                .get(&normalized)
                .map(|owners| owners.len() > 1)
                .unwrap_or(false)
            {
                ambiguous_table_names.push(table);
                continue;
            }
            if create_table(&conn, &table, &columns, &rows).is_ok() {
                tables_for_object.push(table);
            }
        }
        if !tables_for_object.is_empty() {
            registered_tables.extend(tables_for_object);
            if let Some(id) = object.get("id").and_then(Value::as_str) {
                source_object_ids.push(id.to_string());
            }
        }
    }
    ambiguous_table_names.sort_by_key(|name| name.to_ascii_lowercase());
    ambiguous_table_names.dedup_by(|left, right| left.eq_ignore_ascii_case(right));

    // Dataset registration above is trusted setup. From this point onward, caller SQL
    // is constrained by SQLite itself rather than relying on keyword matching alone.
    conn.execute_batch("PRAGMA query_only = ON").map_err(|e| e.to_string())?;
    conn.authorizer(Some(|context: AuthContext<'_>| match context.action {
        AuthAction::Select | AuthAction::Read { .. } | AuthAction::Recursive => Authorization::Allow,
        AuthAction::Function { function_name } => {
            if is_allowed_function(function_name) {
                Authorization::Allow
            } else {
                Authorization::Deny
            }
        }
        // Deny writes, schema changes, PRAGMAs, transactions, ATTACH/DETACH,
        // virtual-table operations, and unknown future SQLite authorizer actions.
        _ => Authorization::Deny,
    }));

    let deadline = Instant::now() + Duration::from_secs(MAX_QUERY_SECONDS);
    conn.progress_handler(1_000, Some(move || Instant::now() >= deadline));

    let mut stmt = conn.prepare(query).map_err(|e| e.to_string())?;
    if !stmt.readonly() {
        return Err("Only read-only SQL statements are permitted".to_string());
    }
    let column_count = stmt.column_count();
    let columns: Vec<String> = (0..column_count).map(|index| stmt.column_name(index).unwrap_or("column").to_string()).collect();
    let mut rows = stmt.query([]).map_err(|e| e.to_string())?;
    let mut records = Vec::new();
    while let Some(row) = rows.next().map_err(|e| e.to_string())? {
        if records.len() >= MAX_RESULT_ROWS {
            return Err(format!("SQL query result exceeds the {MAX_RESULT_ROWS}-row limit"));
        }
        let mut record = serde_json::Map::new();
        for index in 0..column_count {
            record.insert(columns[index].clone(), value_ref_to_json(row.get_ref(index).map_err(|e| e.to_string())?));
        }
        records.push(Value::Object(record));
    }

    Ok(json!({
        "success": true,
        "query": query,
        "columns": columns,
        "row_count": records.len(),
        "rows": records,
        "execution_time_ms": (start.elapsed().as_secs_f64() * 1000.0).round(),
        "registered_tables": registered_tables,
        "ambiguous_table_names": ambiguous_table_names,
        "provenance": {
            "engine": "rust-sqlite",
            "query_text": query,
            "input_sources": source_object_ids,
            "registered_tables": registered_tables,
            "row_count": records.len(),
            "executed_by": "rust-backend",
        },
        "error": Value::Null
    }))
}


#[cfg(test)]
mod function_policy_tests {
    use super::{execute_sql, is_allowed_function};
    use crate::db::Db;
    use serde_json::json;

    #[test]
    fn allows_the_shared_safe_function_surface_case_insensitively() {
        for function in ["count", "AVG", "json_extract", "row_number", "LOWER"] {
            assert!(is_allowed_function(function), "expected {function} to be allowed");
        }
    }

    #[test]
    fn rejects_unreviewed_and_nondeterministic_functions() {
        for function in ["random", "randomblob", "load_extension", "readfile", "sqlite_version"] {
            assert!(!is_allowed_function(function), "expected {function} to be denied");
        }
    }

    #[test]
    fn enforces_function_policy_during_real_sql_execution() {
        let db = Db::open(":memory:").expect("open isolated database");
        db.create_object(
            "dataset",
            "dataset.v1",
            json!({"filename": "employees.csv", "table_name": "employees"}),
            json!([
                {"name": "Alice", "salary": 120.0},
                {"name": "Bob", "salary": 80.0}
            ]),
            "test://employees",
            json!({}),
        )
        .expect("register test dataset");

        let allowed = execute_sql(
            "SELECT LOWER(name) AS normalized_name, ROUND(AVG(salary), 2) AS avg_salary FROM employees",
            &db,
        );
        assert_eq!(allowed["success"], true, "safe query failed: {allowed}");

        let denied = execute_sql("SELECT random()", &db);
        assert_eq!(denied["success"], false, "unreviewed function was allowed: {denied}");
    }
}
