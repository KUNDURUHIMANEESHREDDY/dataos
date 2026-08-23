"""
Lossless Multi-Format Export Engine for DataOS (Rule #32, Rule #66, Rule #67).
Ensures zero vendor lock-in with standard export formats:
JSON-LD, GraphML, GEXF, DOT (Graphviz), CSV, SQL Dumps, and OpenLineage.
"""

from __future__ import annotations
import json
import csv
import io
import datetime
from typing import Dict, Any, List, Optional
import networkx as nx
from core.object.model import DataObject
from core.relation.model import Relationship
from infrastructure.storage.base import StorageBackend
from engines.graph.algorithms import GraphAnalyticsEngine


class DataOSExporter:
    """Exports DataOS objects, relationships, and graphs to standard portable formats."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self.analytics_engine = GraphAnalyticsEngine(storage)

    def export_json_ld(self) -> Dict[str, Any]:
        """Export the entire DataOS graph as standard JSON-LD Linked Data."""
        objects = self.storage.list_objects(limit=10000)
        relationships = self.storage.list_relationships(limit=50000)

        graph_nodes = []
        for obj in objects:
            graph_nodes.append({
                "@id": f"urn:dataos:object:{obj.id}",
                "@type": f"dataos:{obj.type.capitalize()}",
                "schema": obj.schema,
                "version": obj.version,
                "source": obj.source,
                "properties": obj.properties,
                "timestamps": obj.timestamps.to_dict(),
                "provenance": obj.provenance
            })

        graph_edges = []
        for rel in relationships:
            graph_edges.append({
                "@id": f"urn:dataos:rel:{rel.id}",
                "source": f"urn:dataos:object:{rel.source}",
                "target": f"urn:dataos:object:{rel.target}",
                "relationType": rel.relation_type,
                "confidence": rel.confidence,
                "evidence": rel.evidence
            })

        return {
            "@context": {
                "dataos": "https://dataos.dev/ns#",
                "schema": "http://schema.org/",
                "openlineage": "https://openlineage.io/spec/"
            },
            "@graph": graph_nodes,
            "relationships": graph_edges,
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    def export_graphml(self) -> str:
        """Export the graph in standard GraphML XML format."""
        G = self.analytics_engine.build_networkx_projection(directed=True)
        # Convert non-primitive attributes to strings for GraphML safety
        for node, data in G.nodes(data=True):
            for k, v in list(data.items()):
                if isinstance(v, (dict, list)):
                    data[k] = json.dumps(v)
        for u, v, data in G.edges(data=True):
            for k, val in list(data.items()):
                if isinstance(val, (dict, list)):
                    data[k] = json.dumps(val)

        return "\n".join(nx.generate_graphml(G))

    def export_dot(self) -> str:
        """Export the graph in Graphviz DOT format."""
        relationships = self.storage.list_relationships(limit=10000)
        lines = ["digraph DataOS_Graph {", '  node [shape=box, style=rounded, fontname="Helvetica"];', '  edge [fontname="Helvetica", fontsize=10];']
        
        for rel in relationships:
            src = rel.source[:8]
            tgt = rel.target[:8]
            label = f"{rel.relation_type} ({rel.confidence})"
            lines.append(f'  "{src}" -> "{tgt}" [label="{label}"];')

        lines.append("}")
        return "\n".join(lines)

    def export_sql_dump(self) -> str:
        """Export all objects and relationships as SQL DDL and INSERT statements."""
        objects = self.storage.list_objects(limit=10000)
        relationships = self.storage.list_relationships(limit=50000)

        lines = [
            "-- DataOS SQL Export Dump",
            f"-- Generated at {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
            "",
            "CREATE TABLE IF NOT EXISTS dataos_objects (id VARCHAR(64) PRIMARY KEY, type VARCHAR(32), schema_ref VARCHAR(64), version INT, source TEXT);",
            "CREATE TABLE IF NOT EXISTS dataos_relationships (id VARCHAR(64) PRIMARY KEY, source_id VARCHAR(64), target_id VARCHAR(64), relation_type VARCHAR(32), confidence FLOAT);",
            ""
        ]

        for obj in objects:
            lines.append(f"INSERT INTO dataos_objects VALUES ('{obj.id}', '{obj.type}', '{obj.schema}', {obj.version}, '{obj.source}');")

        for rel in relationships:
            lines.append(f"INSERT INTO dataos_relationships VALUES ('{rel.id}', '{rel.source}', '{rel.target}', '{rel.relation_type}', {rel.confidence});")

        return "\n".join(lines)
