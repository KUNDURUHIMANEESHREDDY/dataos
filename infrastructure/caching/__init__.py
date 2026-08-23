"""
Caching infrastructure exports (Rule #62).
"""

from .cache import DependencyAwareCache, CacheEntry

__all__ = ["DependencyAwareCache", "CacheEntry"]
