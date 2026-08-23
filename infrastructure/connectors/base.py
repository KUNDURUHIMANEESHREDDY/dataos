"""
Standardized Connector Interfaces for DataOS (Rule #36).
Integrates external databases, filesystems, and REST APIs.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from core.object.model import DataObject


class BaseConnector(ABC):
    """Abstract connector for external data systems."""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config

    @abstractmethod
    def test_connection(self) -> bool:
        """Test connectivity to the external system."""
        pass

    @abstractmethod
    def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources in the external system."""
        pass

    @abstractmethod
    def read_resource(self, resource_id: str) -> Dict[str, Any]:
        """Read a specific resource by ID."""
        pass
