"""
Connector Manager for DataOS (Rule #36).
Central registry for managing connector instances, lifecycle, and discovery.
Integrates with the Plugin Architecture for extensible connector registration.
"""

from __future__ import annotations
import threading
from typing import Dict, Any, List, Optional, Type
from .base import BaseConnector
from .database_connector import DatabaseConnector
from .api_connector import APIConnector
from .filesystem_connector import FilesystemConnector


class ConnectorState:
    """Lifecycle states for a connector."""
    REGISTERED = "registered"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class ConnectorEntry:
    """Internal record for a registered connector."""

    def __init__(self, connector: BaseConnector, connector_type: str):
        self.connector = connector
        self.connector_type = connector_type
        self.state = ConnectorState.REGISTERED
        self.error: Optional[str] = None
        self.last_used: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return connector metadata as dictionary."""
        return {
            "name": self.connector.name,
            "connector_type": self.connector_type,
            "state": self.state,
            "config": {k: v for k, v in self.connector.config.items() if k != "auth_token"},
            "error": self.error,
        }


class ConnectorManager:
    """
    Singleton manager for all DataOS connectors.
    Provides registration, lookup, lifecycle, and bulk operations.
    """
    _instance = None
    _lock = threading.Lock()

    # Built-in connector type registry
    BUILTIN_TYPES: Dict[str, Type[BaseConnector]] = {
        "database": DatabaseConnector,
        "sqlite": DatabaseConnector,
        "postgresql": DatabaseConnector,
        "mysql": DatabaseConnector,
        "api": APIConnector,
        "rest_api": APIConnector,
        "filesystem": FilesystemConnector,
        "fs": FilesystemConnector,
    }

    def __new__(cls) -> "ConnectorManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._connectors: Dict[str, ConnectorEntry] = {}
                    cls._instance._custom_types: Dict[str, Type[BaseConnector]] = {}
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def register_type(self, type_name: str, connector_class: Type[BaseConnector]) -> None:
        """Register a custom connector type for dynamic instantiation."""
        self._custom_types[type_name] = connector_class

    def _resolve_class(self, connector_type: str) -> Type[BaseConnector]:
        """Resolve connector type string to a class."""
        if connector_type in self._custom_types:
            return self._custom_types[connector_type]
        if connector_type in self.BUILTIN_TYPES:
            return self.BUILTIN_TYPES[connector_type]
        raise ValueError(f"Unknown connector type: '{connector_type}'. Available: {list(self.BUILTIN_TYPES.keys()) + list(self._custom_types.keys())}")

    def create_connector(self, name: str, connector_type: str, config: Dict[str, Any]) -> BaseConnector:
        """Create and register a new connector instance."""
        if name in self._connectors:
            raise ValueError(f"Connector '{name}' already exists.")
        cls = self._resolve_class(connector_type)
        connector = cls(name=name, config=config)
        entry = ConnectorEntry(connector=connector, connector_type=connector_type)
        self._connectors[name] = entry
        return connector

    def get_connector(self, name: str) -> Optional[BaseConnector]:
        """Get a registered connector by name."""
        entry = self._connectors.get(name)
        return entry.connector if entry else None

    def get_entry(self, name: str) -> Optional[ConnectorEntry]:
        """Get the full connector entry with state metadata."""
        return self._connectors.get(name)

    def connect(self, name: str) -> bool:
        """Test connection for a registered connector."""
        entry = self._connectors.get(name)
        if not entry:
            return False
        try:
            success = entry.connector.test_connection()
            entry.state = ConnectorState.CONNECTED if success else ConnectorState.ERROR
            if not success:
                entry.error = "Connection test returned False"
            return success
        except Exception as e:
            entry.state = ConnectorState.ERROR
            entry.error = str(e)
            return False

    def disconnect(self, name: str) -> bool:
        """Close/disconnect a connector."""
        entry = self._connectors.get(name)
        if not entry:
            return False
        try:
            entry.connector.close()
            entry.state = ConnectorState.DISCONNECTED
            return True
        except Exception as e:
            entry.state = ConnectorState.ERROR
            entry.error = str(e)
            return False

    def remove(self, name: str) -> bool:
        """Disconnect and remove a connector."""
        entry = self._connectors.get(name)
        if not entry:
            return False
        self.disconnect(name)
        del self._connectors[name]
        return True

    def list_all(self) -> List[Dict[str, Any]]:
        """List all registered connectors."""
        return [entry.to_dict() for entry in self._connectors.values()]

    def list_by_type(self, connector_type: str) -> List[Dict[str, Any]]:
        """List connectors filtered by type."""
        return [entry.to_dict() for entry in self._connectors.values() if entry.connector_type == connector_type]

    def list_connected(self) -> List[Dict[str, Any]]:
        """List only connected connectors."""
        return [entry.to_dict() for entry in self._connectors.values() if entry.state == ConnectorState.CONNECTED]

    def connect_all(self) -> Dict[str, bool]:
        """Test connection for all registered connectors."""
        results = {}
        for name in self._connectors:
            results[name] = self.connect(name)
        return results

    def disconnect_all(self) -> None:
        """Disconnect all connectors."""
        for name in list(self._connectors.keys()):
            self.disconnect(name)

    def ingest_from_connector(self, connector_name: str, resource_id: str) -> Optional[DataObject]:
        """Convenience: read a resource from a connector and return as DataObject."""
        from core.object.model import DataObject as DO
        connector = self.get_connector(connector_name)
        if not connector:
            return None
        if hasattr(connector, "read_resource_as_object"):
            return connector.read_resource_as_object(resource_id)
        data = connector.read_resource(resource_id)
        return DO(
            type="dataset",
            schema="connector_response.v1",
            properties={"connector": connector_name, "resource_id": resource_id},
            content=data,
            source=f"connector://{connector_name}/{resource_id}",
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics."""
        by_type = {}
        by_state = {}
        for entry in self._connectors.values():
            by_type[entry.connector_type] = by_type.get(entry.connector_type, 0) + 1
            by_state[entry.state] = by_state.get(entry.state, 0) + 1
        return {
            "total": len(self._connectors),
            "by_type": by_type,
            "by_state": by_state,
        }
