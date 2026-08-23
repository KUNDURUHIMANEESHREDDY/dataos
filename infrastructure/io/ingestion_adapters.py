"""
Ingestion Adapters for DataOS (Rule #33).
Provides source-specific adapters for Archive, Database, API, and Git ingestion.
Each adapter follows a common interface: ingest() -> Dict[str, Any].
"""

from __future__ import annotations
import io
import json
import os
import datetime
import hashlib
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
from abc import ABC, abstractmethod


class IngestionSource(str, Enum):
    """Supported ingestion source types."""
    ARCHIVE = "archive"
    DATABASE = "database"
    API = "api"
    GIT = "git"
    FILE = "file"


class IngestionAdapter(ABC):
    """Base class for ingestion adapters."""

    @abstractmethod
    def ingest(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest data from source and return structured result."""
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate source configuration, return list of errors (empty = valid)."""
        pass


class ArchiveIngestionAdapter(IngestionAdapter):
    """Ingests data from archive files (ZIP, TAR, TAR.GZ)."""

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate archive source configuration."""
        errors = []
        if "archive_path" not in config and "archive_bytes" not in config:
            errors.append("Either 'archive_path' or 'archive_bytes' is required")
        return errors

    def ingest(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest archive data and return structured result."""
        archive_bytes = source_config.get("archive_bytes")
        archive_path = source_config.get("archive_path")
        extract_filter = source_config.get("filter")  # Optional glob filter

        if archive_bytes is None and archive_path:
            with open(archive_path, "rb") as f:
                archive_bytes = f.read()

        if archive_bytes is None:
            return {"error": "No archive data provided"}

        ext = (archive_path or "data.zip").lower()
        if ext.endswith(".zip") or archive_path is None:
            return self._ingest_zip(archive_bytes, source_config)
        elif ext.endswith(".tar.gz") or ext.endswith(".tgz"):
            return self._ingest_tar_gz(archive_bytes, source_config)
        elif ext.endswith(".tar"):
            return self._ingest_tar(archive_bytes, source_config)
        return {"error": f"Unsupported archive format: {ext}"}

    def _ingest_zip(self, data: bytes, config: Dict[str, Any]) -> Dict[str, Any]:
        import zipfile
        files = []
        filter_pattern = config.get("filter")
        try:
            with zipfile.ZipFile(io.BytesIO(data), "r") as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    if filter_pattern and not self._matches_filter(info.filename, filter_pattern):
                        continue
                    content = z.read(info.filename)
                    files.append({
                        "filename": info.filename,
                        "size": info.file_size,
                        "compressed_size": info.compress_size,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "content_preview": content[:500].decode("utf-8", errors="replace"),
                    })
        except zipfile.BadZipFile:
            return {"error": "Invalid ZIP file"}

        return {
            "format": "zip",
            "total_files": len(files),
            "files": files,
            "total_size": sum(f["size"] for f in files),
        }

    def _ingest_tar(self, data: bytes, config: Dict[str, Any]) -> Dict[str, Any]:
        import tarfile
        files = []
        filter_pattern = config.get("filter")
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    if filter_pattern and not self._matches_filter(member.name, filter_pattern):
                        continue
                    f = tar.extractfile(member)
                    content = f.read() if f else b""
                    files.append({
                        "filename": member.name,
                        "size": member.size,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "content_preview": content[:500].decode("utf-8", errors="replace"),
                    })
        except tarfile.TarError:
            return {"error": "Invalid TAR file"}

        return {
            "format": "tar",
            "total_files": len(files),
            "files": files,
            "total_size": sum(f["size"] for f in files),
        }

    def _ingest_tar_gz(self, data: bytes, config: Dict[str, Any]) -> Dict[str, Any]:
        import tarfile
        files = []
        filter_pattern = config.get("filter")
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    if filter_pattern and not self._matches_filter(member.name, filter_pattern):
                        continue
                    f = tar.extractfile(member)
                    content = f.read() if f else b""
                    files.append({
                        "filename": member.name,
                        "size": member.size,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "content_preview": content[:500].decode("utf-8", errors="replace"),
                    })
        except tarfile.TarError:
            return {"error": "Invalid TAR.GZ file"}

        return {
            "format": "tar.gz",
            "total_files": len(files),
            "files": files,
            "total_size": sum(f["size"] for f in files),
        }

    def _matches_filter(self, filename: str, pattern: str) -> bool:
        import fnmatch
        return fnmatch.fnmatch(filename.lower(), pattern.lower())


class DatabaseIngestionAdapter(IngestionAdapter):
    """Ingests data from database sources via query execution."""

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate database source configuration."""
        errors = []
        if "connection_string" not in config and "db_type" not in config:
            errors.append("Either 'connection_string' or 'db_type' is required")
        if "query" not in config:
            errors.append("'query' is required")
        return errors

    def ingest(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest data from database source."""
        db_type = source_config.get("db_type", "sqlite")
        connection_string = source_config.get("connection_string", "")
        query = source_config.get("query", "")
        params = source_config.get("params", {})
        limit = source_config.get("limit", 1000)

        if db_type == "sqlite":
            return self._ingest_sqlite(connection_string, query, params, limit)
        elif db_type == "postgresql":
            return self._ingest_postgresql(connection_string, query, params, limit)
        elif db_type == "mysql":
            return self._ingest_mysql(connection_string, query, params, limit)
        else:
            return {"error": f"Unsupported database type: {db_type}"}

    def _ingest_sqlite(self, conn_str: str, query: str, params: Dict, limit: int) -> Dict[str, Any]:
        import sqlite3
        conn = None
        try:
            conn = sqlite3.connect(conn_str or ":memory:")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            data = [dict(row) for row in rows[:limit]]
            return {
                "db_type": "sqlite",
                "columns": columns,
                "row_count": len(data),
                "data": data,
                "truncated": len(rows) > limit,
            }
        except Exception as e:
            return {"error": str(e), "db_type": "sqlite"}
        finally:
            if conn:
                conn.close()

    def _ingest_postgresql(self, conn_str: str, query: str, params: Dict, limit: int) -> Dict[str, Any]:
        conn = None
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(conn_str)
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            data = [dict(row) for row in rows[:limit]]
            return {
                "db_type": "postgresql",
                "columns": columns,
                "row_count": len(data),
                "data": data,
                "truncated": len(rows) > limit,
            }
        except ImportError:
            return {"error": "psycopg2 is required for PostgreSQL: pip install psycopg2-binary"}
        except Exception as e:
            return {"error": str(e), "db_type": "postgresql"}
        finally:
            if conn:
                conn.close()

    def _ingest_mysql(self, conn_str: str, query: str, params: Dict, limit: int) -> Dict[str, Any]:
        conn = None
        try:
            import pymysql
            conn = pymysql.connect(conn_str)
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            data = [dict(row) for row in rows[:limit]]
            return {
                "db_type": "mysql",
                "columns": columns,
                "row_count": len(data),
                "data": data,
                "truncated": len(rows) > limit,
            }
        except ImportError:
            return {"error": "pymysql is required for MySQL: pip install pymysql"}
        except Exception as e:
            return {"error": str(e), "db_type": "mysql"}
        finally:
            if conn:
                conn.close()


class APIIngestionAdapter(IngestionAdapter):
    """Ingests data from REST/GraphQL APIs."""

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate API source configuration."""
        errors = []
        if "url" not in config:
            errors.append("'url' is required")
        return errors

    def ingest(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest data from API source."""
        url = source_config.get("url", "")
        method = source_config.get("method", "GET").upper()
        headers = source_config.get("headers", {})
        body = source_config.get("body")
        auth_token = source_config.get("auth_token")
        timeout = source_config.get("timeout", 30)
        response_type = source_config.get("response_type", "json")

        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        try:
            req = urllib.request.Request(url, headers=headers)
            if method == "POST" and body:
                req.data = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body.encode("utf-8")
                req.add_header("Content-Type", "application/json")
            elif method != "GET":
                req.method = method

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                status_code = resp.status
                resp_headers = dict(resp.headers)

            if response_type == "json":
                data = json.loads(raw)
                return {
                    "status_code": status_code,
                    "response_type": "json",
                    "data": data,
                    "content_length": len(raw),
                    "headers": resp_headers,
                }
            else:
                return {
                    "status_code": status_code,
                    "response_type": "text",
                    "data": raw.decode("utf-8", errors="replace"),
                    "content_length": len(raw),
                    "headers": resp_headers,
                }
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.reason}", "status_code": e.code}
        except urllib.error.URLError as e:
            return {"error": str(e.reason)}
        except Exception as e:
            return {"error": str(e)}

    def ingest_graphql(self, url: str, query: str, variables: Optional[Dict] = None,
                       headers: Optional[Dict] = None, auth_token: Optional[str] = "") -> Dict[str, Any]:
        """Ingest data from GraphQL endpoint."""
        config = {
            "url": url,
            "method": "POST",
            "body": {"query": query, "variables": variables or {}},
            "headers": headers or {},
            "auth_token": auth_token,
        }
        return self.ingest(config)


class GitIngestionAdapter(IngestionAdapter):
    """Ingests data from Git repositories."""

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate Git source configuration."""
        errors = []
        if "repo_url" not in config and "local_path" not in config:
            errors.append("Either 'repo_url' or 'local_path' is required")
        return errors

    def ingest(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest data from Git repository."""
        local_path = source_config.get("local_path")
        repo_url = source_config.get("repo_url")
        branch = source_config.get("branch", "main")
        file_filter = source_config.get("filter")
        include_history = source_config.get("include_history", False)
        max_files = source_config.get("max_files", 500)

        if local_path:
            return self._ingest_local(local_path, file_filter, max_files)
        elif repo_url:
            return self._ingest_remote(repo_url, branch, file_filter, max_files, include_history)
        return {"error": "No source specified"}

    def _ingest_local(self, path: str, file_filter: Optional[str], max_files: int) -> Dict[str, Any]:
        import subprocess
        import fnmatch
        files = []
        try:
            if not os.path.isdir(path):
                return {"error": f"Path does not exist or is not a directory: {path}"}
            result = subprocess.run(
                ["git", "ls-files"], cwd=path, capture_output=True, text=True, timeout=30
            )
            all_files = result.stdout.strip().split("\n") if result.stdout.strip() else []
            import fnmatch
            if file_filter:
                all_files = [f for f in all_files if fnmatch.fnmatch(f.lower(), file_filter.lower())]

            for fname in all_files[:max_files]:
                fpath = os.path.join(path, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "rb") as f:
                            content = f.read()
                        files.append({
                            "filename": fname,
                            "size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                        })
                    except (PermissionError, UnicodeDecodeError):
                        files.append({"filename": fname, "size": -1, "error": "unreadable"})

            # Get latest commit info
            log_result = subprocess.run(
                ["git", "log", "-1", "--format=%H|%s|%an|%ai"],
                cwd=path, capture_output=True, text=True, timeout=10
            )
            latest_commit = {}
            if log_result.stdout.strip():
                parts = log_result.stdout.strip().split("|", 3)
                if len(parts) >= 4:
                    latest_commit = {"hash": parts[0], "message": parts[1], "author": parts[2], "date": parts[3]}

            return {
                "source": "local_git",
                "path": path,
                "total_files": len(files),
                "files": files,
                "latest_commit": latest_commit,
            }
        except FileNotFoundError:
            return {"error": "Git is not installed or not in PATH"}
        except subprocess.TimeoutExpired:
            return {"error": "Git operation timed out"}

    def _ingest_remote(self, repo_url: str, branch: str, file_filter: Optional[str],
                       max_files: int, include_history: bool) -> Dict[str, Any]:
        import subprocess
        import tempfile
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", "--branch", branch, repo_url, "."],
                    cwd=tmpdir, capture_output=True, text=True, timeout=120
                )
                if result.returncode != 0:
                    return {"error": f"Clone failed: {result.stderr}"}

                local_result = self._ingest_local(tmpdir, file_filter, max_files)
                local_result["source"] = "remote_git"
                local_result["repo_url"] = repo_url
                local_result["branch"] = branch
                return local_result
        except subprocess.TimeoutExpired:
            return {"error": "Git clone timed out"}
        except Exception as e:
            return {"error": str(e)}


class IngestionAdapterManager:
    """Registry of ingestion adapters."""

    def __init__(self):
        self._adapters: Dict[str, IngestionAdapter] = {
            "archive": ArchiveIngestionAdapter(),
            "database": DatabaseIngestionAdapter(),
            "api": APIIngestionAdapter(),
            "git": GitIngestionAdapter(),
        }

    def register(self, source_type: str, adapter: IngestionAdapter) -> None:
        """Register an ingestion adapter for a source type."""
        self._adapters[source_type] = adapter

    def get(self, source_type: str) -> Optional[IngestionAdapter]:
        """Get adapter for a source type."""
        return self._adapters.get(source_type)

    def ingest(self, source_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest data using adapter for source type."""
        adapter = self._adapters.get(source_type)
        if not adapter:
            return {"error": f"No adapter for source type '{source_type}'"}
        errors = adapter.validate_config(config)
        if errors:
            return {"error": "Validation failed", "details": errors}
        return adapter.ingest(config)

    def list_sources(self) -> List[str]:
        """Return list of registered source types."""
        return list(self._adapters.keys())
