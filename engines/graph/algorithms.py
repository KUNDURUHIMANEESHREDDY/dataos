"""
Graph Analytics Engine for DataOS (Rule #56).
Projects persistent relationships into NetworkX for analytical computation:
PageRank, Degree/Betweenness Centrality, Community Detection, Shortest Paths.
NetworkX is the analysis engine, NOT the authoritative graph store.
"""

from __future__ import annotations
import networkx as nx
from typing import Dict, Any, List, Optional
from infrastructure.storage.base import StorageBackend


class GraphAnalyticsEngine:
    """Analytical graph algorithms executed over NetworkX projections."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def build_networkx_projection(
        self,
        min_confidence: float = 0.0,
        relation_types: Optional[List[str]] = None,
        directed: bool = True
    ) -> nx.DiGraph | nx.Graph:
        """Construct an on-demand NetworkX graph projection from persistent store."""
        G = nx.DiGraph() if directed else nx.Graph()

        # Load all active objects as nodes
        objects = self.storage.list_objects(limit=10000)
        for obj in objects:
            G.add_node(
                obj.id,
                type=obj.type,
                schema=obj.schema,
                version=obj.version,
                source=obj.source
            )

        # Load all active relationships as edges
        relationships = self.storage.list_relationships(min_confidence=min_confidence, limit=50000)
        for rel in relationships:
            if relation_types and rel.relation_type not in relation_types:
                continue
            G.add_edge(
                rel.source,
                rel.target,
                id=rel.id,
                relation_type=rel.relation_type,
                weight=rel.confidence,
                confidence=rel.confidence
            )

        return G

    def compute_pagerank(self, min_confidence: float = 0.0, alpha: float = 0.85) -> Dict[str, float]:
        """Compute PageRank importance scores for all graph objects."""
        G = self.build_networkx_projection(min_confidence=min_confidence, directed=True)
        if len(G.nodes) == 0:
            return {}
        try:
            scores = nx.pagerank(G, alpha=alpha, weight="weight")
            return {k: round(v, 6) for k, v in sorted(scores.items(), key=lambda item: item[1], reverse=True)}
        except Exception:
            return {node: 1.0 / len(G.nodes) for node in G.nodes}

    def compute_degree_centrality(self, min_confidence: float = 0.0) -> Dict[str, Dict[str, float]]:
        """Compute in-degree, out-degree, and total degree centrality."""
        G = self.build_networkx_projection(min_confidence=min_confidence, directed=True)
        if len(G.nodes) == 0:
            return {}
        
        in_deg = nx.in_degree_centrality(G)
        out_deg = nx.out_degree_centrality(G)
        deg = nx.degree_centrality(G)

        result = {}
        for node in G.nodes:
            result[node] = {
                "in_degree": round(in_deg.get(node, 0.0), 4),
                "out_degree": round(out_deg.get(node, 0.0), 4),
                "total_degree": round(deg.get(node, 0.0), 4)
            }
        return result

    def compute_betweenness_centrality(self, min_confidence: float = 0.0) -> Dict[str, float]:
        """Compute betweenness centrality (identifies bottleneck/bridge objects)."""
        G = self.build_networkx_projection(min_confidence=min_confidence, directed=True)
        if len(G.nodes) == 0:
            return {}
        bc = nx.betweenness_centrality(G, weight="weight")
        return {k: round(v, 6) for k, v in sorted(bc.items(), key=lambda item: item[1], reverse=True)}

    def detect_communities(self, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        """Detect clusters/communities in the data graph using Louvain/Greedy Modularity."""
        G = self.build_networkx_projection(min_confidence=min_confidence, directed=False)
        if len(G.nodes) == 0:
            return []
        
        try:
            communities = nx.community.greedy_modularity_communities(G)
            result = []
            for idx, comm in enumerate(communities):
                members = list(comm)
                result.append({
                    "community_id": idx,
                    "size": len(members),
                    "members": members,
                    "sample_types": list({G.nodes[n].get("type", "unknown") for n in members})
                })
            return result
        except Exception:
            return [{"community_id": 0, "size": len(G.nodes), "members": list(G.nodes), "sample_types": []}]

    def find_shortest_path(self, source_id: str, target_id: str) -> Optional[Dict[str, Any]]:
        """Compute weighted shortest path between two objects."""
        G = self.build_networkx_projection(directed=True)
        if source_id not in G or target_id not in G:
            return None
        try:
            path = nx.shortest_path(G, source=source_id, target=target_id, weight="weight")
            length = nx.shortest_path_length(G, source=source_id, target=target_id, weight="weight")
            return {
                "source": source_id,
                "target": target_id,
                "path": path,
                "hop_count": len(path) - 1,
                "path_weight": length
            }
        except nx.NetworkXNoPath:
            return None
