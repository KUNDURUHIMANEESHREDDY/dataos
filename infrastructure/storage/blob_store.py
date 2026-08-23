"""
Blob Storage for Immutable Artifacts (Rule #8, Rule #30).
Stores and retrieves raw files with SHA-256 integrity verification.
"""

from __future__ import annotations
import os
import shutil
import hashlib
from typing import Optional, Dict, Any


class FileBlobStorage:
    """Local filesystem blob store for immutable original files."""

    def __init__(self, root_dir: str = ".dataos_blobs"):
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

    def store_file(self, source_path: str, object_id: str) -> Dict[str, Any]:
        """Store an original file immutably, keyed by hash and object ID."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file not found: {source_path}")

        file_size = os.path.getsize(source_path)
        
        # Calculate SHA-256
        sha256 = hashlib.sha256()
        with open(source_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        content_hash = sha256.hexdigest()

        # Destination filename preserves extension
        _, ext = os.path.splitext(source_path)
        dest_filename = f"{object_id}_{content_hash[:16]}{ext}"
        dest_path = os.path.join(self.root_dir, dest_filename)

        # Copy file if not exists
        if not os.path.exists(dest_path):
            shutil.copy2(source_path, dest_path)
            # Make read-only to enforce immutability
            os.chmod(dest_path, 0o444)

        return {
            "blob_path": dest_path,
            "filename": os.path.basename(source_path),
            "size_bytes": file_size,
            "sha256": content_hash,
            "extension": ext.lower()
        }

    def store_bytes(self, content_bytes: bytes, filename: str, object_id: str) -> Dict[str, Any]:
        """Store bytes as an immutable blob."""
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        _, ext = os.path.splitext(filename)
        dest_filename = f"{object_id}_{content_hash[:16]}{ext}"
        dest_path = os.path.join(self.root_dir, dest_filename)

        if not os.path.exists(dest_path):
            with open(dest_path, "wb") as f:
                f.write(content_bytes)
            os.chmod(dest_path, 0o444)

        return {
            "blob_path": dest_path,
            "filename": filename,
            "size_bytes": len(content_bytes),
            "sha256": content_hash,
            "extension": ext.lower()
        }

    def get_blob_path(self, relative_path: str) -> Optional[str]:
        """Return full path to blob if it exists."""
        if os.path.exists(relative_path):
            return relative_path
        joined = os.path.join(self.root_dir, os.path.basename(relative_path))
        return joined if os.path.exists(joined) else None
