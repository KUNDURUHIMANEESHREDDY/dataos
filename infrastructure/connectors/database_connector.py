"""
Database Connector for DataOS (Rule #36).
Standardized interface for reading from and writing to SQL databases.
Supports SQLite, PostgreSQL, and MySQL via standard DB-API 2.0.
"""

from __future__ import annotations
import json
import sqlite3
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
    MAX_READ_ROWS = 10000

    @staticmethod
    def _quote_identifier(identifier: str, quote: str) -> str:
        """Quote a catalog-derived SQL identifier for the selected DB dialect."""
        if not isinstance(identifier, str) or not identifier or "\x00" in identifier:
            raise ValueError("Database resource identifier is invalid.")
        return quote + identifier.replace(quote, quote + quote) + quote

    @staticmethod
    def _sqlite_read_only_authorizer(action, arg1, arg2, database_name, trigger_name):
        """Allow read-only SQLite operations and deny every unlisted action."""
        allowed_actions = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_RECURSIVE,
        }
        if action == sqlite3.SQLITE_FUNCTION:
            function_name = (arg2 or arg1 or "").lower()
            if function_name in {"load_extension", "readfile", "writefile"}:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in allowed_actions else sqlite3.SQLITE_DENY

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
            db_path = self.connection_string.replace("sqlite:///", "").replace("sqlite://", "")
            self._connection = sqlite3.connect(db_path)
            self._connection.row_factory = sqlite3.Row
            if self.read_only:
                self._connection.set_authorizer(self._sqlite_read_only_authorizer)
        elif self.engine == "postgresql":
            try:
                import psycopg2
                self._connection = psycopg2.connect(self.connection_string)
                if self.read_only:
                    self._connection.set_session(readonly=True)
            except ImportError:
                raise ImportError("psycopg2 is required for PostgreSQL connectors. Install with: pip install psycopg2-binary")
        elif self.engine == "mysql":
            try:
                import pymysql
                self._connection = pymysql.connect(**self._parse_mysql_url(self.connection_string))
                if self.read_only:
                    cursor = self._connection.cursor()
                    try:
                        cursor.execute("SET SESSION TRANSACTION READ ONLY")
                    finally:
                        cursor.close()
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
            schema_params = ()
            if self.schema_filter:
                if not isinstance(self.schema_filter, (list, tuple)) or any(
                    not isinstance(schema, str) or not schema or "\x00" in schema
                    for schema in self.schema_filter
                ):
                    raise ValueError("schema_filter must contain non-empty schema names.")
                placeholders = ", ".join("%s" for _ in self.schema_filter)
                schema_clause = f"AND table_schema IN ({placeholders})"
                schema_params = tuple(self.schema_filter)
            cursor.execute(f"""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema') {schema_clause}
                ORDER BY table_schema, table_name
            """, schema_params)
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
        Read a catalog-listed table as a structured dict.
        User input is matched against catalog metadata; it is never inserted
        directly into an SQL identifier.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.MAX_READ_ROWS:
            raise ValueError(f"limit must be between 1 and {self.MAX_READ_ROWS}.")

        if not isinstance(resource_id, str) or not resource_id:
            raise FileNotFoundError("Database resource not found.")

        resource = next(
            (item for item in self.list_resources() if item.get("id") == resource_id),
            None,
        )
        if resource is None:
            raise FileNotFoundError("Database resource not found.")

        if self.engine == "postgresql":
            table_sql = (
                self._quote_identifier(resource["schema"], '"')
                + "."
                + self._quote_identifier(resource["name"], '"')
            )
            limit_placeholder = "%s"
        elif self.engine == "mysql":
            table_sql = self._quote_identifier(resource["name"], "`")
            limit_placeholder = "%s"
        else:
            table_sql = self._quote_identifier(resource["name"], '"')
            limit_placeholder = "?"

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table_sql} LIMIT {limit_placeholder}", (limit,))
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
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty SQL string.")
        if self.read_only and any(kw in query.upper() for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE")):
            raise PermissionError("Connector is in read-only mode. Write operations are blocked.")

        # Read-only mode is enforced by the database connection itself:
        # SQLite's authorizer, PostgreSQL read-only transactions, and MySQL's
        # session transaction mode. The keyword check above is only an early,
        # user-friendly rejection and is not the security boundary.
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
