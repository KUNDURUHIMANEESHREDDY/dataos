"""
Plugin Registry for DataOS (Rule #35).
Central registry tracking all loaded plugins, their manifests, state, and capabilities.
Thread-safe singleton with lookup by ID, type, and capability.
"""

from __future__ import annotations
import threading
from typing import Dict, Any, List, Optional
from .base import DataOSPlugin, PluginManifest, PluginType, PluginContext


class PluginState:
    """Lifecycle state of a loaded plugin."""
    LOADED = "loaded"
    INITIALIZED = "initialized"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"
    ERROR = "error"
    UNLOADED = "unloaded"


class PluginEntry:
    """Internal record for a registered plugin."""

    def __init__(self, plugin: DataOSPlugin, manifest: PluginManifest):
        self.plugin = plugin
        self.manifest = manifest
        self.state = PluginState.LOADED
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return plugin entry as dictionary."""
        return {
            "manifest": self.manifest.to_dict(),
            "state": self.state,
            "error": self.error,
            "is_active": self.plugin.is_active if self.plugin else False,
        }


class PluginRegistry:
    """
    Singleton registry for all DataOS plugins.
    Supports registration, lookup, lifecycle management, and capability queries.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls) -> "PluginRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._entries: Dict[str, PluginEntry] = {}
                    cls._instance._context: Optional[PluginContext] = None
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def set_context(self, context: PluginContext) -> None:
        """Set the kernel context provided to all plugins during initialization."""
        self._context = context

    def register(self, plugin: DataOSPlugin, manifest: PluginManifest) -> PluginEntry:
        """Register a plugin instance with its manifest."""
        if manifest.plugin_id in self._entries:
            raise ValueError(f"Plugin '{manifest.plugin_id}' is already registered.")
        entry = PluginEntry(plugin=plugin, manifest=manifest)
        self._entries[manifest.plugin_id] = entry
        return entry

    def unregister(self, plugin_id: str) -> bool:
        """Unregister and shutdown a plugin by ID."""
        entry = self._entries.get(plugin_id)
        if not entry:
            return False
        try:
            if entry.plugin.is_active:
                entry.plugin.deactivate()
                entry.state = PluginState.DEACTIVATED
            entry.plugin.shutdown()
            entry.state = PluginState.UNLOADED
        except Exception as e:
            entry.error = str(e)
            entry.state = PluginState.ERROR
        del self._entries[plugin_id]
        return True

    def get(self, plugin_id: str) -> Optional[PluginEntry]:
        """Lookup a plugin entry by ID."""
        return self._entries.get(plugin_id)

    def get_plugin(self, plugin_id: str) -> Optional[DataOSPlugin]:
        """Get the plugin instance by ID."""
        entry = self.get(plugin_id)
        return entry.plugin if entry else None

    def list_all(self) -> List[Dict[str, Any]]:
        """List all registered plugins with their state."""
        return [entry.to_dict() for entry in self._entries.values()]

    def list_by_type(self, plugin_type: PluginType) -> List[Dict[str, Any]]:
        """List plugins filtered by type."""
        return [
            entry.to_dict()
            for entry in self._entries.values()
            if entry.manifest.plugin_type == plugin_type
        ]

    def list_active(self) -> List[Dict[str, Any]]:
        """List only active plugins."""
        return [entry.to_dict() for entry in self._entries.values() if entry.state == PluginState.ACTIVE]

    def list_by_capability(self, capability: str) -> List[str]:
        """Return plugin IDs that advertise a given capability."""
        result = []
        for pid, entry in self._entries.items():
            if capability in entry.plugin.get_capabilities():
                result.append(pid)
        return result

    def initialize_plugin(self, plugin_id: str) -> bool:
        """Initialize a registered plugin (call its initialize hook)."""
        entry = self._entries.get(plugin_id)
        if not entry:
            return False
        try:
            entry.plugin.initialize(self._context)
            entry.plugin._initialized = True
            entry.state = PluginState.INITIALIZED
            return True
        except Exception as e:
            entry.error = str(e)
            entry.state = PluginState.ERROR
            return False

    def activate_plugin(self, plugin_id: str) -> bool:
        """Activate a registered and initialized plugin."""
        entry = self._entries.get(plugin_id)
        if not entry:
            return False
        if entry.state not in (PluginState.INITIALIZED, PluginState.DEACTIVATED):
            return False
        try:
            entry.plugin.activate()
            entry.plugin._active = True
            entry.state = PluginState.ACTIVE
            return True
        except Exception as e:
            entry.error = str(e)
            entry.state = PluginState.ERROR
            return False

    def deactivate_plugin(self, plugin_id: str) -> bool:
        """Deactivate an active plugin."""
        entry = self._entries.get(plugin_id)
        if not entry or entry.state != PluginState.ACTIVE:
            return False
        try:
            entry.plugin.deactivate()
            entry.plugin._active = False
            entry.state = PluginState.DEACTIVATED
            return True
        except Exception as e:
            entry.error = str(e)
            entry.state = PluginState.ERROR
            return False

    def initialize_all(self) -> Dict[str, bool]:
        """Initialize all registered plugins. Returns mapping of plugin_id -> success."""
        results = {}
        for plugin_id in self._entries:
            results[plugin_id] = self.initialize_plugin(plugin_id)
        return results

    def activate_all(self) -> Dict[str, bool]:
        """Activate all initialized plugins."""
        results = {}
        for plugin_id, entry in self._entries.items():
            if entry.state == PluginState.INITIALIZED:
                results[plugin_id] = self.activate_plugin(plugin_id)
        return results

    def shutdown_all(self) -> None:
        """Shutdown all plugins (deactivate then shutdown)."""
        for plugin_id in list(self._entries.keys()):
            entry = self._entries.get(plugin_id)
            if entry and entry.state == PluginState.ACTIVE:
                self.deactivate_plugin(plugin_id)
            if entry:
                try:
                    entry.plugin.shutdown()
                    entry.state = PluginState.UNLOADED
                except Exception:
                    entry.state = PluginState.ERROR

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics about registered plugins."""
        by_type = {}
        by_state = {}
        for entry in self._entries.values():
            t = entry.manifest.plugin_type.value
            by_type[t] = by_type.get(t, 0) + 1
            by_state[entry.state] = by_state.get(entry.state, 0) + 1
        return {
            "total": len(self._entries),
            "by_type": by_type,
            "by_state": by_state,
        }
