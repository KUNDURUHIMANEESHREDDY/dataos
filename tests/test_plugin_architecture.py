"""
Tests for Plugin Architecture (Rule #35).
Validates plugin registration, lifecycle, discovery, loading, and capability queries.
"""

import unittest
import os
import tempfile
import json
import shutil
from infrastructure.plugins.base import DataOSPlugin, PluginManifest, PluginType, PluginContext
from infrastructure.plugins.registry import PluginRegistry, PluginState
from infrastructure.plugins.loader import PluginLoader, PluginLoadError


class StubPlugin(DataOSPlugin):
    """Minimal test plugin implementing the full interface."""

    def __init__(self, manifest=None, config=None):
        if manifest is None:
            manifest = PluginManifest(
                plugin_id="stub_plugin",
                name="Stub Plugin",
                version="1.0.0",
                plugin_type=PluginType.CUSTOM,
                description="A test stub plugin",
            )
        super().__init__(manifest=manifest, config=config or {})
        self._capabilities = ["test_cap_a", "test_cap_b"]
        self.initialize_called = False
        self.activate_called = False
        self.deactivate_called = False
        self.shutdown_called = False
        self.context_received = None

    def initialize(self, context):
        self.initialize_called = True
        self.context_received = context
        self._initialized = True

    def activate(self):
        self.activate_called = True
        self._active = True

    def deactivate(self):
        self.deactivate_called = True
        self._active = False

    def shutdown(self):
        self.shutdown_called = True

    def get_capabilities(self):
        return self._capabilities


class FailingPlugin(DataOSPlugin):
    """Plugin that raises errors during lifecycle."""

    def __init__(self):
        manifest = PluginManifest(
            plugin_id="failing_plugin",
            name="Failing Plugin",
            version="1.0.0",
            plugin_type=PluginType.CUSTOM,
        )
        super().__init__(manifest=manifest)

    def initialize(self, context):
        raise RuntimeError("Init failed")

    def activate(self):
        raise RuntimeError("Activate failed")

    def deactivate(self):
        raise RuntimeError("Deactivate failed")

    def shutdown(self):
        raise RuntimeError("Shutdown failed")


class TestPluginManifest(unittest.TestCase):

    def test_manifest_creation(self):
        m = PluginManifest(
            plugin_id="test.1",
            name="Test",
            version="0.1.0",
            plugin_type=PluginType.CONNECTOR,
            description="desc",
            author="author",
            dependencies=["dep_a"],
            config_schema={"type": "object"},
        )
        self.assertEqual(m.plugin_id, "test.1")
        self.assertEqual(m.plugin_type, PluginType.CONNECTOR)
        self.assertEqual(m.dependencies, ["dep_a"])

    def test_manifest_serialization(self):
        m = PluginManifest(plugin_id="x", name="X", version="1.0.0", plugin_type=PluginType.STORAGE)
        d = m.to_dict()
        m2 = PluginManifest.from_dict(d)
        self.assertEqual(m2.plugin_id, "x")
        self.assertEqual(m2.plugin_type, PluginType.STORAGE)


class TestPluginRegistry(unittest.TestCase):

    def setUp(self):
        PluginRegistry.reset()
        self.registry = PluginRegistry()

    def tearDown(self):
        PluginRegistry.reset()

    def test_register_and_get(self):
        plugin = StubPlugin()
        entry = self.registry.register(plugin, plugin.manifest)
        self.assertEqual(entry.state, PluginState.LOADED)
        self.assertIsNotNone(self.registry.get("stub_plugin"))

    def test_duplicate_registration_raises(self):
        plugin = StubPlugin()
        self.registry.register(plugin, plugin.manifest)
        with self.assertRaises(ValueError):
            self.registry.register(plugin, plugin.manifest)

    def test_unregister(self):
        plugin = StubPlugin()
        self.registry.register(plugin, plugin.manifest)
        self.assertTrue(self.registry.unregister("stub_plugin"))
        self.assertIsNone(self.registry.get("stub_plugin"))

    def test_unregister_nonexistent(self):
        self.assertFalse(self.registry.unregister("no_such_plugin"))

    def test_initialize_and_activate(self):
        plugin = StubPlugin()
        self.registry.register(plugin, plugin.manifest)
        self.assertTrue(self.registry.initialize_plugin("stub_plugin"))
        self.assertTrue(plugin.initialize_called)
        self.assertEqual(self.registry.get("stub_plugin").state, PluginState.INITIALIZED)

        self.assertTrue(self.registry.activate_plugin("stub_plugin"))
        self.assertTrue(plugin.activate_called)
        self.assertEqual(self.registry.get("stub_plugin").state, PluginState.ACTIVE)

    def test_deactivate(self):
        plugin = StubPlugin()
        self.registry.register(plugin, plugin.manifest)
        self.registry.initialize_plugin("stub_plugin")
        self.registry.activate_plugin("stub_plugin")
        self.assertTrue(self.registry.deactivate_plugin("stub_plugin"))
        self.assertTrue(plugin.deactivate_called)
        self.assertEqual(self.registry.get("stub_plugin").state, PluginState.DEACTIVATED)

    def test_failing_plugin_goes_to_error(self):
        plugin = FailingPlugin()
        self.registry.register(plugin, plugin.manifest)
        self.assertFalse(self.registry.initialize_plugin("failing_plugin"))
        self.assertEqual(self.registry.get("failing_plugin").state, PluginState.ERROR)
        self.assertIn("Init failed", self.registry.get("failing_plugin").error)

    def test_list_all(self):
        self.registry.register(StubPlugin(), StubPlugin().manifest)
        all_plugins = self.registry.list_all()
        self.assertEqual(len(all_plugins), 1)

    def test_list_by_type(self):
        manifest = PluginManifest(plugin_id="conn", name="C", version="1.0.0", plugin_type=PluginType.CONNECTOR)
        plugin = StubPlugin(manifest=manifest)
        self.registry.register(plugin, manifest)
        connectors = self.registry.list_by_type(PluginType.CONNECTOR)
        self.assertEqual(len(connectors), 1)

    def test_list_active(self):
        p = StubPlugin()
        self.registry.register(p, p.manifest)
        self.registry.initialize_plugin("stub_plugin")
        self.registry.activate_plugin("stub_plugin")
        active = self.registry.list_active()
        self.assertEqual(len(active), 1)

    def test_list_by_capability(self):
        p = StubPlugin()
        self.registry.register(p, p.manifest)
        ids = self.registry.list_by_capability("test_cap_a")
        self.assertEqual(ids, ["stub_plugin"])

    def test_initialize_all(self):
        p1 = StubPlugin()
        self.registry.register(p1, p1.manifest)
        results = self.registry.initialize_all()
        self.assertTrue(results["stub_plugin"])

    def test_activate_all(self):
        p = StubPlugin()
        self.registry.register(p, p.manifest)
        self.registry.initialize_plugin("stub_plugin")
        results = self.registry.activate_all()
        self.assertTrue(results["stub_plugin"])

    def test_shutdown_all(self):
        p = StubPlugin()
        self.registry.register(p, p.manifest)
        self.registry.initialize_plugin("stub_plugin")
        self.registry.activate_plugin("stub_plugin")
        self.registry.shutdown_all()
        self.assertTrue(p.shutdown_called)

    def test_get_stats(self):
        self.registry.register(StubPlugin(), StubPlugin().manifest)
        stats = self.registry.get_stats()
        self.assertEqual(stats["total"], 1)
        self.assertIn("custom", stats["by_type"])

    def test_set_context(self):
        ctx = PluginContext(event_bus="fake_bus")
        self.registry.set_context(ctx)
        self.assertEqual(self.registry._context.event_bus, "fake_bus")


class TestPluginLoader(unittest.TestCase):

    def setUp(self):
        PluginRegistry.reset()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        PluginRegistry.reset()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_plugin_dir(self, plugin_id, module_code, manifest_extra=None):
        """Helper to create a plugin directory with manifest and module."""
        plugin_dir = os.path.join(self.temp_dir, plugin_id)
        os.makedirs(plugin_dir, exist_ok=True)

        manifest = {
            "plugin_id": plugin_id,
            "name": plugin_id,
            "version": "1.0.0",
            "plugin_type": "custom",
            "entry_point": f"plugin:TestPlugin",
        }
        if manifest_extra:
            manifest.update(manifest_extra)

        with open(os.path.join(plugin_dir, "plugin.json"), "w") as f:
            json.dump(manifest, f)

        with open(os.path.join(plugin_dir, "plugin.py"), "w") as f:
            f.write(module_code)

        return plugin_dir

    def test_discover_plugins(self):
        module_code = '''
from infrastructure.plugins.base import DataOSPlugin, PluginManifest, PluginType

class TestPlugin(DataOSPlugin):
    def initialize(self, ctx): self._initialized = True
    def activate(self): self._active = True
    def deactivate(self): self._active = False
    def shutdown(self): pass
'''
        self._create_plugin_dir("test_disc", module_code)
        loader = PluginLoader(plugin_dirs=[self.temp_dir])
        discovered = loader.discover_plugins()
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]["plugin_id"], "test_disc")

    def test_load_from_manifest(self):
        module_code = '''
from infrastructure.plugins.base import DataOSPlugin

class TestPlugin(DataOSPlugin):
    def initialize(self, ctx): self._initialized = True
    def activate(self): self._active = True
    def deactivate(self): self._active = False
    def shutdown(self): pass
'''
        self._create_plugin_dir("test_load", module_code)
        loader = PluginLoader(plugin_dirs=[self.temp_dir])
        discovered = loader.discover_plugins()
        plugin = loader.load_from_manifest(discovered[0])
        self.assertIsInstance(plugin, DataOSPlugin)
        self.assertEqual(plugin.manifest.plugin_id, "test_load")

    def test_load_from_module_path(self):
        module_code = '''
from infrastructure.plugins.base import DataOSPlugin

class TestPlugin(DataOSPlugin):
    def initialize(self, ctx): self._initialized = True
    def activate(self): self._active = True
    def deactivate(self): self._active = False
    def shutdown(self): pass
'''
        module_path = os.path.join(self.temp_dir, "direct_plugin.py")
        with open(module_path, "w") as f:
            f.write(module_code)

        loader = PluginLoader()
        plugin = loader.load_from_module_path(module_path, class_name="TestPlugin")
        self.assertIsInstance(plugin, DataOSPlugin)

    def test_load_all(self):
        module_code = '''
from infrastructure.plugins.base import DataOSPlugin

class TestPlugin(DataOSPlugin):
    def initialize(self, ctx): self._initialized = True
    def activate(self): self._active = True
    def deactivate(self): self._active = False
    def shutdown(self): pass
'''
        self._create_plugin_dir("full_load", module_code)
        loader = PluginLoader(plugin_dirs=[self.temp_dir])
        results = loader.load_all()
        self.assertTrue(results.get("full_load"))

        registry = PluginRegistry()
        entry = registry.get("full_load")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.state, PluginState.ACTIVE)

    def test_load_nonexistent_module_raises(self):
        loader = PluginLoader()
        with self.assertRaises(PluginLoadError):
            loader.load_from_module_path("/nonexistent/path.py")

    def test_load_bad_entry_point_raises(self):
        module_code = '''
x = 1
'''
        plugin_dir = os.path.join(self.temp_dir, "bad_ep")
        os.makedirs(plugin_dir)
        with open(os.path.join(plugin_dir, "plugin.json"), "w") as f:
            json.dump({"plugin_id": "bad_ep", "name": "bad", "version": "1.0.0", "entry_point": "plugin:NonexistentClass"}, f)
        with open(os.path.join(plugin_dir, "plugin.py"), "w") as f:
            f.write(module_code)

        loader = PluginLoader(plugin_dirs=[self.temp_dir])
        with self.assertRaises(PluginLoadError):
            loader.load_from_manifest({"plugin_id": "bad_ep", "entry_point": "plugin:NonexistentClass", "_source_dir": plugin_dir})


class TestPluginContext(unittest.TestCase):

    def test_context_creation(self):
        ctx = PluginContext(storage="s", graph_engine="g", search_engine="se", event_bus="eb")
        self.assertEqual(ctx.storage, "s")
        self.assertEqual(ctx.graph_engine, "g")

    def test_publish_event_no_bus(self):
        ctx = PluginContext()
        ctx.publish_event("topic", {"key": "val"})  # Should not raise


class TestPluginType(unittest.TestCase):

    def test_all_types(self):
        for pt in PluginType:
            self.assertIsInstance(pt.value, str)


if __name__ == "__main__":
    unittest.main()
