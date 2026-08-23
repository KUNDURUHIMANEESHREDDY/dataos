"""
Resource Governance, Quota Enforcement & Rate Limiting for DataOS (Rule #61).
Guards against unbounded compute consumption, execution timeouts, memory overruns,
and excessive API query rates per agent or user principal.
"""

from __future__ import annotations
import time
import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


class QuotaExceededError(Exception):
    """Raised when a principal exceeds their allocated resource quota."""
    pass


class RateLimitExceededError(Exception):
    """Raised when a principal exceeds their permitted query rate."""
    pass


@dataclass
class ResourceQuota:
    """Resource limits configured for a principal (agent or user)."""
    principal_id: str
    max_queries_per_minute: int = 60
    max_compute_seconds_per_hour: float = 300.0  # 5 minutes of compute per hour
    max_tokens_per_hour: int = 100000
    max_memory_mb: int = 1024  # 1 GB
    execution_timeout_seconds: float = 30.0


@dataclass
class PrincipalUsageRecord:
    """Tracks consumption metrics within sliding time windows."""
    query_timestamps: List[float] = field(default_factory=list)
    total_compute_seconds: float = 0.0
    total_tokens: int = 0
    total_queries: int = 0
    violations_count: int = 0


class ResourceGovernor:
    """Enforces computational quotas and rate limits across DataOS operations."""

    def __init__(self, default_quota: Optional[ResourceQuota] = None):
        self.default_quota = default_quota or ResourceQuota(principal_id="default")
        self.quotas: Dict[str, ResourceQuota] = {}
        self.usage: Dict[str, PrincipalUsageRecord] = {}

    def set_quota(self, quota: ResourceQuota):
        """Set resource quota for a principal."""
        self.quotas[quota.principal_id] = quota

    def get_quota(self, principal_id: str) -> ResourceQuota:
        """Get quota for a principal, falling back to default if unset."""
        return self.quotas.get(principal_id, self.default_quota)

    def _get_usage(self, principal_id: str) -> PrincipalUsageRecord:
        if principal_id not in self.usage:
            self.usage[principal_id] = PrincipalUsageRecord()
        return self.usage[principal_id]

    def check_and_consume_rate_limit(self, principal_id: str, cost: int = 1) -> Dict[str, Any]:
        """
        Check query rate limit using a 60-second sliding window.
        Raises RateLimitExceededError if rate is exceeded.
        """
        now = time.time()
        quota = self.get_quota(principal_id)
        usage = self._get_usage(principal_id)

        # Prune timestamps older than 60 seconds
        usage.query_timestamps = [t for t in usage.query_timestamps if now - t < 60.0]

        current_rpm = len(usage.query_timestamps)
        if current_rpm + cost > quota.max_queries_per_minute:
            usage.violations_count += 1
            raise RateLimitExceededError(
                f"Rate limit exceeded for '{principal_id}': {current_rpm}/{quota.max_queries_per_minute} queries/min."
            )

        # Record queries
        for _ in range(cost):
            usage.query_timestamps.append(now)
        usage.total_queries += cost

        return {
            "principal_id": principal_id,
            "current_rpm": len(usage.query_timestamps),
            "max_rpm": quota.max_queries_per_minute,
            "remaining": quota.max_queries_per_minute - len(usage.query_timestamps)
        }

    def record_compute_usage(
        self,
        principal_id: str,
        duration_seconds: float,
        tokens_used: int = 0
    ) -> Dict[str, Any]:
        """Record compute duration and token usage, checking hour budgets."""
        quota = self.get_quota(principal_id)
        usage = self._get_usage(principal_id)

        if usage.total_compute_seconds + duration_seconds > quota.max_compute_seconds_per_hour:
            usage.violations_count += 1
            raise QuotaExceededError(
                f"Compute quota exceeded for '{principal_id}': {usage.total_compute_seconds:.1f}s used (max {quota.max_compute_seconds_per_hour}s/hr)."
            )

        if usage.total_tokens + tokens_used > quota.max_tokens_per_hour:
            usage.violations_count += 1
            raise QuotaExceededError(
                f"Token budget exceeded for '{principal_id}': {usage.total_tokens + tokens_used} tokens (max {quota.max_tokens_per_hour}/hr)."
            )

        usage.total_compute_seconds += duration_seconds
        usage.total_tokens += tokens_used

        return {
            "principal_id": principal_id,
            "total_compute_seconds": round(usage.total_compute_seconds, 2),
            "total_tokens": usage.total_tokens,
            "quota_status": "healthy"
        }

    def get_principal_status(self, principal_id: str) -> Dict[str, Any]:
        """Get current quota usage and limits for a principal."""
        quota = self.get_quota(principal_id)
        usage = self._get_usage(principal_id)
        now = time.time()
        active_queries_in_window = len([t for t in usage.query_timestamps if now - t < 60.0])

        return {
            "principal_id": principal_id,
            "quota": {
                "max_queries_per_minute": quota.max_queries_per_minute,
                "max_compute_seconds_per_hour": quota.max_compute_seconds_per_hour,
                "max_tokens_per_hour": quota.max_tokens_per_hour,
                "max_memory_mb": quota.max_memory_mb
            },
            "usage": {
                "active_rpm": active_queries_in_window,
                "total_queries": usage.total_queries,
                "total_compute_seconds": round(usage.total_compute_seconds, 2),
                "total_tokens": usage.total_tokens,
                "violations_count": usage.violations_count
            }
        }
