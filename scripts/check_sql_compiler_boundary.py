#!/usr/bin/env python3
"""Fail closed while the two confirmed caller-controlled SQL sinks remain.

This is a targeted regression sentinel for DataOS issue #75, not a SQL parser
or a substitute for CodeQL. Keep it until both runtimes compile a restricted,
principal/schema-aware query plan and adversarial tests prove that boundary.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# These are the exact tainted-input-to-SQLite boundaries confirmed by CodeQL
# alerts #32 and #37. Whitespace (including newlines) is intentionally flexible.
KNOWN_RAW_SQL_SINKS = {
    "engines/compute/sql_engine.py": re.compile(
        r"\b(?:conn|connection)\s*\.\s*execute\s*\(\s*sql_query\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "rust-backend/src/sql_engine.rs": re.compile(
        r"\b(?:conn|connection)\s*\.\s*prepare\s*\(\s*query\b",
        re.IGNORECASE | re.DOTALL,
    ),
}


def find_unsafe_sql_sinks(source_by_path: dict[str, str]) -> list[str]:
    """Return path:line findings for known raw-input SQLite execution sinks."""
    findings: list[str] = []
    for path, pattern in KNOWN_RAW_SQL_SINKS.items():
        source = source_by_path.get(path)
        if source is None:
            findings.append(f"{path}: missing source file; cannot verify SQL boundary")
            continue
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            findings.append(f"{path}:{line}: caller-controlled SQL reaches SQLite directly")
    return findings


def main() -> int:
    source_by_path: dict[str, str] = {}
    for path in KNOWN_RAW_SQL_SINKS:
        file_path = ROOT / path
        try:
            source_by_path[path] = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: unable to inspect {path}: {exc}", file=sys.stderr)
            return 2

    findings = find_unsafe_sql_sinks(source_by_path)
    if findings:
        print("P0 SQL compiler boundary is not satisfied (issue #75):")
        for finding in findings:
            print(f"::error::{finding}")
        print(
            "Do not merge a PR that leaves these raw SQL sinks in place. "
            "Implement the restricted AST/query-plan compiler in both runtimes; "
            "do not suppress alerts or weaken this gate."
        )
        return 1

    print(
        "Known raw SQL sinks are absent. This sentinel is not proof of parser "
        "correctness; CodeQL and adversarial compiler tests remain required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
