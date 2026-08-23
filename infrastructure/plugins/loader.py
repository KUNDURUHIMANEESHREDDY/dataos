"""
Plugin Loader for DataOS (Rule #35).
Handles dynamic discovery, loading, and lifecycle orchestration of plugins
from filesystem directories, Python entry points, and manifest files.
"""

from __future__ import annotations
import os
import json
import importlib
import importlib.util
from typing import Dict, Any, List, Optional, Type
from pathlib import Path

from .base import DataOSPlugin, PluginManifest, PluginType, PluginContext
from .registry import PluginRegistry, PluginState


DEFAULT_PLUGIN_DIRS = [
    os.path.join(os.path.expanduser("~"), ".dataos", "plugins"),
    os.path.join(".", "dataos_plugins"),
]


class PluginLoadError(Exception):
    """Raised when a plugin fails to load."""
    pass


class PluginLoader:
    """
    Discovers and loads DataOS plugins from:
    - Filesystem directories containing plugin.json manifests
    - Python entry point groups
    - Explicit module paths
    """

    def __init__(
        self,
        plugin_dirs: Optional[List[str]] = None,
        entry_point_group: str = "dataos.plugins",
    ):
        self.plugin_dirs = plugin_dirs or DEFAULT_PLUGIN_DIRS
        self.entry_point_group = entry_point_group
        self._loaded_modules: Dict[str, Any] = {}

    def discover_plugins(self) -> List[Dict[str, Any]]:
        """
        Scan all plugin directories for plugin.json manifests.
        Returns list of manifest dicts found.
        """
        discovered = []
        for plugin_dir in self.plugin_dirs:
            dir_path = Path(plugin_dir)
            if not dir_path.is_dir():
                continue
            for child in dir_path.iterdir():
                if not child.is_dir():
                    continue
                manifest_path = child / "plugin.json"
                if manifest_path.is_file():
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest_data = json.load(f)
                        manifest_data["_source_dir"] = str(child)
                        discovered.append(manifest_data)
                    except (json.JSONDecodeError, OSError) as e:
                        print(f"[PluginLoader] Skipping {manifest_path}: {e}")
        return discovered

    def load_from_manifest(self, manifest_data: Dict[str, Any]) -> DataOSPlugin:
        """
        Load a plugin class from a manifest dict.
        The manifest must specify 'entry_point' as 'module:ClassName'.
        """
        source_dir = manifest_data.get("_source_dir", ".")
        entry_point = manifest_data.get("entry_point", "plugin:DataOSPlugin")
        module_name, class_name = entry_point.rsplit(":", 1) if ":" in entry_point else (entry_point, "DataOSPlugin")

        module_path = os.path.join(source_dir, module_name.replace(".", "/") + ".py")
        if not os.path.isfile(module_path):
            # Try as package
            module_path = os.path.join(source_dir, module_name.replace(".", "/"), "__init__.py")

        if not os.path.isfile(module_path):
            raise PluginLoadError(f"Module not found: {module_path}")

        spec = importlib.util.spec_from_file_location(
            f"dataos_plugin_{manifest_data.get('plugin_id', 'unknown')}",
            module_path,
        )
        if not spec or not spec.loader:
            raise PluginLoadError(f"Cannot load module spec: {module_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plugin_class = getattr(module, class_name, None)
        if plugin_class is None:
            raise PluginLoadError(f"Class '{class_name}' not found in {module_path}")

        if not (isinstance(plugin_class, type) and issubclass(plugin_class, DataOSPlugin)):
            raise PluginLoadError(f"Class '{class_name}' is not a DataOSPlugin subclass")

        manifest = PluginManifest.from_dict(manifest_data)
        plugin_instance = plugin_class(manifest=manifest, config=manifest_data.get("config", {}))
        self._loaded_modules[manifest.plugin_id] = module
        return plugin_instance

    def load_from_module_path(self, module_path: str, class_name: str = "DataOSPlugin", config: Optional[Dict[str, Any]] = None) -> DataOSPlugin:
        """
        Load a plugin directly from a Python module file path.
        """
        if not os.path.isfile(module_path):
            raise PluginLoadError(f"Module file not found: {module_path}")

        spec = importlib.util.spec_from_file_location("dataos_dynamic_plugin", module_path)
        if not spec or not spec.loader:
            raise PluginLoadError(f"Cannot load spec: {module_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plugin_class = getattr(module, class_name, None)
        if plugin_class is None:
            raise PluginLoadError(f"Class '{class_name}' not found in {module_path}")

        if not (isinstance(plugin_class, type) and issubclass(plugin_class, DataOSPlugin)):
            raise PluginLoadError(f"Class '{class_name}' is not a DataOSPlugin subclass")

        manifest = PluginManifest(
            plugin_id=f"dynamic_{Path(module_path).stem}",
            name=class_name,
            version="0.0.1",
            plugin_type=PluginType.CUSTOM,
            entry_point=f"{Path(module_path).stem}:{class_name}",
        )
        return plugin_class(manifest=manifest, config=config or {})

    def load_entry_points(self) -> List[DataOSPlugin]:
        """
        Discover plugins registered via Python entry points (e.g. setup.cfg, pyproject.toml).
        """
        plugins = []
        try:
            from importlib.metadata import entry_points
            eps = entry_points()
            group_eps = eps.select(group=self.entry_point_group) if hasattr(eps, "select") else eps.get(self.entry_point_group, [])
            for ep in group_eps:
                try:
                    plugin_class = ep.load()
                    if isinstance(plugin_class, type) and issubclass(plugin_class, DataOSPlugin):
                        manifest = PluginManifest(
                            plugin_id=ep.name,
                            name=ep.name,
                            version="0.0.1",
                            plugin_type=PluginType.CUSTOM,
                        )
                        plugins.append(plugin_class(manifest=manifest))
                except Exception as e:
                    print(f"[PluginLoader] Failed to load entry point '{ep.name}': {e}")
        except ImportError:
            pass
        return plugins

    def load_all(self, context: Optional[PluginContext] = None) -> Dict[str, bool]:
        """
        Full plugin loading pipeline:
        1. Discover from filesystem
        2. Load from entry points
        3. Register, initialize, and activate all
        """
        registry = PluginRegistry()
        if context:
            registry.set_context(context)

        results = {}

        # 1. Filesystem discovery
        for manifest_data in self.discover_plugins():
            try:
                plugin = self.load_from_manifest(manifest_data)
                manifest = PluginManifest.from_dict(manifest_data)
                registry.register(plugin, manifest)
                results[manifest.plugin_id] = True
            except PluginLoadError as e:
                pid = manifest_data.get("plugin_id", "unknown")
                results[pid] = False
                print(f"[PluginLoader] Failed to load plugin '{pid}': {e}")

        # 2. Entry points
        for plugin in self.load_entry_points():
            try:
                registry.register(plugin, plugin.manifest)
                results[plugin.manifest.plugin_id] = True
            except Exception as e:
                results[plugin.manifest.plugin_id] = False
                print(f"[PluginLoader] Failed to register EP plugin: {e}")

        # 3. Initialize and activate
        registry.initialize_all()
        registry.activate_all()

        return results

    def hot_reload(self, plugin_id: str, context: Optional[PluginContext] = None) -> bool:
        """
        Hot-reload a single plugin: unregister, reload from source, re-register.
        """
        registry = PluginRegistry()
        entry = registry.get(plugin_id)
        if not entry:
            return False

        source_dir = entry.manifest.to_dict().get("_source_dir")
        manifest_data = entry.manifest.to_dict()
        if source_dir:
            manifest_data["_source_dir"] = source_dir

        registry.unregister(plugin_id)
        try:
            plugin = self.load_from_manifest(manifest_data)
            registry.register(plugin, entry.manifest)
            if context:
                registry.set_context(context)
            registry.initialize_plugin(plugin_id)
            registry.activate_plugin(plugin_id)
            return True
        except PluginLoadError as e:
            print(f"[PluginLoader] Hot-reload failed for '{plugin_id}': {e}")
            return False
