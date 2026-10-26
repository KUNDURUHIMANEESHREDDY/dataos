"""Regression tests for the fail-closed workflow validator."""

import unittest

import yaml

from scripts.check_workflow_yaml import UniqueKeyLoader, validate_gate_contract


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


def _aggregate(required_needs):
    env = {
        RESULT_ENV[dependency]: f"${{{{ needs.{dependency}.result }}}}"
        for dependency in required_needs
    }
    run = "\n".join(
        f'test "${variable}" = "success"'
        for variable in env
    )
    return {"if": "always()", "needs": list(required_needs), "steps": [{"env": env, "run": run}]}


def _valid_workflow():
    security_needs = ["secret-scan", "dependency-audit", "sbom", "codeql"]
    backend_needs = ["backend", "postgres-storage", "security-required", "workflow-lint"]
    return {
        "jobs": {
            "security-required": _aggregate(security_needs),
            "backend-required": _aggregate(backend_needs),
        }
    }


class WorkflowYamlGateTests(unittest.TestCase):
    def test_duplicate_mapping_key_is_rejected(self):
        source = "jobs:\n  backend: {}\n  backend: {}\n"
        with self.assertRaises(yaml.constructor.ConstructorError):
            yaml.load(source, Loader=UniqueKeyLoader)

    def test_valid_fail_closed_aggregates_pass(self):
        self.assertTrue(validate_gate_contract(__import__("pathlib").Path("workflow.yml"), _valid_workflow()))

    def test_aggregate_with_dependencies_but_no_result_guards_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["steps"][0]["run"] = "echo looks good"
        self.assertFalse(validate_gate_contract(__import__("pathlib").Path("workflow.yml"), workflow))

    def test_missing_dependency_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["backend-required"]["needs"].remove("postgres-storage")
        self.assertFalse(validate_gate_contract(__import__("pathlib").Path("workflow.yml"), workflow))

    def test_aggregate_without_always_condition_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["if"] = "success()"
        self.assertFalse(validate_gate_contract(__import__("pathlib").Path("workflow.yml"), workflow))


if __name__ == "__main__":
    unittest.main()
