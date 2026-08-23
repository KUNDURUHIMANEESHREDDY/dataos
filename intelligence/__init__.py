"""
Intelligence package for DataOS document, dataset, code, media, semantic, and relationship discovery.
"""

from .document.doc_parser import DocumentParser
from .dataset.dataset_parser import DatasetParser
from .code.ast_analyzer import CodeASTAnalyzer
from .media.media_parser import MediaProcessor, MediaInfo, MediaType
from .semantic.semantic_layer import SemanticLayer, SemanticTerm
from .discovery.engine import RelationshipDiscoveryEngine

# Backward compatibility
MediaParser = MediaProcessor

__all__ = [
    "DocumentParser",
    "DatasetParser",
    "CodeASTAnalyzer",
    "MediaProcessor",
    "MediaInfo",
    "MediaType",
    "MediaParser",
    "SemanticLayer",
    "SemanticTerm",
    "RelationshipDiscoveryEngine",
]
