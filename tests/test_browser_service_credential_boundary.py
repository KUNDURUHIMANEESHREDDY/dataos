"""Prevent the server-only DataOS service credential from entering browser source."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "src"
CLIENT_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


class TestBrowserServiceCredentialBoundary(unittest.TestCase):
    def test_service_token_identifiers_never_appear_in_browser_source(self):
        forbidden_identifiers = (
            "DATAOS_API_TOKEN",
            "NEXT_PUBLIC_DATAOS_API_TOKEN",
            "VITE_DATAOS_API_TOKEN",
        )
        violations = []

        for path in sorted(CLIENT_ROOT.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in CLIENT_SUFFIXES:
                continue
            source = path.read_text(encoding="utf-8")
            for identifier in forbidden_identifiers:
                if identifier in source:
                    violations.append(f"{path.relative_to(ROOT)} references {identifier}")

        self.assertEqual(
            violations,
            [],
            "The production API service credential is server-only and must never "
            "be referenced by browser-bundled source.",
        )


if __name__ == "__main__":
    unittest.main()
