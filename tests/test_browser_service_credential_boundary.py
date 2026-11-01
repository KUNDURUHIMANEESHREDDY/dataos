"""Prevent the server-only DataOS service credential from entering client modules."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "src"
CLIENT_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
CLIENT_DIRECTIVE = re.compile(
    r"\A(?:\ufeff)?(?:\s|//[^\n]*(?:\n|$)|/\*[\s\S]*?\*/)*(['\"])use client\1\s*;?"
)


def is_client_module(source: str) -> bool:
    """Recognize Next.js client modules, allowing a BOM and leading comments."""
    return CLIENT_DIRECTIVE.match(source) is not None


class TestBrowserServiceCredentialBoundary(unittest.TestCase):
    def test_client_module_detection_handles_comments_and_bom(self):
        self.assertTrue(is_client_module('\ufeff/* generated */\n"use client";\nimport React from "react";'))
        self.assertTrue(is_client_module("// client entry\n'use client'\nexport {}"))
        self.assertFalse(is_client_module('/* server component */\nexport const dynamic = "force-dynamic";'))
        self.assertFalse(is_client_module('import React from "react";\n"use client";'))

    def test_public_service_token_names_never_appear_in_source(self):
        self.assertTrue(CLIENT_ROOT.is_dir(), "Expected the Next.js source tree to exist")
        public_identifiers = (
            "NEXT_PUBLIC_DATAOS_API_TOKEN",
            "VITE_DATAOS_API_TOKEN",
        )
        violations = []

        for path in sorted(CLIENT_ROOT.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in CLIENT_SUFFIXES:
                continue
            source = path.read_text(encoding="utf-8")
            for identifier in public_identifiers:
                if identifier in source:
                    violations.append(f"{path.relative_to(ROOT)} references {identifier}")

            if is_client_module(source) and "DATAOS_API_TOKEN" in source:
                violations.append(
                    f"{path.relative_to(ROOT)} references the server-only service token "
                    "from a Next.js client module"
                )

        self.assertEqual(
            violations,
            [],
            "The production API service credential must remain server-only and must "
            "never be referenced by browser-bundled source.",
        )


if __name__ == "__main__":
    unittest.main()
