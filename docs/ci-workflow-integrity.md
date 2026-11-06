# GitHub Actions workflow integrity

The backend verification workflow runs `scripts/check_workflow_yaml.py` as a required release-gate dependency.

The checker parses every `.yml` and `.yaml` file under `.github/workflows/` with a pinned PyYAML version and rejects duplicate mapping keys. It also asserts that `security-required` depends on all four security jobs and that `backend-required` depends on backend tests, PostgreSQL integration, security, and workflow lint. Both aggregates must use `if: always()` so they run and fail closed when a prerequisite fails, is skipped, or is cancelled. Duplicate YAML keys can otherwise silently override an earlier `needs`, `run`, or job definition.

Run it locally after installing the same parser version used by CI:

```sh
python -m pip install PyYAML==6.0.2
python scripts/check_workflow_yaml.py
```

The `Backend required` aggregate depends on the workflow-integrity job in addition to backend tests, live PostgreSQL storage checks, and the security gate. A failed or skipped prerequisite must not be treated as a passing release gate. The checker also rejects job- or step-level `continue-on-error` and conditional execution on guard steps, because either can turn a failed prerequisite into a green aggregate.


## Stacked pull requests

The backend verification workflow intentionally uses an unfiltered `pull_request` trigger. A branch filter such as `branches: [main]` silently omits pull requests whose base is another feature branch, so a stacked PR can otherwise receive frontend checks without the backend, PostgreSQL and security gates. The workflow validator rejects both `branches` and `branches-ignore` filters on `pull_request` to keep the release contract active for every PR base branch.
