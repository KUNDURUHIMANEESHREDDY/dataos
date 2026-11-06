"""Regression tests for strict Vertex AI asset resource-name parsing."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "cloud"
    / "agent-platform-alert-configuration"
    / "scripts"
    / "gather_agent_info.py"
)


def load_gather_agent_info():
    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    aiplatform = types.ModuleType("google.cloud.aiplatform_v1beta1")
    cloud.aiplatform_v1beta1 = aiplatform
    google.cloud = cloud

    with patch.dict(
        sys.modules,
        {
            "google": google,
            "google.cloud": cloud,
            "google.cloud.aiplatform_v1beta1": aiplatform,
        },
    ):
        spec = importlib.util.spec_from_file_location(
            "dataos_gather_agent_info_test", SCRIPT_PATH
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load gather_agent_info.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class TestVertexResourceNameParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = load_gather_agent_info()._resource_name_from_asset_name

    def test_accepts_google_authority_relative_and_https_names(self):
        path = "projects/demo/locations/us-central1/reasoningEngines/123"
        self.assertEqual(
            self.parser(f"//aiplatform.googleapis.com/{path}"), path
        )
        self.assertEqual(
            self.parser(f"https://aiplatform.googleapis.com/{path}"), path
        )

    def test_preserves_plain_google_resource_paths(self):
        path = "projects/demo/locations/us-central1/reasoningEngines/123"
        self.assertEqual(self.parser(path), path)

    def test_rejects_untrusted_authorities_and_url_components(self):
        invalid = [
            "https://aiplatform.googleapis.com.evil.test/projects/demo",
            "//aiplatform.googleapis.com@evil.test/projects/demo",
            "https://user@aiplatform.googleapis.com/projects/demo",
            "http://aiplatform.googleapis.com/projects/demo",
            "https://aiplatform.googleapis.com:8443/projects/demo",
            "https://aiplatform.googleapis.com/projects/demo?next=evil",
            "https://aiplatform.googleapis.com/projects/demo#fragment",
            "//evil.test/projects/demo",
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(self.parser(value))


if __name__ == "__main__":
    unittest.main()
