use std::sync::Mutex;

use chrono::Utc;
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};
use uuid::Uuid;

use crate::auth::{User, verify_password};

#[derive(Debug)]
pub struct Db {
    conn: Mutex<Connection>,
}

fn now() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
}

fn json_text(value: &Value) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "{}".to_string())
}

fn parse_json(text: Option<String>) -> Value {
    text.and_then(|value| serde_json::from_str(&value).ok()).unwrap_or(Value::Null)
}

fn object_select_sql() -> &'static str {
    "SELECT id, type, schema_ref, properties, content, relations, provenance, permissions,\n            created_at, updated_at, deleted_at, valid_from, valid_to, version, source, metadata, indexes\n     FROM objects"
}

fn relationship_select_sql() -> &'static str {
    "SELECT id, source_id, target_id, relation_type, metadata, confidence, provenance, evidence,\n            created_at, updated_at, deleted_at\n     FROM relationships"
}

pub fn object_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    let properties = parse_json(row.get(3)?);
    let content = parse_json(row.get(4)?);
    let relations = parse_json(row.get(5)?);
    let provenance = parse_json(row.get(6)?);
    let permissions = parse_json(row.get(7)?);
    let created_at: String = row.get(8)?;
    let updated_at: String = row.get(9)?;
    let deleted_at: Option<String> = row.get(10)?;
    let valid_from: Option<String> = row.get(11)?;
    let valid_to: Option<String> = row.get(12)?;
    let version: i64 = row.get(13)?;
    let source: String = row.get(14)?;
    let metadata = parse_json(row.get(15)?);
    let indexes = parse_json(row.get(16)?);
    Ok(json!({
        "id": row.get::<_, String>(0)?,
        "type": row.get::<_, String>(1)?,
        "schema": row.get::<_, String>(2)?,
        "properties": properties,
        "content": content,
        "relations": relations,
        "provenance": provenance,
        "permissions": permissions,
        "timestamps": {
            "created_at": created_at,
            "updated_at": updated_at,
            "deleted_at": deleted_at,
            "valid_from": valid_from,
            "valid_to": valid_to
        },
        "version": version,
        "source": source,
        "metadata": metadata,
        "indexes": indexes
    }))
}

pub fn relationship_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    Ok(json!({
        "id": row.get::<_, String>(0)?,
        "source": row.get::<_, String>(1)?,
        "target": row.get::<_, String>(2)?,
        "relation_type": row.get::<_, String>(3)?,
        "metadata": parse_json(row.get(4)?),
        "confidence": row.get::<_, f64>(5)?,
        "provenance": parse_json(row.get(6)?),
        "evidence": parse_json(row.get(7)?),
        "created_at": row.get::<_, String>(8)?,
        "updated_at": row.get::<_, String>(9)?,
        "deleted_at": row.get::<_, Option<String>>(10)?
    }))
}

fn compute_content_hash(obj: &Value) -> String {
    let payload = json!({
        "type": obj.get("type").cloned().unwrap_or(Value::Null),
        "schema": obj.get("schema").cloned().unwrap_or(Value::Null),
        "properties": obj.get("properties").cloned().unwrap_or(Value::Null),
        "content": obj.get("content").cloned().unwrap_or(Value::Null),
        "source": obj.get("source").cloned().unwrap_or(Value::Null),
        "version": obj.get("version").cloned().unwrap_or(Value::Null)
    });
    use sha2::{Digest, Sha256};
    let serialized = serde_json::to_string(&payload).unwrap_or_else(|_| "{}".to_string());
    hex::encode(Sha256::digest(serialized.as_bytes()))
}

impl Db {
    pub fn open(path: &str) -> Result<Self, String> {
        let conn = Connection::open(path).map_err(|e| e.to_string())?;
        let db = Self { conn: Mutex::new(conn) };
        db.init_schema()?;
        Ok(db)
    }

    fn init_schema(&self) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS objects (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                schema_ref TEXT NOT NULL,
                properties JSON NOT NULL,
                content JSON NOT NULL,
                relations JSON NOT NULL,
                provenance JSON NOT NULL,
                permissions JSON NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                valid_from TEXT,
                valid_to TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL,
                metadata JSON NOT NULL,
                indexes JSON NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_objects_type ON objects(type);
            CREATE INDEX IF NOT EXISTS idx_objects_source ON objects(source);
            CREATE INDEX IF NOT EXISTS idx_objects_deleted_at ON objects(deleted_at);
            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                metadata JSON NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                provenance JSON NOT NULL,
                evidence JSON NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                FOREIGN KEY (source_id) REFERENCES objects(id) ON DELETE CASCADE,
                FOREIGN KEY (target_id) REFERENCES objects(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relation_type);
            CREATE TABLE IF NOT EXISTS object_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                data_snapshot JSON NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT,
                change_summary TEXT
            );
            CREATE TABLE IF NOT EXISTS dataos_users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL DEFAULT 'viewer',
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            "#,
        )
        .map_err(|e| e.to_string())
    }

    pub fn health_check(&self) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        conn.query_row("SELECT COUNT(*) FROM objects LIMIT 1", [], |_| Ok(())).map_err(|e| e.to_string())
    }

    pub fn list_objects(&self, object_type: Option<&str>, source: Option<&str>, limit: i64, offset: i64) -> Result<Vec<Value>, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        let mut sql = format!("{} WHERE deleted_at IS NULL", object_select_sql());
        let mut values: Vec<Value> = Vec::new();
        if let Some(kind) = object_type {
            sql.push_str(" AND type = ?");
            values.push(Value::String(kind.to_string()));
        }
        if let Some(src) = source {
            sql.push_str(" AND source LIKE ?");
            values.push(Value::String(format!("%{}%", src)));
        }
        sql.push_str(" ORDER BY updated_at DESC LIMIT ? OFFSET ?");
        values.push(Value::from(limit));
        values.push(Value::from(offset));
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let mut rows = stmt.query(rusqlite::params_from_iter(values.iter().map(param_value).map(|v| v.unwrap_or(rusqlite::types::Value::Null)))).map_err(|e| e.to_string())?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            out.push(object_from_row(row).map_err(|e| e.to_string())?);
        }
        Ok(out)
    }

    pub fn count_objects(&self, object_type: Option<&str>, source: Option<&str>) -> Result<i64, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        let mut sql = "SELECT COUNT(*) FROM objects WHERE deleted_at IS NULL".to_string();
        let mut values: Vec<Value> = Vec::new();
        if let Some(kind) = object_type {
            sql.push_str(" AND type = ?");
            values.push(Value::String(kind.to_string()));
        }
        if let Some(src) = source {
            sql.push_str(" AND source LIKE ?");
            values.push(Value::String(format!("%{}%", src)));
        }
        conn.query_row(&sql, rusqlite::params_from_iter(values.iter().map(param_value).map(|v| v.unwrap_or(rusqlite::types::Value::Null))), |row| row.get(0)).map_err(|e| e.to_string())
    }

    pub fn get_object(&self, id: &str) -> Result<Option<Value>, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        conn.query_row(&format!("{} WHERE id = ? AND deleted_at IS NULL", object_select_sql()), [id], object_from_row).optional().map_err(|e| e.to_string())
    }

    pub fn create_object(&self, object_type: &str, schema: &str, properties: Value, content: Value, source: &str, metadata: Value) -> Result<Value, String> {
        let created = now();
        let mut object = json!({
            "id": Uuid::new_v4().to_string(),
            "type": object_type,
            "schema": schema,
            "properties": properties,
            "content": content,
            "relations": {},
            "provenance": {
                "created_by": "dataos-rust",
                "creation_timestamp": created,
                "input_sources": [source],
                "transformations": []
            },
            "permissions": {"owner": "system", "read": ["*"], "write": ["owner"]},
            "timestamps": {
                "created_at": created,
                "updated_at": created,
                "deleted_at": Value::Null,
                "valid_from": Value::Null,
                "valid_to": Value::Null
            },
            "version": 1,
            "source": source,
            "metadata": metadata,
            "indexes": {}
        });
        let hash = compute_content_hash(&object);
        if let Value::Object(map) = &mut object["metadata"] {
            map.entry("content_hash".to_string()).or_insert(Value::String(hash.clone()));
        }
        self.save_object(&object)?;
        Ok(object)
    }

    pub fn save_object(&self, object: &Value) -> Result<(), String> {
        let id = object["id"].as_str().ok_or_else(|| "object id missing".to_string())?.to_string();
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        conn.execute(
            "INSERT INTO objects (
                id, type, schema_ref, properties, content, relations, provenance, permissions,
                created_at, updated_at, deleted_at, valid_from, valid_to, version, source, metadata, indexes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type, schema_ref=excluded.schema_ref, properties=excluded.properties,
                content=excluded.content, relations=excluded.relations, provenance=excluded.provenance,
                permissions=excluded.permissions, updated_at=excluded.updated_at, deleted_at=excluded.deleted_at,
                valid_from=excluded.valid_from, valid_to=excluded.valid_to, version=excluded.version,
                source=excluded.source, metadata=excluded.metadata, indexes=excluded.indexes",
            params![
                id.clone(),
                object["type"].as_str().unwrap_or("document"),
                object["schema"].as_str().unwrap_or("generic.v1"),
                json_text(&object["properties"]),
                json_text(&object["content"]),
                json_text(&object["relations"]),
                json_text(&object["provenance"]),
                json_text(&object["permissions"]),
                object["timestamps"]["created_at"].as_str().unwrap_or("1970-01-01T00:00:00+00:00"),
                object["timestamps"]["updated_at"].as_str().unwrap_or("1970-01-01T00:00:00+00:00"),
                object["timestamps"]["deleted_at"].as_str(),
                object["timestamps"]["valid_from"].as_str(),
                object["timestamps"]["valid_to"].as_str(),
                object["version"].as_i64().unwrap_or(1),
                object["source"].as_str().unwrap_or("dataos://rust"),
                json_text(&object["metadata"]),
                json_text(&object["indexes"])
            ],
        ).map_err(|e| e.to_string())?;
        conn.execute(
            "INSERT INTO object_versions (object_id, version, data_snapshot, content_hash, created_at, created_by, change_summary)
             VALUES (?, ?, ?, ?, ?, ?, ?)",
            params![
                id,
                object["version"].as_i64().unwrap_or(1),
                json_text(object),
                object.pointer("/metadata/content_hash").and_then(Value::as_str).unwrap_or_default(),
                object["timestamps"]["updated_at"].as_str().unwrap_or_default(),
                object.pointer("/provenance/last_modified_by").and_then(Value::as_str).unwrap_or("system"),
                "Rust service save"
            ],
        ).map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn delete_object(&self, id: &str, soft: bool) -> Result<bool, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        if soft {
            conn.execute("UPDATE objects SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", params![now(), id])
        } else {
            conn.execute("DELETE FROM objects WHERE id = ?", [id])
        }.map(|n| n > 0).map_err(|e| e.to_string())
    }

    pub fn list_relationships(&self, source_id: Option<&str>, target_id: Option<&str>, relation_type: Option<&str>, min_confidence: f64, limit: i64, offset: i64) -> Result<Vec<Value>, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        let mut sql = format!("{} WHERE deleted_at IS NULL AND confidence >= ?", relationship_select_sql());
        let mut values: Vec<Value> = vec![Value::from(min_confidence)];
        if let Some(source) = source_id { sql.push_str(" AND source_id = ?"); values.push(Value::String(source.to_string())); }
        if let Some(target) = target_id { sql.push_str(" AND target_id = ?"); values.push(Value::String(target.to_string())); }
        if let Some(kind) = relation_type { sql.push_str(" AND relation_type = ?"); values.push(Value::String(kind.to_string())); }
        sql.push_str(" ORDER BY confidence DESC, updated_at DESC LIMIT ? OFFSET ?");
        values.push(Value::from(limit));
        values.push(Value::from(offset));
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let mut rows = stmt.query(rusqlite::params_from_iter(values.iter().map(param_value).map(|v| v.unwrap_or(rusqlite::types::Value::Null)))).map_err(|e| e.to_string())?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            out.push(relationship_from_row(row).map_err(|e| e.to_string())?);
        }
        Ok(out)
    }

    pub fn count_relationships(&self, source_id: Option<&str>, target_id: Option<&str>, relation_type: Option<&str>, min_confidence: f64) -> Result<i64, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        let mut sql = "SELECT COUNT(*) FROM relationships WHERE deleted_at IS NULL AND confidence >= ?".to_string();
        let mut values: Vec<Value> = vec![Value::from(min_confidence)];
        if let Some(source) = source_id { sql.push_str(" AND source_id = ?"); values.push(Value::String(source.to_string())); }
        if let Some(target) = target_id { sql.push_str(" AND target_id = ?"); values.push(Value::String(target.to_string())); }
        if let Some(kind) = relation_type { sql.push_str(" AND relation_type = ?"); values.push(Value::String(kind.to_string())); }
        conn.query_row(&sql, rusqlite::params_from_iter(values.iter().map(param_value).map(|v| v.unwrap_or(rusqlite::types::Value::Null))), |row| row.get(0)).map_err(|e| e.to_string())
    }

    pub fn create_relationship(&self, source: &str, target: &str, relation_type: &str, confidence: f64, metadata: Value) -> Result<Value, String> {
        let created = now();
        let provenance = json!({"established_by":"dataos-rust", "method":"explicit", "timestamp": created});
        let evidence = Value::Array(vec![]);
        let rel = json!({
            "id": Uuid::new_v4().to_string(),
            "source": source,
            "target": target,
            "relation_type": relation_type,
            "metadata": metadata,
            "confidence": confidence.clamp(0.0, 1.0),
            "provenance": provenance,
            "evidence": evidence,
            "created_at": created,
            "updated_at": created,
            "deleted_at": Value::Null
        });
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        conn.execute(
            "INSERT INTO relationships (id, source_id, target_id, relation_type, metadata, confidence, provenance, evidence, created_at, updated_at, deleted_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                rel["id"].as_str().unwrap_or_default(),
                source,
                target,
                relation_type,
                json_text(&rel["metadata"]),
                rel["confidence"].as_f64().unwrap_or(1.0),
                json_text(&rel["provenance"]),
                json_text(&rel["evidence"]),
                created,
                created,
                Option::<String>::None
            ],
        ).map_err(|e| e.to_string())?;
        Ok(rel)
    }

    pub fn user_register(&self, username: &str, email: &str, password: &str, role: &str) -> Result<User, String> {
        let user = crate::auth::new_user(username, email, password, role)?;
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        conn.execute(
            "INSERT INTO dataos_users (id, username, email, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            params![user.id, user.username, user.email, user.role, user.password_hash, user.created_at],
        ).map_err(|e| {
            if e.to_string().contains("UNIQUE") { "A user with this username or email already exists.".to_string() } else { e.to_string() }
        })?;
        Ok(user)
    }

    pub fn user_login(&self, login: &str, password: &str) -> Result<Option<User>, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        let user = conn.query_row(
            "SELECT id, username, email, role, password_hash, created_at FROM dataos_users WHERE username = ? OR email = ?",
            params![login, login.to_lowercase()],
            |row| Ok(User {
                id: row.get(0)?,
                username: row.get(1)?,
                email: row.get(2)?,
                role: row.get(3)?,
                password_hash: row.get(4)?,
                created_at: row.get(5)?,
            }),
        ).optional().map_err(|e| e.to_string())?;
        Ok(user.filter(|u| verify_password(password, &u.password_hash)))
    }

    pub fn user_by_id(&self, user_id: &str) -> Result<Option<User>, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        conn.query_row(
            "SELECT id, username, email, role, password_hash, created_at FROM dataos_users WHERE id = ?",
            [user_id],
            |row| Ok(User {
                id: row.get(0)?,
                username: row.get(1)?,
                email: row.get(2)?,
                role: row.get(3)?,
                password_hash: row.get(4)?,
                created_at: row.get(5)?,
            }),
        ).optional().map_err(|e| e.to_string())
    }

    pub fn list_users(&self) -> Result<Vec<Value>, String> {
        let conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        let mut stmt = conn.prepare("SELECT id, username, email, role, password_hash, created_at FROM dataos_users ORDER BY created_at").map_err(|e| e.to_string())?;
        let mut rows = stmt.query([]).map_err(|e| e.to_string())?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            let user = User {
                id: row.get(0).map_err(|e| e.to_string())?,
                username: row.get(1).map_err(|e| e.to_string())?,
                email: row.get(2).map_err(|e| e.to_string())?,
                role: row.get(3).map_err(|e| e.to_string())?,
                password_hash: row.get(4).map_err(|e| e.to_string())?,
                created_at: row.get(5).map_err(|e| e.to_string())?,
            };
            out.push(crate::auth::user_payload(&user));
        }
        Ok(out)
    }
}

fn param_value(value: &Value) -> Option<rusqlite::types::Value> {
    match value {
        Value::Null => Some(rusqlite::types::Value::Null),
        Value::Bool(v) => Some(rusqlite::types::Value::Integer(i64::from(*v))),
        Value::Number(n) => n.as_i64().map(rusqlite::types::Value::Integer).or_else(|| n.as_f64().map(rusqlite::types::Value::Real)),
        Value::String(v) => Some(rusqlite::types::Value::Text(v.clone())),
        Value::Array(_) | Value::Object(_) => Some(rusqlite::types::Value::Text(serde_json::to_string(value).ok()?)),
    }
}
