"""
Intelligent Caching Engine for DataOS (Rule #62).
Dependency-aware caching with TTL expiration, LRU eviction,
invalidation propagation, and hit/miss statistics.
"""

from __future__ import annotations
import time
import threading
from typing import Dict, Any, Optional, Set, List, Callable
from collections import OrderedDict


class CacheEntry:
    """A single cached value with metadata."""

    def __init__(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
        tags: Optional[Set[str]] = None,
        dependencies: Optional[Set[str]] = None,
    ):
        self.key = key
        self.value = value
        self.created_at = time.time()
        self.last_accessed = time.time()
        self.access_count = 0
        self.ttl_seconds = ttl_seconds
        self.tags = tags or set()
        self.dependencies = dependencies or set()
        self.version = 1

    @property
    def is_expired(self) -> bool:
        """Return True if entry has exceeded TTL."""
        if self.ttl_seconds is None:
            return False
        return (time.time() - self.created_at) > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        """Return age of entry in seconds."""
        return time.time() - self.created_at

    def touch(self) -> None:
        """Update access time and count."""
        self.last_accessed = time.time()
        self.access_count += 1

    def to_dict(self) -> Dict[str, Any]:
        """Return metadata as dictionary."""
        return {
            "key": self.key,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "ttl_seconds": self.ttl_seconds,
            "age_seconds": round(self.age_seconds, 2),
            "is_expired": self.is_expired,
            "tags": list(self.tags),
            "dependencies": list(self.dependencies),
            "version": self.version,
        }


class CacheNode:
    """Doubly-linked list node for LRU tracking."""

    def __init__(self, key: str):
        self.key = key
        self.prev: Optional[CacheNode] = None
        self.next: Optional[CacheNode] = None


class DependencyAwareCache:
    """
    LRU cache with dependency tracking, TTL, and tag-based invalidation.
    Thread-safe for concurrent access.
    """

    def __init__(self, max_size: int = 1000, default_ttl: Optional[int] = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

        # LRU doubly-linked list
        self._head = CacheNode("")
        self._tail = CacheNode("")
        self._head.next = self._tail
        self._tail.prev = self._head
        self._lru_map: Dict[str, CacheNode] = {}

        # Dependency graph: key -> set of keys that depend on it
        self._dependents: Dict[str, Set[str]] = {}

        # Stats
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "invalidations": 0}

    def _move_to_front(self, node: CacheNode) -> None:
        """Move node to front of LRU list (most recently used)."""
        if node.prev:
            node.prev.next = node.next
        if node.next:
            node.next.prev = node.prev
        node.next = self._head.next
        node.prev = self._head
        if self._head.next:
            self._head.next.prev = node
        self._head.next = node

    def _remove_from_list(self, node: CacheNode) -> None:
        """Remove node from LRU list."""
        if node.prev:
            node.prev.next = node.next
        if node.next:
            node.next.prev = node.prev

    def _evict_lru(self) -> Optional[str]:
        """Evict the least recently used entry."""
        if self._tail.prev == self._head:
            return None
        node = self._tail.prev
        self._remove_from_list(node)
        del self._lru_map[node.key]
        del self._cache[node.key]
        self._stats["evictions"] += 1
        return node.key

    def get(self, key: str) -> Optional[Any]:
        """Get a cached value. Returns None on miss or expiry."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None
            if entry.is_expired:
                self._remove_entry(key)
                self._stats["misses"] += 1
                return None
            entry.touch()
            if key in self._lru_map:
                self._move_to_front(self._lru_map[key])
            self._stats["hits"] += 1
            return entry.value

    def put(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        tags: Optional[Set[str]] = None,
        dependencies: Optional[Set[str]] = None,
    ) -> None:
        """Put a value in the cache."""
        with self._lock:
            # If key exists, update
            if key in self._cache:
                entry = self._cache[key]
                entry.value = value
                entry.ttl_seconds = ttl if ttl is not None else self.default_ttl
                entry.tags = tags or entry.tags
                entry.version += 1
                entry.touch()
                if key in self._lru_map:
                    self._move_to_front(self._lru_map[key])
                return

            # Evict if at capacity
            while len(self._cache) >= self.max_size:
                self._evict_lru()

            # Create new entry
            entry = CacheEntry(
                key=key,
                value=value,
                ttl_seconds=ttl if ttl is not None else self.default_ttl,
                tags=tags,
                dependencies=dependencies,
            )
            self._cache[key] = entry

            # Add to LRU list
            node = CacheNode(key)
            self._lru_map[key] = node
            self._move_to_front(node)

            # Register dependencies
            if dependencies:
                for dep in dependencies:
                    if dep not in self._dependents:
                        self._dependents[dep] = set()
                    self._dependents[dep].add(key)

    def _remove_entry(self, key: str) -> None:
        """Internal removal of a cache entry."""
        if key in self._lru_map:
            self._remove_from_list(self._lru_map[key])
            del self._lru_map[key]
        if key in self._cache:
            del self._cache[key]

    def invalidate(self, key: str) -> bool:
        """Invalidate a specific cache entry and its dependents."""
        with self._lock:
            if key not in self._cache:
                return False
            # Collect dependent keys
            to_invalidate = [key]
            visited = set()
            while to_invalidate:
                k = to_invalidate.pop()
                if k in visited:
                    continue
                visited.add(k)
                deps = self._dependents.get(k, set())
                to_invalidate.extend(deps - visited)

            for k in visited:
                if k in self._cache:
                    self._remove_entry(k)
                    self._stats["invalidations"] += 1
            return True

    def invalidate_by_tag(self, tag: str) -> int:
        """Invalidate all entries with a specific tag."""
        with self._lock:
            keys_to_remove = [
                k for k, entry in self._cache.items()
                if tag in entry.tags
            ]
            for k in keys_to_remove:
                self._remove_entry(k)
                self._stats["invalidations"] += 1
            return len(keys_to_remove)

    def invalidate_all(self) -> int:
        """Clear the entire cache."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._lru_map.clear()
            self._head.next = self._tail
            self._tail.prev = self._head
            self._stats["invalidations"] += count
            return count

    def get_or_put(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: Optional[int] = None,
        tags: Optional[Set[str]] = None,
        dependencies: Optional[Set[str]] = None,
    ) -> Any:
        """Get from cache, or compute and cache the result."""
        value = self.get(key)
        if value is not None:
            return value
        value = factory()
        self.put(key, value, ttl=ttl, tags=tags, dependencies=dependencies)
        return value

    def exists(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired:
                self._remove_entry(key)
                return False
            return True

    def keys(self) -> List[str]:
        """List all valid (non-expired) keys."""
        with self._lock:
            return [k for k, entry in self._cache.items() if not entry.is_expired]

    def get_entry(self, key: str) -> Optional[Dict[str, Any]]:
        """Get full metadata for a cache entry."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            return entry.to_dict()

    def get_dependents(self, key: str) -> Set[str]:
        """Get all keys that depend on the given key."""
        with self._lock:
            return set(self._dependents.get(key, set()))

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
            return {
                **self._stats,
                "size": len(self._cache),
                "max_size": self.max_size,
                "hit_rate_percent": round(hit_rate, 2),
                "total_requests": total,
                "dependency_chains": len(self._dependents),
            }

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        with self._lock:
            expired_keys = [
                k for k, entry in self._cache.items()
                if entry.is_expired
            ]
            for k in expired_keys:
                self._remove_entry(k)
            return len(expired_keys)
