"""Regression tests for canonical Google AI Platform resource-name parsing."""

from pathlib import Path
import sys
import unittest

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "cloud"
    / "agent-platform-alert-configuration"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

from resource_name_utils import normalize_aiplatform_resource_name


class TestAIPlatformResourceNames(unittest.TestCase):
    def test_strips_only_exact_canonical_authority(self):
        resource = "projects/demo/locations/us-central1/reasoningEngines/123"
        for value in (
            "//aiplatform.googleapis.com/" + resource,
            "https://aiplatform.googleapis.com/" + resource,
            "https://aiplatform.googleapis.com:443/" + resource,
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_aiplatform_resource_name(value), resource)

    def test_preserves_bare_resource_paths(self):
        resource = "projects/demo/locations/us-central1/reasoningEngines/123"
        self.assertEqual(normalize_aiplatform_resource_name(resource), resource)

    def test_rejects_lookalike_or_ambiguous_urls(self):
        untrusted_values = [
            "//aiplatform.googleapis.com.evil.example/projects/demo",
            "//user@aiplatform.googleapis.com/projects/demo",
            "//aiplatform.googleapis.com:bad/projects/demo",
            "//aiplatform.googleapis.com/projects/demo?next=//evil.example",
            "http://aiplatform.googleapis.com/projects/demo",
            "https://aiplatform.googleapis.com/projects/demo#fragment",
            "https://aiplatform.googleapis.com.evil.example/projects/demo",
        ]
        for value in untrusted_values:
            with self.subTest(value=value):
                self.assertIsNone(normalize_aiplatform_resource_name(value))

    def test_rejects_non_string_and_empty_values(self):
        self.assertIsNone(normalize_aiplatform_resource_name(""))
        self.assertIsNone(normalize_aiplatform_resource_name(None))


if __name__ == "__main__":
    unittest.main()
