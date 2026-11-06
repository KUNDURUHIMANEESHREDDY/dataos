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
    "rust-codeql": "RUST_CODEQL_RESULT",
    "backend": "BACKEND_RESULT",
    "rust-backend": "RUST_BACKEND_RESULT",
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
        ["set -euo pipefail"]
        + [f'test "${variable}" = "success"' for variable in env]
    )
    return {"if": "always()", "needs": list(required_needs), "steps": [{"env": env, "run": run}]}


GITHUB_ALERT_GATE_SCRIPT = """const pullRef = context.eventName === "pull_request"
  ? `refs/pull/${context.payload.pull_request.number}/merge`
  : null;
const refs = context.eventName === "pull_request"
  ? [`refs/heads/${context.payload.pull_request.base.ref}`, pullRef]
  : [context.ref];
const blockingRefs = new Set(
  context.eventName === "pull_request" ? [pullRef] : [context.ref]
);
let blockingCount = 0;
for (const ref of refs) {
  const alerts = await github.paginate(
    github.rest.codeScanning.listAlertsForRepo,
    { owner: context.repo.owner, repo: context.repo.repo, state: "open", ref, per_page: 100 }
  );
  const blocking = alerts.filter(({ rule }) => ["critical", "high"].includes(rule?.security_severity_level));
  const blocksRelease = blockingRefs.has(ref);
  if (blocksRelease) blockingCount += blocking.length;
  for (const alert of blocking) {
    const location = alert.most_recent_instance?.location;
    const where = location?.path ? `${location.path}:${location.start_line ?? "?"}` : "location unavailable";
    const message = `#${alert.number} ${alert.rule?.security_severity_level}: ${alert.rule?.id} on ${ref} at ${where}`;
    if (blocksRelease) core.error(message);
    else core.warning(`Base-branch diagnostic only: ${message}`);
  }
}
if (blockingCount > 0) core.setFailed("Open critical/high alerts must be fixed on the code being released.");
else core.info("No open critical/high alerts remain on the PR merge ref or pushed branch.");"""




def _valid_workflow():
    security_needs = ["secret-scan", "dependency-audit", "sbom", "codeql", "rust-codeql"]
    backend_needs = ["backend", "rust-backend", "postgres-storage", "security-required", "workflow-lint"]
    security = _aggregate(security_needs)
    security["permissions"] = {"contents": "read", "security-events": "read"}
    security["steps"].append(
        {
            "name": "Fail on open critical/high code-scanning alerts",
            "uses": "actions/github-script@f28e40c7f34bde8b3046d885e986cb6290c5673b",
            "with": {"script": GITHUB_ALERT_GATE_SCRIPT},
        }
    )
    return {
        "on": {"pull_request": None},
        "jobs": {
            "security-required": security,
            "backend-required": _aggregate(backend_needs),
        }
    }


class WorkflowYamlGateTests(unittest.TestCase):
    def test_pull_request_trigger_is_required(self):
        workflow = _valid_workflow()
        del workflow["on"]["pull_request"]
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_pull_request_branch_filter_is_rejected(self):
        workflow = _valid_workflow()
        workflow["on"]["pull_request"] = {"branches": ["main"]}
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_pull_request_branches_ignore_filter_is_rejected(self):
        workflow = _valid_workflow()
        workflow["on"]["pull_request"] = {"branches-ignore": ["release/**"]}
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

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

    def test_aggregate_without_fail_fast_shell_mode_fails(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][0]
        step["run"] = step["run"].replace("set -euo pipefail\n", "", 1)
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

    def test_missing_rust_codeql_dependency_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["needs"].remove("rust-codeql")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_missing_rust_backend_dependency_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["backend-required"]["needs"].remove("rust-backend")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_security_alert_gate_requires_code_scanning_read_permission(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["permissions"].pop("security-events")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_security_alert_gate_accepts_write_permission(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["permissions"]["security-events"] = "write"
        self.assertTrue(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_missing_critical_high_alert_gate_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["steps"] = [
            step
            for step in workflow["jobs"]["security-required"]["steps"]
            if step.get("name") != "Fail on open critical/high code-scanning alerts"
        ]
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_github_script_alert_gate_is_accepted_without_exported_token(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][-1]
        self.assertNotIn("env", step)
        self.assertTrue(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_github_script_alert_gate_checks_base_and_merge_refs(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][-1]
        script = step["with"]["script"]
        for fragment in ("refs/heads/", "refs/pull/", "blockingRefs.has(ref)",
                         "if (blocksRelease) blockingCount += blocking.length;",
                         "core.warning(", "Base-branch diagnostic only:"):
            self.assertIn(fragment, script)
        self.assertTrue(validate_gate_contract(Path("workflow.yml"), workflow))
        for fragment in ("refs/heads/", "refs/pull/", "blockingRefs.has(ref)",
                         "if (blocksRelease) blockingCount += blocking.length;",
                         "core.warning("):
            step["with"]["script"] = script.replace(fragment, "", 1)
            self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))
            step["with"]["script"] = script

    def test_github_script_alert_gate_logs_source_locations(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][-1]
        script = step["with"]["script"]
        self.assertIn("location?.path", script)
        self.assertIn("location.start_line", script)
        self.assertTrue(validate_gate_contract(Path("workflow.yml"), workflow))
        step["with"]["script"] = script.replace("location?.path", "location?.name")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))
        step["with"]["script"] = script.replace("location.start_line", "location.end_line")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_github_script_alert_gate_must_fail_closed(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][-1]
        step.pop("env", None)
        step.pop("run", None)
        step["uses"] = "actions/github-script@f28e40c7f34bde8b3046d885e986cb6290c5673b"
        step["with"] = {"script": """
github.rest.codeScanning.listAlertsForRepo;
github.paginate(
  github.rest.codeScanning.listAlertsForRepo,
  { state: "open", ref, per_page: 100 }
);
const blocking = alerts.filter(({ rule }) => ["critical", "high"].includes(rule?.security_severity_level));
core.info("alerts found");
"""}
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_alert_gate_without_failing_on_nonzero_alerts_fails(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][-1]
        step["with"]["script"] = step["with"]["script"].replace("core.setFailed(", "core.info(")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_alert_gate_counts_by_stable_alert_number_without_lossy_deduplication(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][-1]
        step["with"]["script"] = step["with"]["script"].replace("alert.number", "alert.rule?.id")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_alert_gate_deduplication_is_rejected(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][-1]
        step["with"]["script"] = step["with"]["script"].replace(
            "if (blocksRelease) blockingCount += blocking.length;",
            "if (blocksRelease) blockingCount += new Set(blocking.map(alert => alert.rule?.id)).size;",
        )
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_alert_gate_uses_pull_request_merge_ref_filter(self):
        workflow = _valid_workflow()
        step = workflow["jobs"]["security-required"]["steps"][-1]
        self.assertIn("refs/pull/", step["with"]["script"])
        step["with"]["script"] = step["with"]["script"].replace("refs/pull/", "pull/")
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_aggregate_without_always_condition_fails(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["if"] = "success()"
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_result_guard_hidden_in_here_document_fails(self):
        workflow = _valid_workflow()
        env = workflow["jobs"]["security-required"]["steps"][0]["env"]
        variable = next(iter(env))
        expected_guard = 'test "$' + variable + '" = "success"'
        workflow["jobs"]["security-required"]["steps"][0]["run"] = (
            "cat <<'EOF'\n" + expected_guard + "\nEOF"
        )
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_result_guard_inside_conditional_fails(self):
        workflow = _valid_workflow()
        env = workflow["jobs"]["security-required"]["steps"][0]["env"]
        variable = next(iter(env))
        expected_guard = 'test "$' + variable + '" = "success"'
        workflow["jobs"]["security-required"]["steps"][0]["run"] = (
            "if false; then\n" + expected_guard + "\nfi"
        )
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))


    def test_aggregate_guard_cannot_ignore_failure_with_step_continue_on_error(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["steps"][0]["continue-on-error"] = True
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_aggregate_job_cannot_ignore_failure_with_continue_on_error(self):
        workflow = _valid_workflow()
        workflow["jobs"]["backend-required"]["continue-on-error"] = True
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_aggregate_guard_cannot_be_conditionally_skipped(self):
        workflow = _valid_workflow()
        workflow["jobs"]["backend-required"]["steps"][0]["if"] = "false"
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_critical_alert_gate_cannot_ignore_failure_with_continue_on_error(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["steps"][-1]["continue-on-error"] = True
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))

    def test_critical_alert_gate_cannot_be_conditionally_skipped(self):
        workflow = _valid_workflow()
        workflow["jobs"]["security-required"]["steps"][-1]["if"] = "false"
        self.assertFalse(validate_gate_contract(Path("workflow.yml"), workflow))


if __name__ == "__main__":
    unittest.main()
