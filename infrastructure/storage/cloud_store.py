"""
Cloud Storage Backend for DataOS (Rule #50).
Implements S3, GCS, and Azure Blob Storage backends.
Uses cloud bucket for blob data + embedded SQLite index for metadata queries.
"""

from __future__ import annotations
import io
import json
import os
import datetime
import threading
from typing import Dict, Any, List, Optional
from infrastructure.storage.base import StorageBackend
from core.object.model import DataObject, Timestamps
from core.relation.model import Relationship
from core.schema.model import Schema
from core.provenance.model import ProvenanceEvent


class CloudStorageBackend(StorageBackend):
    """
    Dual-mode cloud storage: cloud bucket for data, SQLite for metadata indexing.
    Subclasses provide the cloud client (s3, gcs, azure).
    """

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "dataos/",
        index_db: str = ":memory:",
        credentials: Optional[Dict[str, Any]] = None,
    ):
        self.bucket_name = bucket_name
        self.prefix = prefix.rstrip("/") + "/"
        self.credentials = credentials or {}
        self._lock = threading.Lock()
        self._client = None
        self._init_index(index_db)

    def _get_client(self):
        raise NotImplementedError("Subclasses must provide a cloud client")

    def _upload_blob(self, key: str, data: bytes, content_type: str = "application/json") -> Dict[str, Any]:
        raise NotImplementedError

    def _download_blob(self, key: str) -> Optional[bytes]:
        raise NotImplementedError

    def _delete_blob(self, key: str) -> bool:
        raise NotImplementedError

    def _list_blobs(self, prefix: str = "") -> List[str]:
        raise NotImplementedError

    def _init_index(self, db_path: str) -> None:
        import sqlite3
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        c = self._conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS objects (
                id TEXT PRIMARY KEY, type TEXT, schema TEXT, properties TEXT,
                content TEXT, relations TEXT, provenance TEXT, permissions TEXT,
                timestamps TEXT, version INTEGER, source TEXT, metadata TEXT,
                indexes TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY, source_id TEXT, target_id TEXT,
                relation_type TEXT, metadata TEXT, confidence REAL,
                provenance TEXT, evidence TEXT, created_at TEXT,
                updated_at TEXT, deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS schemas (
                id TEXT PRIMARY KEY, name TEXT, version INTEGER,
                description TEXT, target_object_type TEXT, fields TEXT,
                strict_mode INTEGER, parent_schema_id TEXT,
                created_at TEXT, metadata TEXT
            );
            CREATE TABLE IF NOT EXISTS provenance_events (
                id TEXT PRIMARY KEY, target_object_id TEXT, event_type TEXT,
                description TEXT, inputs TEXT, outputs TEXT,
                tools_used TEXT, parameters TEXT, execution_context TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS object_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, object_id TEXT,
                version INTEGER, snapshot TEXT, created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_obj_type ON objects(type);
            CREATE INDEX IF NOT EXISTS idx_obj_source ON objects(source);
            CREATE INDEX IF NOT EXISTS idx_obj_deleted ON objects(deleted_at);
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relation_type);
            CREATE INDEX IF NOT EXISTS idx_prov_target ON provenance_events(target_object_id);
        """)
        self._conn.commit()

    def close(self):
        """Close database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __del__(self):
        self.close()

    def _row_to_object(self, row) -> DataObject:
        d = dict(row)
        return DataObject(
            id=d["id"], type=d["type"], schema=d["schema"],
            properties=json.loads(d["properties"]) if d["properties"] else {},
            content=json.loads(d["content"]) if d["content"] else {},
            relations=json.loads(d["relations"]) if d["relations"] else {},
            provenance=json.loads(d["provenance"]) if d["provenance"] else {},
            permissions=json.loads(d["permissions"]) if d["permissions"] else {},
            timestamps=Timestamps.from_dict(json.loads(d["timestamps"])) if d["timestamps"] else Timestamps(),
            version=d["version"], source=d["source"] or "",
            metadata=json.loads(d["metadata"]) if d["metadata"] else {},
            indexes=json.loads(d["indexes"]) if d["indexes"] else {},
        )

    def _row_to_relationship(self, row) -> Relationship:
        d = dict(row)
        return Relationship(
            id=d["id"], source=d["source_id"], target=d["target_id"],
            relation_type=d["relation_type"],
            metadata=json.loads(d["metadata"]) if d["metadata"] else {},
            confidence=d["confidence"] or 0.0,
            provenance=json.loads(d["provenance"]) if d["provenance"] else {},
            evidence=json.loads(d["evidence"]) if d["evidence"] else [],
            created_at=d["created_at"] or "", updated_at=d["updated_at"] or "",
            deleted_at=d.get("deleted_at"),
        )

    def save_object(self, obj: DataObject) -> DataObject:
        """Save a DataObject to storage."""
        with self._lock:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            c = self._conn.cursor()
            c.execute(
                """INSERT OR REPLACE INTO objects
                   (id, type, schema, properties, content, relations, provenance,
                    permissions, timestamps, version, source, metadata, indexes,
                    created_at, updated_at, deleted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (obj.id, obj.type, obj.schema,
                 json.dumps(obj.properties, default=str),
                 json.dumps(obj.content, default=str),
                 json.dumps(obj.relations, default=str),
                 json.dumps(obj.provenance, default=str),
                 json.dumps(obj.permissions, default=str),
                 json.dumps(obj.timestamps.to_dict(), default=str),
                 obj.version, obj.source,
                 json.dumps(obj.metadata, default=str),
                 json.dumps(obj.indexes, default=str),
                 obj.timestamps.created_at, now, obj.timestamps.deleted_at),
            )
            c.execute(
                "INSERT INTO object_versions (object_id, version, snapshot, created_at) VALUES (?,?,?,?)",
                (obj.id, obj.version, json.dumps(obj.to_dict(), default=str), now),
            )
            self._conn.commit()
            # Upload to cloud
            try:
                key = f"{self.prefix}objects/{obj.id}.json"
                self._upload_blob(key, json.dumps(obj.to_dict(), default=str).encode("utf-8"))
            except Exception:
                pass
            return obj

    def get_object(self, object_id: str) -> Optional[DataObject]:
        """Retrieve a DataObject by ID."""
        with self._lock:
            c = self._conn.cursor()
            c.execute("SELECT * FROM objects WHERE id = ? AND deleted_at IS NULL", (object_id,))
            row = c.fetchone()
            if row:
                return self._row_to_object(row)
        # Fallback: try cloud
        try:
            key = f"{self.prefix}objects/{object_id}.json"
            data = self._download_blob(key)
            if data:
                return DataObject.from_dict(json.loads(data))
        except Exception:
            pass
        return None

    def list_objects(self, object_type=None, source=None, limit=100, offset=0) -> List[DataObject]:
        """List DataObjects with optional filters."""
        with self._lock:
            query = "SELECT * FROM objects WHERE deleted_at IS NULL"
            params: list = []
            if object_type:
                query += " AND type = ?"
                params.append(object_type)
            if source:
                query += " AND source = ?"
                params.append(source)
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            c = self._conn.cursor()
            c.execute(query, params)
            return [self._row_to_object(r) for r in c.fetchall()]

    def delete_object(self, object_id: str, soft=True) -> bool:
        """Delete a DataObject by ID."""
        with self._lock:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            c = self._conn.cursor()
            if soft:
                c.execute("UPDATE objects SET deleted_at = ? WHERE id = ?", (now, object_id))
            else:
                c.execute("DELETE FROM objects WHERE id = ?", (object_id,))
            self._conn.commit()
            if c.rowcount > 0:
                try:
                    self._delete_blob(f"{self.prefix}objects/{object_id}.json")
                except Exception:
                    pass
                return True
            return False

    def save_relationship(self, rel: Relationship) -> Relationship:
        """Save a Relationship to storage."""
        with self._lock:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            c = self._conn.cursor()
            c.execute(
                """INSERT OR REPLACE INTO relationships
                   (id, source_id, target_id, relation_type, metadata, confidence,
                    provenance, evidence, created_at, updated_at, deleted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (rel.id, rel.source, rel.target, rel.relation_type,
                 json.dumps(rel.metadata, default=str), rel.confidence,
                 json.dumps(rel.provenance, default=str),
                 json.dumps(rel.evidence, default=str),
                 rel.created_at, now, rel.deleted_at),
            )
            self._conn.commit()
            return rel

    def get_relationship(self, relation_id: str) -> Optional[Relationship]:
        """Retrieve a Relationship by ID."""
        with self._lock:
            c = self._conn.cursor()
            c.execute("SELECT * FROM relationships WHERE id = ? AND deleted_at IS NULL", (relation_id,))
            row = c.fetchone()
            return self._row_to_relationship(row) if row else None

    def list_relationships(self, source_id=None, target_id=None, relation_type=None, min_confidence=0.0, limit=1000) -> List[Relationship]:
        """List Relationships with optional filters."""
        with self._lock:
            query = "SELECT * FROM relationships WHERE deleted_at IS NULL AND confidence >= ?"
            params: list = [min_confidence]
            if source_id:
                query += " AND source_id = ?"
                params.append(source_id)
            if target_id:
                query += " AND target_id = ?"
                params.append(target_id)
            if relation_type:
                query += " AND relation_type = ?"
                params.append(relation_type)
            query += " LIMIT ?"
            params.append(limit)
            c = self._conn.cursor()
            c.execute(query, params)
            return [self._row_to_relationship(r) for r in c.fetchall()]

    def delete_relationship(self, relation_id: str, soft=True) -> bool:
        """Delete a Relationship by ID."""
        with self._lock:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            c = self._conn.cursor()
            if soft:
                c.execute("UPDATE relationships SET deleted_at = ? WHERE id = ?", (now, relation_id))
            else:
                c.execute("DELETE FROM relationships WHERE id = ?", (relation_id,))
            self._conn.commit()
            return c.rowcount > 0

    def save_schema(self, schema: Schema) -> Schema:
        """Save a Schema to storage."""
        with self._lock:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            c = self._conn.cursor()
            c.execute(
                """INSERT OR REPLACE INTO schemas
                   (id, name, version, description, target_object_type, fields,
                    strict_mode, parent_schema_id, created_at, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (schema.id, schema.name, schema.version, schema.description,
                 schema.target_object_type,
                 json.dumps({k: v.to_dict() for k, v in schema.fields.items()} if hasattr(schema, 'fields') and schema.fields else {}, default=str),
                 int(schema.strict) if hasattr(schema, 'strict') else 0,
                 getattr(schema, 'parent_schema_id', None),
                 now,
                 json.dumps(schema.metadata if hasattr(schema, 'metadata') else {}, default=str)),
            )
            self._conn.commit()
            return schema

    def get_schema(self, schema_id_or_name: str) -> Optional[Schema]:
        """Retrieve a Schema by ID or name."""
        with self._lock:
            c = self._conn.cursor()
            c.execute("SELECT * FROM schemas WHERE id = ? OR name = ?", (schema_id_or_name, schema_id_or_name))
            row = c.fetchone()
            if row:
                d = dict(row)
                fields_data = json.loads(d["fields"]) if d["fields"] else {}
                return Schema(
                    id=d["id"], name=d["name"], version=d["version"],
                    description=d["description"] or "",
                    target_object_type=d["target_object_type"] or "",
                    fields=fields_data,
                    strict=bool(d["strict_mode"]),
                    parent_schema_id=d["parent_schema_id"],
                    created_at=d["created_at"] or "",
                    metadata=json.loads(d["metadata"]) if d["metadata"] else {},
                )
            return None

    def list_schemas(self) -> List[Schema]:
        """Return all stored schemas."""
        with self._lock:
            c = self._conn.cursor()
            c.execute("SELECT * FROM schemas")
            schemas = []
            for row in c.fetchall():
                d = dict(row)
                fields_data = json.loads(d["fields"]) if d["fields"] else {}
                schemas.append(Schema(
                    id=d["id"], name=d["name"], version=d["version"],
                    description=d["description"] or "",
                    target_object_type=d["target_object_type"] or "",
                    fields=fields_data,
                    strict=bool(d["strict_mode"]),
                    parent_schema_id=d["parent_schema_id"],
                    created_at=d["created_at"] or "",
                    metadata=json.loads(d["metadata"]) if d["metadata"] else {},
                ))
            return schemas

    def record_provenance_event(self, event: ProvenanceEvent) -> ProvenanceEvent:
        """Record a provenance event."""
        with self._lock:
            c = self._conn.cursor()
            c.execute(
                """INSERT OR REPLACE INTO provenance_events
                   (id, target_object_id, event_type, description, inputs, outputs,
                    tools_used, parameters, execution_context, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (event.id, event.target_object_id, event.event_type,
                 event.description,
                 json.dumps(event.inputs, default=str),
                 json.dumps(event.outputs, default=str),
                 json.dumps(event.tools_used, default=str),
                 json.dumps(event.parameters, default=str),
                 json.dumps(event.execution_context, default=str),
                 event.created_at),
            )
            self._conn.commit()
            return event

    def get_provenance_events(self, target_object_id: str, limit=100) -> List[ProvenanceEvent]:
        """Return provenance events for an object."""
        with self._lock:
            c = self._conn.cursor()
            c.execute(
                "SELECT * FROM provenance_events WHERE target_object_id = ? ORDER BY created_at DESC LIMIT ?",
                (target_object_id, limit),
            )
            events = []
            for row in c.fetchall():
                d = dict(row)
                events.append(ProvenanceEvent(
                    id=d["id"], target_object_id=d["target_object_id"],
                    event_type=d["event_type"], description=d["description"] or "",
                    inputs=json.loads(d["inputs"]) if d["inputs"] else [],
                    outputs=json.loads(d["outputs"]) if d["outputs"] else [],
                    tools_used=json.loads(d["tools_used"]) if d["tools_used"] else [],
                    parameters=json.loads(d["parameters"]) if d["parameters"] else {},
                    execution_context=json.loads(d["execution_context"]) if d["execution_context"] else {},
                    created_at=d["created_at"] or "",
                ))
            return events

    def get_version_history(self, object_id: str) -> List[Dict[str, Any]]:
        """Return version history for an object."""
        with self._lock:
            c = self._conn.cursor()
            c.execute(
                "SELECT * FROM object_versions WHERE object_id = ? ORDER BY version ASC",
                (object_id,),
            )
            return [
                {"version": row["version"], "snapshot": json.loads(row["snapshot"]), "created_at": row["created_at"]}
                for row in c.fetchall()
            ]


class S3Storage(CloudStorageBackend):
    """AWS S3 storage backend."""

    def __init__(self, bucket_name: str, prefix: str = "dataos/", index_db: str = ":memory:",
                 aws_access_key: str = "", aws_secret_key: str = "", region: str = "us-east-1", **kwargs):
        self._aws_access_key = aws_access_key
        self._aws_secret_key = aws_secret_key
        self._region = region
        super().__init__(bucket_name, prefix, index_db, kwargs)

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client(
                    "s3",
                    aws_access_key_id=self._aws_access_key,
                    aws_secret_access_key=self._aws_secret_key,
                    region_name=self._region,
                )
            except ImportError:
                raise ImportError("boto3 is required for S3 storage: pip install boto3")
        return self._client

    def _upload_blob(self, key: str, data: bytes, content_type: str = "application/json") -> Dict[str, Any]:
        client = self._get_client()
        client.put_object(Bucket=self.bucket_name, Key=key, Body=data, ContentType=content_type)
        return {"key": key, "size": len(data), "bucket": self.bucket_name}

    def _download_blob(self, key: str) -> Optional[bytes]:
        client = self._get_client()
        try:
            resp = client.get_object(Bucket=self.bucket_name, Key=key)
            return resp["Body"].read()
        except Exception:
            return None

    def _delete_blob(self, key: str) -> bool:
        client = self._get_client()
        try:
            client.delete_object(Bucket=self.bucket_name, Key=key)
            return True
        except Exception:
            return False

    def _list_blobs(self, prefix: str = "") -> List[str]:
        client = self._get_client()
        resp = client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)
        return [obj["Key"] for obj in resp.get("Contents", [])]


class GCSStorage(CloudStorageBackend):
    """Google Cloud Storage backend."""

    def __init__(self, bucket_name: str, prefix: str = "dataos/", index_db: str = ":memory:",
                 project: str = "", credentials_path: str = "", **kwargs):
        self._project = project
        self._credentials_path = credentials_path
        super().__init__(bucket_name, prefix, index_db, kwargs)

    def _get_client(self):
        if self._client is None:
            try:
                from google.cloud import storage as gcs
                if self._credentials_path:
                    self._client = gcs.Client.from_service_account_json(self._credentials_path)
                else:
                    self._client = gcs.Client(project=self._project)
            except ImportError:
                raise ImportError("google-cloud-storage is required: pip install google-cloud-storage")
        return self._client

    def _upload_blob(self, key: str, data: bytes, content_type: str = "application/json") -> Dict[str, Any]:
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)
        blob = bucket.blob(key)
        blob.upload_from_string(data, content_type=content_type)
        return {"key": key, "size": len(data), "bucket": self.bucket_name}

    def _download_blob(self, key: str) -> Optional[bytes]:
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)
        blob = bucket.blob(key)
        if blob.exists():
            return blob.download_as_bytes()
        return None

    def _delete_blob(self, key: str) -> bool:
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)
        blob = bucket.blob(key)
        if blob.exists():
            blob.delete()
            return True
        return False

    def _list_blobs(self, prefix: str = "") -> List[str]:
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)
        return [blob.name for blob in bucket.list_blobs(prefix=prefix)]


class AzureBlobStorage(CloudStorageBackend):
    """Azure Blob Storage backend."""

    def __init__(self, bucket_name: str, prefix: str = "dataos/", index_db: str = ":memory:",
                 connection_string: str = "", account_name: str = "", account_key: str = "", **kwargs):
        self._connection_string = connection_string
        self._account_name = account_name
        self._account_key = account_key
        super().__init__(bucket_name, prefix, index_db, kwargs)

    def _get_client(self):
        if self._client is None:
            try:
                from azure.storage.blob import BlobServiceClient
                if self._connection_string:
                    self._client = BlobServiceClient.from_connection_string(self._connection_string)
                else:
                    from azure.storage.blob import AccountSPermissions, generate_account_sas
                    sas_token = generate_account_sas(
                        account_name=self._account_name,
                        account_key=self._account_key,
                        permission=AccountSPermissions.READ | AccountSPermissions.WRITE | AccountSPermissions.DELETE,
                        expires_on=datetime.datetime.utcnow() + datetime.timedelta(hours=1),
                    )
                    self._client = BlobServiceClient(
                        account_url=f"https://{self._account_name}.blob.core.windows.net",
                        credential=sas_token,
                    )
            except ImportError:
                raise ImportError("azure-storage-blob is required: pip install azure-storage-blob")
        return self._client

    def _upload_blob(self, key: str, data: bytes, content_type: str = "application/json") -> Dict[str, Any]:
        client = self._get_client()
        blob_client = client.get_blob_client(container=self.bucket_name, blob=key)
        blob_client.upload_blob(data, overwrite=True, content_type=content_type)
        return {"key": key, "size": len(data), "bucket": self.bucket_name}

    def _download_blob(self, key: str) -> Optional[bytes]:
        client = self._get_client()
        blob_client = client.get_blob_client(container=self.bucket_name, blob=key)
        try:
            return blob_client.download_blob().readall()
        except Exception:
            return None

    def _delete_blob(self, key: str) -> bool:
        client = self._get_client()
        blob_client = client.get_blob_client(container=self.bucket_name, blob=key)
        try:
            blob_client.delete_blob()
            return True
        except Exception:
            return False

    def _list_blobs(self, prefix: str = "") -> List[str]:
        client = self._get_client()
        container_client = client.get_container_client(self.bucket_name)
        return [b.name for b in container_client.list_blobs(name_starts_with=prefix)]
