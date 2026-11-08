"""
SQL Computation Engine for DataOS (Rule #14, Rule #15).
Executes read-only SQL queries against registered DataOS datasets via in-memory SQLite.
Captures query text, inputs, execution plan, timing, outputs, and full provenance.
NEVER fabricates query results.
"""

from __future__ import annotations

import datetime
import io
import os
import sqlite3
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from core.object.model import DataObject, ObjectType
from core.provenance.model import ProvenanceRecord
from infrastructure.storage.base import StorageBackend


_DENIED_SQLITE_ACTIONS = frozenset(
    getattr(sqlite3, name)
    for name in (
        "SQLITE_INSERT",
        "SQLITE_UPDATE",
        "SQLITE_DELETE",
        "SQLITE_CREATE_INDEX",
        "SQLITE_CREATE_TABLE",
        "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE",
        "SQLITE_CREATE_TEMP_TRIGGER",
        "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER",
        "SQLITE_CREATE_VIEW",
        "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE",
        "SQLITE_DROP_TEMP_INDEX",
        "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER",
        "SQLITE_DROP_TEMP_VIEW",
        "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW",
        "SQLITE_ALTER_TABLE",
        "SQLITE_REINDEX",
        "SQLITE_ANALYZE",
        "SQLITE_ATTACH",
        "SQLITE_DETACH",
        "SQLITE_CREATE_VTABLE",
        "SQLITE_DROP_VTABLE",
        "SQLITE_TRANSACTION",
        "SQLITE_SAVEPOINT",
    )
    if hasattr(sqlite3, name)
)

# Both runtimes consume one reviewed manifest so their SQLite capability
# surfaces cannot silently drift apart.
def _load_allowed_sqlite_functions() -> frozenset[str]:
    manifest = Path(__file__).resolve().parents[2] / "security" / "sqlite_allowed_functions.txt"
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Unable to load SQLite function policy: {manifest}") from exc
    return frozenset(
        line.strip().casefold()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    )


_ALLOWED_SQLITE_FUNCTIONS = _load_allowed_sqlite_functions()



class SQLExecutionEngine:
    """Execute bounded, read-only SQL against registered DataOS objects."""

    MAX_QUERY_BYTES = 64 * 1024
    MAX_QUERY_SECONDS = 5.0
    MAX_RESULT_ROWS = 10_000

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    @staticmethod
    def _read_only_authorizer(
        action: int,
        arg1: Optional[str],
        arg2: Optional[str],
        database_name: Optional[str],
        trigger_name: Optional[str],
    ) -> int:
        """Deny database mutation, attachment, transaction control and PRAGMA."""
        if action in _DENIED_SQLITE_ACTIONS or action == sqlite3.SQLITE_PRAGMA:
            return sqlite3.SQLITE_DENY

        if action == sqlite3.SQLITE_FUNCTION:
            function_name = (arg2 or arg1 or "").casefold()
            if function_name not in _ALLOWED_SQLITE_FUNCTIONS:
                return sqlite3.SQLITE_DENY

        return sqlite3.SQLITE_OK

    def execute_sql(
        self,
        sql_query: str,
        table_objects: Optional[List[DataObject]] = None,
        agent_or_user: str = "system",
    ) -> Dict[str, Any]:
        """
        Execute one bounded, read-only SQL query against tabular DataObjects.

        Dataset registration happens before the SQLite authorizer and query-only
        mode are enabled. User SQL cannot mutate the in-memory schema, attach
        databases, change PRAGMAs, or write rows. Query execution is time- and
        result-bounded so recursive or high-cardinality queries cannot consume
        unbounded worker memory or CPU.
        """
        start_time = time.time()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = sqlite3.connect(":memory:")
        registered_tables: List[str] = []
        source_object_ids: List[str] = []
        ambiguous_table_names: List[str] = []

        try:
            if not isinstance(sql_query, str) or not sql_query.strip():
                raise ValueError("SQL query must be a non-empty string")
            if len(sql_query.encode("utf-8")) > self.MAX_QUERY_BYTES:
                raise ValueError(
                    f"SQL query exceeds the {self.MAX_QUERY_BYTES}-byte limit"
                )

            if table_objects is None:
                table_objects = self.storage.list_objects(
                    object_type=ObjectType.DATASET.value,
                    limit=100,
                )

            prepared_datasets = []
            alias_owners: Dict[str, set[str]] = {}
            for obj in table_objects:
                filename_raw = obj.properties.get("filename", "")
                base_name, _ = (
                    os.path.splitext(filename_raw)
                    if "." in filename_raw
                    else (filename_raw, "")
                )

                table_names = set()
                if obj.properties.get("table_name"):
                    table_names.add(obj.properties["table_name"])
                if filename_raw:
                    table_names.add(
                        "".join(
                            c if c.isalnum() or c == "_"
                            else "_"
                            for c in filename_raw
                        )
                    )
                if base_name:
                    table_names.add(
                        "".join(
                            c if c.isalnum() or c == "_"
                            else "_"
                            for c in base_name
                        )
                    )
                table_names.add(f"tbl_{obj.id[:8]}")

                df = None
                if isinstance(obj.content, list) and all(
                    isinstance(row, dict) for row in obj.content
                ):
                    df = pd.DataFrame(obj.content)
                elif isinstance(obj.properties.get("raw_csv"), str):
                    df = pd.read_csv(io.StringIO(obj.properties["raw_csv"]))
                elif isinstance(obj.properties.get("sample_rows"), list):
                    df = pd.DataFrame(obj.properties["sample_rows"])

                if df is None or df.empty:
                    continue

                # SQLite identifiers are case-insensitive. Normalize aliases before
                # registration so two datasets cannot silently shadow one another.
                normalized_names: Dict[str, str] = {}
                for table_name in sorted(table_names):
                    normalized_names.setdefault(table_name.casefold(), table_name)
                prepared_datasets.append((obj, df, normalized_names))
                for normalized_name in normalized_names:
                    alias_owners.setdefault(normalized_name, set()).add(str(obj.id))

            ambiguous_table_names = sorted(
                {
                    table_name
                    for _, _, names in prepared_datasets
                    for normalized_name, table_name in names.items()
                    if len(alias_owners[normalized_name]) > 1
                },
                key=str.casefold,
            )

            for obj, df, names in prepared_datasets:
                registered_for_object = False
                for normalized_name, table_name in names.items():
                    if len(alias_owners[normalized_name]) > 1:
                        # Ambiguous aliases are omitted for every owner. Each
                        # dataset retains its deterministic tbl_<id-prefix> alias.
                        continue
                    df.to_sql(table_name, conn, if_exists="fail", index=False)
                    registered_tables.append(table_name)
                    registered_for_object = True
                if registered_for_object:
                    source_object_ids.append(obj.id)

            # Lock the registered in-memory schema before executing caller SQL.
            conn.execute("PRAGMA query_only = ON")
            conn.set_authorizer(self._read_only_authorizer)

            deadline = time.monotonic() + self.MAX_QUERY_SECONDS
            conn.set_progress_handler(
                lambda: int(time.monotonic() >= deadline),
                1_000,
            )

            cursor = conn.execute(sql_query)
            if cursor.description is None:
                raise ValueError("Only read-only SQL queries that return rows are supported")

            rows = cursor.fetchmany(self.MAX_RESULT_ROWS + 1)
            if len(rows) > self.MAX_RESULT_ROWS:
                raise ValueError(
                    f"SQL query result exceeds the {self.MAX_RESULT_ROWS}-row limit"
                )

            columns = [column[0] for column in cursor.description]
            query_df = pd.DataFrame.from_records(rows, columns=columns)
            execution_time_ms = round((time.time() - start_time) * 1000.0, 2)

            clean_df = query_df.where(pd.notnull(query_df), None)
            records = clean_df.to_dict(orient="records")

            provenance = {
                "engine": "sqlite_in_memory",
                "query_text": sql_query,
                "input_sources": source_object_ids,
                "registered_tables": registered_tables,
                "ambiguous_table_names": ambiguous_table_names,
                "execution_time_ms": execution_time_ms,
                "row_count": len(records),
                "executed_by": agent_or_user,
                "executed_at": now,
            }

            return {
                "success": True,
                "query": sql_query,
                "columns": columns,
                "row_count": len(records),
                "rows": records,
                "execution_time_ms": execution_time_ms,
                "registered_tables": registered_tables,
                "ambiguous_table_names": ambiguous_table_names,
                "provenance": provenance,
                "error": None,
            }

        except Exception as exc:
            execution_time_ms = round((time.time() - start_time) * 1000.0, 2)
            return {
                "success": False,
                "query": sql_query,
                "columns": [],
                "row_count": 0,
                "rows": [],
                "execution_time_ms": execution_time_ms,
                "registered_tables": registered_tables,
                "ambiguous_table_names": ambiguous_table_names,
                "provenance": {
                    "engine": "sqlite_in_memory",
                    "query_text": sql_query,
                    "error": str(exc),
                    "executed_at": now,
                },
                "error": str(exc),
            }
        finally:
            conn.close()
