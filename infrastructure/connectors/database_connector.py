"""
Database Connector for DataOS (Rule #36).
Standardized interface for reading from and writing to SQL databases.
Supports SQLite, PostgreSQL, and MySQL via standard DB-API 2.0.
"""

from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, ObjectType
from ..connectors.base import BaseConnector


class DatabaseConnector(BaseConnector):
    """
    Connects to SQL databases, lists tables, reads/writes data as DataObjects.
    Config:
        engine: "sqlite" | "postgresql" | "mysql"
        connection_string: str (e.g. "sqlite:///path.db" or "postgresql://user:pass@host/db")
        read_only: bool (default True)
        schema_filter: list[str] (optional, limit to specific schemas)
    """

    SUPPORTED_ENGINES = ("sqlite", "postgresql", "mysql")

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.engine = config.get("engine", "sqlite")
        self.connection_string = config.get("connection_string", "")
        self.read_only = config.get("read_only", True)
        self.schema_filter = config.get("schema_filter", [])
        self._connection = None

        if self.engine not in self.SUPPORTED_ENGINES:
            raise ValueError(f"Unsupported engine '{self.engine}'. Must be one of {self.SUPPORTED_ENGINES}")

    def _get_connection(self):
        """Establish database connection based on engine type."""
        if self._connection:
            return self._connection

        if self.engine == "sqlite":
            import sqlite3
            db_path = self.connection_string.replace("sqlite:///", "").replace("sqlite://", "")
            self._connection = sqlite3.connect(db_path)
            self._connection.row_factory = sqlite3.Row
        elif self.engine == "postgresql":
            try:
                import psycopg2
                self._connection = psycopg2.connect(self.connection_string)
            except ImportError:
                raise ImportError("psycopg2 is required for PostgreSQL connectors. Install with: pip install psycopg2-binary")
        elif self.engine == "mysql":
            try:
                import pymysql
                self._connection = pymysql.connect(**self._parse_mysql_url(self.connection_string))
            except ImportError:
                raise ImportError("pymysql is required for MySQL connectors. Install with: pip install pymysql")

        return self._connection

    def _parse_mysql_url(self, url: str) -> Dict[str, Any]:
        """Parse mysql://user:pass@host:port/db into connection kwargs."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username or "",
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/") or "",
        }

    def test_connection(self) -> bool:
        """Verify database is reachable."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            return True
        except Exception as e:
            print(f"[DatabaseConnector:{self.name}] Connection failed: {e}")
            return False

    def list_resources(self) -> List[Dict[str, Any]]:
        """List all tables (resources) in the connected database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        tables = []

        if self.engine == "sqlite":
            cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')")
            for row in cursor.fetchall():
                tables.append({"id": row[0], "type": row[1], "name": row[0]})
        elif self.engine == "postgresql":
            schema_clause = ""
            if self.schema_filter:
                schemas = ", ".join(f"'{s}'" for s in self.schema_filter)
                schema_clause = f"AND table_schema IN ({schemas})"
            cursor.execute(f"""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema') {schema_clause}
                ORDER BY table_schema, table_name
            """)
            for row in cursor.fetchall():
                tables.append({
                    "id": f"{row[0]}.{row[1]}",
                    "type": row[2].lower(),
                    "name": row[1],
                    "schema": row[0],
                })
        elif self.engine == "mysql":
            cursor.execute("SHOW TABLES")
            for row in cursor.fetchall():
                tables.append({"id": row[0], "type": "table", "name": row[0]})

        return tables

    def read_resource(self, resource_id: str, limit: int = 1000) -> Dict[str, Any]:
        """
        Read a table's data as a structured dict with columns and rows.
        resource_id is the table name (or schema.table for PostgreSQL).
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        safe_id = resource_id.replace(";", "")
        cursor.execute(f"SELECT * FROM {safe_id} LIMIT {limit}")
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return {
            "resource_id": resource_id,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }

    def read_resource_as_object(self, resource_id: str, limit: int = 1000) -> DataObject:
        """Read a table and wrap it as a DataObject."""
        data = self.read_resource(resource_id, limit=limit)
        return DataObject(
            type=ObjectType.DATASET.value,
            schema="dataset.v1",
            properties={
                "source_connector": self.name,
                "source_engine": self.engine,
                "table_name": resource_id,
                "columns": data["columns"],
                "row_count": data["row_count"],
            },
            content=data["rows"],
            source=f"connector://{self.name}/{resource_id}",
        )

    def execute_query(self, query: str) -> Dict[str, Any]:
        """Execute an arbitrary read query (read_only=True enforced)."""
        if self.read_only and any(kw in query.upper() for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE")):
            raise PermissionError("Connector is in read-only mode. Write operations are blocked.")

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}

    def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
