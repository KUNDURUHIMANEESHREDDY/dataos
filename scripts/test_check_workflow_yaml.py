"""Regression tests for the fail-closed workflow validator."""

from pathlib import Path
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


ALERT_GATE_RUN = """
gh api --paginate --jq 'select((.rule.security_severity_level // "") == "critical" or (.rule.security_severity_level // "") == "high") | [((.number // 0) | tostring), (.rule.security_severity_level // "unknown")] | @tsv' "repos/${GITHUB_REPOSITORY}/code-scanning/alerts?state=open&per_page=100&${filter}"
if [[ "$GITHUB_EVENT_NAME" == "pull_request" ]]; then
  alerts="$(fetch_alerts "pr=${PR_NUMBER}")"
else
  alerts="$(fetch_alerts "ref=refs/heads/${GITHUB_REF_NAME}")"
fi
if [[ "$count" != "0" ]]; then
  exit 1
fi
"""


def _valid_workflow():
    security_needs = ["secret-scan", "dependency-audit", "sbom", "codeql"]
    backend_needs = ["backend", "postgres-storage", "security-required", "workflow-lint"]
    security = _aggregate(security_needs)
    security["steps"].append(
        {
            "name": "Fail on open critical/high code-scanning alerts",
            "env": {
                "GH_TOKEN": "${{ github.token }}",
                "PR_NUMBER": "${{ github.event.pull_request.number }}",
            },
            "run": ALERT_GATE_RUN,
        }
    )
    return {
        "jobs": {
            "security-required": security,
            "backend-required": _aggregate(backend_needs),
        }
    }


class WorkflowYamlGateTests(unittest.TestCase):
    def test_duplicate_mapping_key_is_rejected(self):
        source = "jobs:\n  backend: {}\n  backend: {}\n"
        with self.assertRaises(yaml.constructor.ConstructorError):
            yaml.load(source, Loader=UniqueKeyLoader)

    def test_valid_fail_closed_aggregates_pass(self):
        self.assertTrue(validate_gate_contract(Path("workflow.yml"), _valid_workflow()))

    def test_aggregate_with_dependencies_but_no_result_guards_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["steps"][0]["run"] = "echo looks good"
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_comment_only_result_guards_fail(self):
        workflow = _valid_workflow()
        env = workflow["jobs"]["security-required"]["steps"][0]["env"]
        workflow["jobs"]["security-required"]["steps"][0]["run"] = "\n".join(
            f'# test "${variable}" = "success"'
            for variable in env
        )
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_missing_dependency_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["backend-required"]["needs"].remove("postgres-storage")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))


    def test_missing_critical_high_alert_gate_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["steps"] = [
            step
            for step in workflow["jobs"]["security-required"]["steps"]
            if step.get("name") != "Fail on open critical/high code-scanning alerts"
        ]
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_alert_gate_without_failing_on_nonzero_alerts_fails(self):
        workflow = _valid_workflow()
        alert_step = workflow["jobs"]["security-required"]["steps"][-1]
        alert_step["run"] = alert_step["run"].replace("exit 1", "echo warning")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_alert_gate_counts_by_stable_alert_number_without_lossy_deduplication(self):
        workflow = _valid_workflow()
        alert_step = workflow["jobs"]["security-required"]["steps"][-1]
        self.assertTrue(validate_gate_contract(Path("workflow.yml"), workflow))
        alert_step["run"] = alert_step["run"].replace("(.number // 0)", "(.rule.id // \"unknown\")")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_alert_gate_deduplication_is_rejected(self):
        workflow = _valid_workflow()
        alert_step = workflow["jobs"]["security-required"]["steps"][-1]
        alert_step["run"] = alert_step["run"].replace('alerts="$(fetch_alerts "pr=${PR_NUMBER}")"', 'alerts="$(fetch_alerts "pr=${PR_NUMBER}" | sort -u)"')
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_aggregate_without_always_condition_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["if"] = "success()"
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))


if __name__ == "__main__":
    unittest.main()
