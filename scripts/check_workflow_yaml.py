#!/usr/bin/env python3
"""Validate workflow YAML, reject duplicate keys, and protect required-gate dependencies."""

from pathlib import Path
import sys

import yaml
from yaml.constructor import ConstructorError


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys instead of silently overriding them."""


def construct_unique_mapping(loader: UniqueKeyLoader, node, deep: bool = False):
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)


RESULT_ENV = {
    "secret-scan": "SECRET_SCAN_RESULT",
    "dependency-audit": "DEPENDENCY_AUDIT_RESULT",
    "sbom": "SBOM_RESULT",
    "codeql": "CODEQL_RESULT",
    "backend": "BACKEND_RESULT",
    "postgres-storage": "POSTGRES_RESULT",
    "security-required": "SECURITY_RESULT",
    "workflow-lint": "WORKFLOW_LINT_RESULT",
}


def has_fail_closed_result_checks(job: dict, required_needs: set[str]) -> bool:
    """Require every prerequisite result to be explicitly checked for success."""
    for step in job.get("steps", []):
        if not isinstance(step, dict):
            continue
        env = step.get("env")
        run = step.get("run")
        if not isinstance(env, dict) or not isinstance(run, str):
            continue

        for dependency in required_needs:
            variable = RESULT_ENV.get(dependency)
            expected_expression = f"${{{{ needs.{dependency}.result }}}}"
            expected_guard = f'test "${variable}" = "success"'
            if (
                variable is None
                or env.get(variable) != expected_expression
                or expected_guard not in run
            ):
                break
        else:
            return True
    return False


def validate_gate_contract(path: Path, workflow: object) -> bool:
    """Ensure release aggregates both depend on and fail closed for required jobs."""
    if not isinstance(workflow, dict):
        print(f"FAIL: {path}: workflow root must be a mapping", file=sys.stderr)
        return False

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        print(f"FAIL: {path}: missing jobs mapping", file=sys.stderr)
        return False

    expected = {
        "security-required": {"secret-scan", "dependency-audit", "sbom", "codeql"},
        "backend-required": {
            "backend",
            "postgres-storage",
            "security-required",
            "workflow-lint",
        },
    }
    ok = True
    for job_id, required_needs in expected.items():
        job = jobs.get(job_id)
        if not isinstance(job, dict):
            print(f"FAIL: {path}: required job {job_id!r} is missing", file=sys.stderr)
            ok = False
            continue

        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        missing = required_needs - set(needs if isinstance(needs, list) else [])
        if missing:
            print(
                f"FAIL: {path}: {job_id!r} must depend on {', '.join(sorted(missing))}",
                file=sys.stderr,
            )
            ok = False

        if job.get("if") != "always()":
            print(
                f"FAIL: {path}: {job_id!r} must use if: always() so failures are evaluated",
                file=sys.stderr,
            )
            ok = False

        if not has_fail_closed_result_checks(job, required_needs):
            print(
                f"FAIL: {path}: {job_id!r} must explicitly require success for every prerequisite result",
                file=sys.stderr,
            )
            ok = False

    if ok:
        print(f"PASS: {path}: required release-gate dependencies and fail-closed checks are intact")
    return ok


def main() -> int:
    workflow_dir = Path(".github/workflows")
    files = sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))
    if not files:
        print(f"ERROR: no workflow YAML files found in {workflow_dir}", file=sys.stderr)
        return 1

    parsed = {}
    failed = False
    for path in files:
        try:
            with path.open("r", encoding="utf-8") as stream:
                parsed[path] = yaml.load(stream, Loader=UniqueKeyLoader)
        except (OSError, yaml.YAMLError) as exc:
            print(f"FAIL: {path}: {exc}", file=sys.stderr)
            failed = True
        else:
            print(f"PASS: {path}: valid YAML with unique mapping keys")

    gate_path = workflow_dir / "backend-verification.yml"
    if gate_path not in parsed:
        print(f"FAIL: required workflow {gate_path} was not validated", file=sys.stderr)
        failed = True
    elif not validate_gate_contract(gate_path, parsed[gate_path]):
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
