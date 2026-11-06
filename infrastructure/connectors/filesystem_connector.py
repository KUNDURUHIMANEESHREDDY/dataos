"""
Filesystem Connector for DataOS (Rule #36).
Standardized interface for reading files from local or mounted filesystems.
Supports recursive directory scanning, glob patterns, and file metadata extraction.
"""

from __future__ import annotations
import os
import json
import hashlib
from typing import Dict, Any, List, Optional
from pathlib import Path
from core.object.model import DataObject, ObjectType
from ..connectors.base import BaseConnector


class FilesystemConnector(BaseConnector):
    """
    Connects to local or mounted filesystems, lists files, reads file content.
    Config:
        root_path: str (base directory to scan)
        glob_pattern: str (e.g. "**/*.csv", default "**/*")
        max_depth: int (maximum recursion depth, default 10)
        include_hidden: bool (include hidden files, default False)
        file_types: list[str] (optional, filter by extension e.g. [".csv", ".json"])
        encoding: str (default "utf-8")
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.root_path = Path(config.get("root_path", ".")).expanduser().resolve()
        self.glob_pattern = config.get("glob_pattern", "**/*")
        self.max_depth = config.get("max_depth", 10)
        self.include_hidden = config.get("include_hidden", False)
        self.file_types = config.get("file_types", [])
        self.encoding = config.get("encoding", "utf-8")

    def _resolve_path(self, resource_id: str, expected_type: str) -> Path:
        """Resolve a relative resource beneath the configured root, rejecting escapes and symlinks."""
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError("Resource path must be a non-empty relative path.")
        relative = Path(resource_id)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise ValueError("Resource path must stay within the configured filesystem root.")

        root = Path(self.root_path).expanduser().resolve(strict=True)
        current = root
        for part in relative.parts:
            if part in ("", "."):
                continue
            current = current / part
            if current.is_symlink():
                raise ValueError("Symbolic links are not allowed in filesystem resource paths.")

        try:
            resolved = (root / relative).resolve(strict=True)
            resolved.relative_to(root)
        except FileNotFoundError as exc:
            raise FileNotFoundError("Filesystem resource not found.") from exc
        except ValueError as exc:
            raise ValueError("Resource path resolves outside the configured filesystem root.") from exc

        if expected_type == "file" and not resolved.is_file():
            raise FileNotFoundError("Filesystem resource is not a regular file.")
        if expected_type == "directory" and not resolved.is_dir():
            raise FileNotFoundError("Filesystem resource is not a directory.")
        return resolved

    def test_connection(self) -> bool:
        """Verify the root path exists and is readable."""
        return self.root_path.is_dir() and os.access(self.root_path, os.R_OK)

    def list_resources(self) -> List[Dict[str, Any]]:
        """List regular files/directories under the root without following symlinks."""
        resources = []
        root = Path(self.root_path).expanduser().resolve()
        if not root.is_dir():
            return resources

        for item in root.glob(self.glob_pattern):
            try:
                if item.is_symlink():
                    continue
                resolved = item.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if not self.include_hidden and item.name.startswith("."):
                continue
            if len(item.parts) - len(root.parts) > self.max_depth:
                continue
            if self.file_types and item.suffix.lower() not in self.file_types:
                continue

            stat = resolved.stat()
            resources.append({
                "id": str(resolved.relative_to(root)),
                "type": "directory" if resolved.is_dir() else "file",
                "name": resolved.name,
                "path": str(resolved),
                "size": stat.st_size if resolved.is_file() else 0,
                "extension": resolved.suffix.lower(),
                "modified": stat.st_mtime,
            })

        return resources

    def read_resource(self, resource_id: str) -> Dict[str, Any]:
        """Read a regular file after enforcing root containment."""
        file_path = self._resolve_path(resource_id, "file")
        stat = file_path.stat()
        content = None
        is_binary = False

        try:
            content = file_path.read_text(encoding=self.encoding)
        except (UnicodeDecodeError, ValueError):
            is_binary = True

        if content is not None:
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        else:
            content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()[:16]

        return {
            "resource_id": resource_id,
            "name": file_path.name,
            "path": str(file_path),
            "size": stat.st_size,
            "extension": file_path.suffix.lower(),
            "modified": stat.st_mtime,
            "is_binary": is_binary,
            "content": content,
            "content_hash": content_hash,
        }

    def read_resource_as_object(self, resource_id: str) -> DataObject:
        """Read a file and wrap it as a DataObject."""
        data = self.read_resource(resource_id)
        ext = data.get("extension", "")

        # Determine object type based on extension
        type_map = {
            ".csv": ObjectType.DATASET.value,
            ".tsv": ObjectType.DATASET.value,
            ".json": ObjectType.DATASET.value,
            ".xml": ObjectType.DATASET.value,
            ".parquet": ObjectType.DATASET.value,
            ".md": ObjectType.DOCUMENT.value,
            ".txt": ObjectType.DOCUMENT.value,
            ".pdf": ObjectType.DOCUMENT.value,
            ".py": ObjectType.CODE.value,
            ".js": ObjectType.CODE.value,
            ".ts": ObjectType.CODE.value,
            ".ipynb": ObjectType.NOTEBOOK.value,
            ".jpg": ObjectType.MEDIA.value,
            ".jpeg": ObjectType.MEDIA.value,
            ".png": ObjectType.MEDIA.value,
            ".mp3": ObjectType.MEDIA.value,
            ".mp4": ObjectType.MEDIA.value,
        }
        obj_type = type_map.get(ext, ObjectType.FILE.value)

        # Parse JSON content if applicable
        content = data.get("content")
        if ext == ".json" and isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                pass

        return DataObject(
            type=obj_type,
            schema="file.v1",
            properties={
                "source_connector": self.name,
                "filename": data.get("name"),
                "file_path": data.get("path"),
                "size": data.get("size"),
                "extension": ext,
                "is_binary": data.get("is_binary", False),
                "content_hash": data.get("content_hash"),
            },
            content=content,
            source=f"connector://{self.name}/{resource_id}",
        )

    def read_directory(self, sub_path: str = ".", limit: int = 100) -> List[Dict[str, Any]]:
        """Read a bounded directory listing beneath the configured root."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000.")
        dir_path = self._resolve_path(sub_path, "directory")
        root = Path(self.root_path).expanduser().resolve()
        results = []
        for item in sorted(dir_path.iterdir()):
            if len(results) >= limit:
                break
            if item.is_symlink():
                continue
            try:
                resolved = item.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if not self.include_hidden and resolved.name.startswith("."):
                continue
            stat = resolved.stat()
            results.append({
                "name": resolved.name,
                "path": str(resolved.relative_to(root)),
                "type": "directory" if resolved.is_dir() else "file",
                "size": stat.st_size if resolved.is_file() else 0,
            })
        return results

    def search_files(self, query: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """Search for files by name substring (case-insensitive)."""
        query_lower = query.lower()
        all_resources = self.list_resources()
        matches = [
            r for r in all_resources
            if query_lower in r["name"].lower() or query_lower in r.get("path", "").lower()
        ]
        return matches[:max_results]

    def close(self) -> None:
        """No-op for filesystem connector (no persistent connections)."""
        pass
