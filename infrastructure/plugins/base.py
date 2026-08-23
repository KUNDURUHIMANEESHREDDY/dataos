"""
Plugin Base Classes for DataOS (Rule #35).
Defines the standard interfaces that all DataOS plugins must implement.
Plugins extend: object types, connectors, AI providers, storage systems, workflow actions.
"""

from __future__ import annotations
import abc
from typing import Dict, Any, List, Optional, Type
from enum import Enum


class PluginType(str, Enum):
    """Categories of plugins supported by DataOS."""
    OBJECT_TYPE = "object_type"
    CONNECTOR = "connector"
    AI_PROVIDER = "ai_provider"
    STORAGE = "storage"
    WORKFLOW_ACTION = "workflow_action"
    SEARCH = "search"
    COMPUTE = "compute"
    EXPORT = "export"
    CUSTOM = "custom"


class PluginManifest:
    """Metadata describing a plugin's identity, version, and capabilities."""

    def __init__(
        self,
        plugin_id: str,
        name: str,
        version: str,
        plugin_type: PluginType,
        description: str = "",
        author: str = "",
        dependencies: Optional[List[str]] = None,
        config_schema: Optional[Dict[str, Any]] = None,
        entry_point: str = "plugin:DataOSPlugin",
        min_dataos_version: str = "1.0.0",
    ):
        self.plugin_id = plugin_id
        self.name = name
        self.version = version
        self.plugin_type = plugin_type
        self.description = description
        self.author = author
        self.dependencies = dependencies or []
        self.config_schema = config_schema or {}
        self.entry_point = entry_point
        self.min_dataos_version = min_dataos_version

    def to_dict(self) -> Dict[str, Any]:
        """Return manifest as dictionary."""
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "plugin_type": self.plugin_type.value,
            "description": self.description,
            "author": self.author,
            "dependencies": self.dependencies,
            "config_schema": self.config_schema,
            "entry_point": self.entry_point,
            "min_dataos_version": self.min_dataos_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """Create manifest from dictionary."""
        return cls(
            plugin_id=data["plugin_id"],
            name=data["name"],
            version=data["version"],
            plugin_type=PluginType(data.get("plugin_type", "custom")),
            description=data.get("description", ""),
            author=data.get("author", ""),
            dependencies=data.get("dependencies", []),
            config_schema=data.get("config_schema", {}),
            entry_point=data.get("entry_point", "plugin:DataOSPlugin"),
            min_dataos_version=data.get("min_dataos_version", "1.0.0"),
        )


class DataOSPlugin(abc.ABC):
    """
    Abstract base class for all DataOS plugins.
    Every plugin must implement lifecycle hooks: initialize, activate, deactivate, shutdown.
    Plugins receive a PluginContext providing access to the DataOS kernel.
    """

    def __init__(self, manifest: PluginManifest, config: Optional[Dict[str, Any]] = None):
        self.manifest = manifest
        self.config = config or {}
        self._initialized = False
        self._active = False

    @abc.abstractmethod
    def initialize(self, context: "PluginContext") -> None:
        """Called once when the plugin is loaded. Acquire resources, register capabilities."""
        pass

    @abc.abstractmethod
    def activate(self) -> None:
        """Called when the plugin is activated (enabled). Begin processing."""
        pass

    @abc.abstractmethod
    def deactivate(self) -> None:
        """Called when the plugin is deactivated (disabled). Pause processing."""
        pass

    @abc.abstractmethod
    def shutdown(self) -> None:
        """Called once when the plugin is unloaded. Release all resources."""
        pass

    def get_capabilities(self) -> List[str]:
        """Return list of capability strings this plugin provides. Override to advertise."""
        return []

    def get_config_schema(self) -> Dict[str, Any]:
        """Return JSON Schema for plugin configuration. Override for validation."""
        return self.manifest.config_schema

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate configuration against schema. Return list of error messages."""
        return []

    @property
    def is_initialized(self) -> bool:
        """Return True if plugin has been initialized."""
        return self._initialized

    @property
    def is_active(self) -> bool:
        """Return True if plugin is active."""
        return self._active


class PluginContext:
    """
    Read-only context provided to plugins during initialization.
    Grants controlled access to DataOS kernel components.
    """

    def __init__(
        self,
        storage=None,
        graph_engine=None,
        search_engine=None,
        event_bus=None,
        object_registry=None,
        kernel=None,
    ):
        self.storage = storage
        self.graph_engine = graph_engine
        self.search_engine = search_engine
        self.event_bus = event_bus
        self.object_registry = object_registry
        self.kernel = kernel

    def publish_event(self, topic: str, payload: Dict[str, Any]) -> None:
        """Convenience method to publish events through the system event bus."""
        if self.event_bus:
            self.event_bus.publish(topic, payload)
