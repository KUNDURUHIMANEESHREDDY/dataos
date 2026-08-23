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
        self.root_path = config.get("root_path", ".")
        self.glob_pattern = config.get("glob_pattern", "**/*")
        self.max_depth = config.get("max_depth", 10)
        self.include_hidden = config.get("include_hidden", False)
        self.file_types = config.get("file_types", [])
        self.encoding = config.get("encoding", "utf-8")

    def test_connection(self) -> bool:
        """Verify the root path exists and is readable."""
        return os.path.isdir(self.root_path) and os.access(self.root_path, os.R_OK)

    def list_resources(self) -> List[Dict[str, Any]]:
        """List all files and directories under root_path matching the glob pattern."""
        resources = []
        root = Path(self.root_path)
        if not root.is_dir():
            return resources

        for item in root.glob(self.glob_pattern):
            if not self.include_hidden and item.name.startswith("."):
                continue
            if len(item.parts) - len(root.parts) > self.max_depth:
                continue
            if self.file_types and item.suffix.lower() not in self.file_types:
                continue

            stat = item.stat()
            resources.append({
                "id": str(item.relative_to(root)),
                "type": "directory" if item.is_dir() else "file",
                "name": item.name,
                "path": str(item),
                "size": stat.st_size if item.is_file() else 0,
                "extension": item.suffix.lower(),
                "modified": stat.st_mtime,
            })

        return resources

    def read_resource(self, resource_id: str) -> Dict[str, Any]:
        """
        Read a file's content and metadata.
        resource_id is the relative path from root_path.
        """
        file_path = Path(self.root_path) / resource_id
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        stat = file_path.stat()
        content = None
        is_binary = False

        # Try text read first, fallback to binary
        try:
            content = file_path.read_text(encoding=self.encoding)
        except (UnicodeDecodeError, ValueError):
            is_binary = True
            content = None

        content_hash = None
        if content is not None:
            content_hash = hashlib.sha256(str(content).encode()).hexdigest()[:16]
        else:
            # Hash the raw bytes
            raw = file_path.read_bytes()
            content_hash = hashlib.sha256(raw).hexdigest()[:16]

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
        """Read all files in a subdirectory."""
        dir_path = Path(self.root_path) / sub_path
        if not dir_path.is_dir():
            return []
        results = []
        for item in sorted(dir_path.iterdir()):
            if len(results) >= limit:
                break
            if not self.include_hidden and item.name.startswith("."):
                continue
            stat = item.stat()
            results.append({
                "name": item.name,
                "path": str(item.relative_to(Path(self.root_path))),
                "type": "directory" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else 0,
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
