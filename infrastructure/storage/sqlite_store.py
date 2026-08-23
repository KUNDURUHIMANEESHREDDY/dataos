"""
Persistent SQLite Storage Backend for DataOS (Rule #28, Rule #30).
Authoritative local relational store with ACID transactions, indexing,
and full support for Objects, Relations, Provenance, and Schemas.
"""

from __future__ import annotations
import sqlite3
import json
import os
import threading
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, Timestamps
from core.relation.model import Relationship
from core.schema.model import Schema
from core.provenance.model import ProvenanceEvent
from .base import StorageBackend


class SQLiteStorage(StorageBackend):
    """SQLite-backed persistent store for DataOS metadata, relations, and provenance."""

    def __init__(self, db_path: str = "dataos.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._mem_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self.db_path == ":memory:" and self._mem_conn:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _close(self, conn: sqlite3.Connection):
        if self.db_path != ":memory:":
            conn.close()

    def close(self):
        if self._mem_conn:
            try:
                self._mem_conn.close()
            except Exception:
                pass
            self._mem_conn = None

    def __del__(self):
        self.close()

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Objects table
            cursor.execute("""
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
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_objects_type ON objects(type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_objects_source ON objects(source)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_objects_deleted_at ON objects(deleted_at)")

            # Relationships table
            cursor.execute("""
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
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relation_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_source_target ON relationships(source_id, target_id)")

            # Schemas table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schemas (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    description TEXT,
                    target_object_type TEXT NOT NULL,
                    definition JSON NOT NULL,
                    strict INTEGER NOT NULL DEFAULT 0,
                    parent_schema_id TEXT,
                    created_at TEXT NOT NULL,
                    metadata JSON NOT NULL
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_schemas_name ON schemas(name)")

            # Provenance events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS provenance_events (
                    id TEXT PRIMARY KEY,
                    target_object_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    description TEXT,
                    inputs JSON NOT NULL,
                    outputs JSON NOT NULL,
                    tools_used JSON NOT NULL,
                    parameters JSON NOT NULL,
                    execution_context JSON NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prov_target ON provenance_events(target_object_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prov_type ON provenance_events(event_type)")

            # Object versions history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS object_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    object_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    data_snapshot JSON NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    change_summary TEXT,
                    FOREIGN KEY (object_id) REFERENCES objects(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_obj_ver ON object_versions(object_id, version)")

            conn.commit()
            self._close(conn)

    def save_object(self, obj: DataObject) -> DataObject:
        """Save a DataObject to SQLite."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO objects (
                    id, type, schema_ref, properties, content, relations,
                    provenance, permissions, created_at, updated_at, deleted_at,
                    valid_from, valid_to, version, source, metadata, indexes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    schema_ref = excluded.schema_ref,
                    properties = excluded.properties,
                    content = excluded.content,
                    relations = excluded.relations,
                    provenance = excluded.provenance,
                    permissions = excluded.permissions,
                    updated_at = excluded.updated_at,
                    deleted_at = excluded.deleted_at,
                    valid_from = excluded.valid_from,
                    valid_to = excluded.valid_to,
                    version = excluded.version,
                    source = excluded.source,
                    metadata = excluded.metadata,
                    indexes = excluded.indexes
            """, (
                obj.id,
                obj.type,
                obj.schema,
                json.dumps(obj.properties, default=str),
                json.dumps(obj.content, default=str),
                json.dumps(obj.relations, default=str),
                json.dumps(obj.provenance, default=str),
                json.dumps(obj.permissions, default=str),
                obj.timestamps.created_at,
                obj.timestamps.updated_at,
                obj.timestamps.deleted_at,
                obj.timestamps.valid_from,
                obj.timestamps.valid_to,
                obj.version,
                obj.source,
                json.dumps(obj.metadata, default=str),
                json.dumps(obj.indexes, default=str),
            ))

            # Record version snapshot
            cursor.execute("""
                INSERT INTO object_versions (
                    object_id, version, data_snapshot, content_hash, created_at, created_by, change_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                obj.id,
                obj.version,
                json.dumps(obj.to_dict(), default=str),
                obj.metadata.get("content_hash", obj.compute_hash()),
                obj.timestamps.updated_at,
                obj.provenance.get("last_modified_by", "system"),
                obj.provenance.get("transformations", [{}])[-1].get("action", "Saved") if obj.provenance.get("transformations") else "Created"
            ))

            conn.commit()
            self._close(conn)
            return obj

    def get_object(self, object_id: str) -> Optional[DataObject]:
        """Retrieve a DataObject by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM objects WHERE id = ? AND deleted_at IS NULL", (object_id,))
            row = cursor.fetchone()
            self._close(conn)

            if not row:
                return None
            return self._row_to_object(row)

    def list_objects(
        self,
        object_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[DataObject]:
        """List DataObjects with optional filters."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            query = "SELECT * FROM objects WHERE deleted_at IS NULL"
            params = []

            if object_type:
                query += " AND type = ?"
                params.append(object_type)
            if source:
                query += " AND source LIKE ?"
                params.append(f"%{source}%")

            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()
            self._close(conn)

            return [self._row_to_object(r) for r in rows]

    def delete_object(self, object_id: str, soft: bool = True) -> bool:
        """Delete a DataObject by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if soft:
                import datetime
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                cursor.execute("UPDATE objects SET deleted_at = ? WHERE id = ?", (now, object_id))
            else:
                cursor.execute("DELETE FROM objects WHERE id = ?", (object_id,))
            
            affected = cursor.rowcount > 0
            conn.commit()
            self._close(conn)
            return affected

    def save_relationship(self, rel: Relationship) -> Relationship:
        """Save a Relationship to SQLite."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO relationships (
                    id, source_id, target_id, relation_type, metadata,
                    confidence, provenance, evidence, created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_id = excluded.source_id,
                    target_id = excluded.target_id,
                    relation_type = excluded.relation_type,
                    metadata = excluded.metadata,
                    confidence = excluded.confidence,
                    provenance = excluded.provenance,
                    evidence = excluded.evidence,
                    updated_at = excluded.updated_at,
                    deleted_at = excluded.deleted_at
            """, (
                rel.id,
                rel.source,
                rel.target,
                rel.relation_type,
                json.dumps(rel.metadata, default=str),
                rel.confidence,
                json.dumps(rel.provenance, default=str),
                json.dumps(rel.evidence, default=str),
                rel.created_at,
                rel.updated_at,
                rel.deleted_at
            ))

            conn.commit()
            self._close(conn)
            return rel

    def get_relationship(self, relation_id: str) -> Optional[Relationship]:
        """Retrieve a Relationship by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM relationships WHERE id = ? AND deleted_at IS NULL", (relation_id,))
            row = cursor.fetchone()
            self._close(conn)

            if not row:
                return None
            return self._row_to_relationship(row)

    def list_relationships(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 1000
    ) -> List[Relationship]:
        """List Relationships with optional filters."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM relationships WHERE deleted_at IS NULL AND confidence >= ?"
            params = [min_confidence]

            if source_id:
                query += " AND source_id = ?"
                params.append(source_id)
            if target_id:
                query += " AND target_id = ?"
                params.append(target_id)
            if relation_type:
                query += " AND relation_type = ?"
                params.append(relation_type)

            query += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            self._close(conn)

            return [self._row_to_relationship(r) for r in rows]

    def delete_relationship(self, relation_id: str, soft: bool = True) -> bool:
        """Delete a Relationship by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if soft:
                import datetime
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                cursor.execute("UPDATE relationships SET deleted_at = ? WHERE id = ?", (now, relation_id))
            else:
                cursor.execute("DELETE FROM relationships WHERE id = ?", (relation_id,))
            affected = cursor.rowcount > 0
            conn.commit()
            self._close(conn)
            return affected

    def save_schema(self, schema: Schema) -> Schema:
        """Save a Schema to SQLite."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO schemas (
                    id, name, version, description, target_object_type,
                    definition, strict, parent_schema_id, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    version = excluded.version,
                    description = excluded.description,
                    target_object_type = excluded.target_object_type,
                    definition = excluded.definition,
                    strict = excluded.strict,
                    parent_schema_id = excluded.parent_schema_id,
                    metadata = excluded.metadata
            """, (
                schema.id,
                schema.name,
                schema.version,
                schema.description,
                schema.target_object_type,
                json.dumps(schema.to_dict(), default=str),
                1 if schema.strict else 0,
                schema.parent_schema_id,
                schema.created_at,
                json.dumps(schema.metadata, default=str)
            ))

            conn.commit()
            self._close(conn)
            return schema

    def get_schema(self, schema_id_or_name: str) -> Optional[Schema]:
        """Retrieve a Schema by ID or name."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT definition FROM schemas WHERE id = ? OR name = ? ORDER BY version DESC LIMIT 1",
                           (schema_id_or_name, schema_id_or_name))
            row = cursor.fetchone()
            self._close(conn)
            if not row:
                return None
            return Schema.from_dict(json.loads(row["definition"]))

    def list_schemas(self) -> List[Schema]:
        """Return all stored schemas."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT definition FROM schemas ORDER BY name, version DESC")
            rows = cursor.fetchall()
            self._close(conn)
            return [Schema.from_dict(json.loads(r["definition"])) for r in rows]

    def record_provenance_event(self, event: ProvenanceEvent) -> ProvenanceEvent:
        """Record a provenance event."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO provenance_events (
                    id, target_object_id, event_type, description, inputs,
                    outputs, tools_used, parameters, execution_context, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.id,
                event.target_object_id,
                event.event_type,
                event.description,
                json.dumps(event.inputs, default=str),
                json.dumps(event.outputs, default=str),
                json.dumps(event.tools_used, default=str),
                json.dumps(event.parameters, default=str),
                json.dumps(event.execution_context, default=str),
                event.created_at
            ))

            conn.commit()
            self._close(conn)
            return event

    def get_provenance_events(self, target_object_id: str, limit: int = 100) -> List[ProvenanceEvent]:
        """Return provenance events for an object."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM provenance_events
                WHERE target_object_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (target_object_id, limit))
            rows = cursor.fetchall()
            self._close(conn)

            return [
                ProvenanceEvent(
                    id=r["id"],
                    target_object_id=r["target_object_id"],
                    event_type=r["event_type"],
                    description=r["description"] or "",
                    inputs=json.loads(r["inputs"]),
                    outputs=json.loads(r["outputs"]),
                    tools_used=json.loads(r["tools_used"]),
                    parameters=json.loads(r["parameters"]),
                    execution_context=json.loads(r["execution_context"]),
                    created_at=r["created_at"]
                )
                for r in rows
            ]

    def get_version_history(self, object_id: str) -> List[Dict[str, Any]]:
        """Return version history for an object."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM object_versions
                WHERE object_id = ?
                ORDER BY version ASC
            """, (object_id,))
            rows = cursor.fetchall()
            self._close(conn)

            return [
                {
                    "object_id": r["object_id"],
                    "version": r["version"],
                    "data_snapshot": json.loads(r["data_snapshot"]),
                    "content_hash": r["content_hash"],
                    "created_at": r["created_at"],
                    "created_by": r["created_by"],
                    "change_summary": r["change_summary"]
                }
                for r in rows
            ]

    def _row_to_object(self, row: sqlite3.Row) -> DataObject:
        timestamps = Timestamps(
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"]
        )
        return DataObject(
            id=row["id"],
            type=row["type"],
            schema=row["schema_ref"],
            properties=json.loads(row["properties"]),
            content=json.loads(row["content"]),
            relations=json.loads(row["relations"]),
            provenance=json.loads(row["provenance"]),
            permissions=json.loads(row["permissions"]),
            timestamps=timestamps,
            version=row["version"],
            source=row["source"],
            metadata=json.loads(row["metadata"]),
            indexes=json.loads(row["indexes"])
        )

    def _row_to_relationship(self, row: sqlite3.Row) -> Relationship:
        return Relationship(
            id=row["id"],
            source=row["source_id"],
            target=row["target_id"],
            relation_type=row["relation_type"],
            metadata=json.loads(row["metadata"]),
            confidence=row["confidence"],
            provenance=json.loads(row["provenance"]),
            evidence=json.loads(row["evidence"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"]
        )
