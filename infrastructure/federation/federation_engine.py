"""
Federation Protocol Engine for Multi-Instance DataOS (Rule #64).
Enables querying, discovering, and searching across autonomous, distributed DataOS instances.
"""

from __future__ import annotations
import urllib.request
import urllib.error
import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from core.object.model import DataObject
from infrastructure.storage.base import StorageBackend
from engines.search.search_engine import HybridSearchEngine


@dataclass
class FederatedPeer:
    """Represents a remote connected DataOS instance."""
    peer_id: str
    name: str
    base_url: str
    is_active: bool = True
    auth_token: Optional[str] = None
    last_ping_ms: float = 0.0


class DataOSFederationEngine:
    """Orchestrates cross-instance federated queries and searches."""

    def __init__(self, storage: StorageBackend, local_instance_id: str = "dataos_primary"):
        self.storage = storage
        self.local_instance_id = local_instance_id
        self.peers: Dict[str, FederatedPeer] = {}
        self.local_search = HybridSearchEngine(storage)

    def register_peer(
        self,
        peer_id: str,
        name: str,
        base_url: str,
        auth_token: Optional[str] = None
    ) -> FederatedPeer:
        """Register a remote DataOS peer instance."""
        peer = FederatedPeer(
            peer_id=peer_id,
            name=name,
            base_url=base_url.rstrip("/"),
            auth_token=auth_token
        )
        self.peers[peer_id] = peer
        return peer

    def list_peers(self) -> List[Dict[str, Any]]:
        """Return list of registered peer instances."""
        return [
            {
                "peer_id": p.peer_id,
                "name": p.name,
                "base_url": p.base_url,
                "is_active": p.is_active,
                "last_ping_ms": p.last_ping_ms
            }
            for p in self.peers.values()
        ]

    def federated_search(
        self,
        query: str,
        include_local: bool = True,
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Execute federated search across local instance and all registered active peers.
        """
        all_results: List[Dict[str, Any]] = []
        peer_responses: Dict[str, Any] = {}

        # 1. Local Search
        if include_local:
            local_matches = self.local_search.search(query, limit=top_k)
            for m in local_matches:
                m["source_instance"] = self.local_instance_id
                m["is_local"] = True
                all_results.append(m)
            peer_responses[self.local_instance_id] = {"status": "ok", "results_count": len(local_matches)}

        # 2. Remote Peer Searches
        for peer_id, peer in self.peers.items():
            if not peer.is_active:
                continue

            peer_url = f"{peer.base_url}/api/search/?q={urllib.parse.quote(query)}&limit={top_k}"
            req = urllib.request.Request(peer_url)
            if peer.auth_token:
                req.add_header("Authorization", f"Bearer {peer.auth_token}")

            start_t = time.time()
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    peer.last_ping_ms = round((time.time() - start_t) * 1000.0, 2)
                    remote_results = data.get("results", [])
                    for r in remote_results:
                        r["source_instance"] = peer_id
                        r["is_local"] = False
                        all_results.append(r)
                    peer_responses[peer_id] = {
                        "status": "ok",
                        "latency_ms": peer.last_ping_ms,
                        "results_count": len(remote_results)
                    }
            except Exception as e:
                peer_responses[peer_id] = {"status": "unreachable", "error": str(e)}

        # Rank all federated results by score
        all_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        return {
            "query": query,
            "total_matches": len(all_results),
            "results": all_results[:top_k],
            "peer_responses": peer_responses
        }
