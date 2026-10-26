# GitHub Actions workflow integrity

The backend verification workflow runs `scripts/check_workflow_yaml.py` as a required release-gate dependency.

The checker parses every `.yml` and `.yaml` file under `.github/workflows/` with a pinned PyYAML version and rejects duplicate mapping keys. This is important because duplicate YAML keys can silently override an earlier `needs`, `run`, or job definition and change the effective release policy without an obvious syntax error.

Run it locally after installing the same parser version used by CI:

```sh
python -m pip install PyYAML==6.0.2
python scripts/check_workflow_yaml.py
```

The `Backend required` aggregate depends on the workflow-integrity job in addition to backend tests, live PostgreSQL storage checks, and the security gate. A failed or skipped prerequisite must not be treated as a passing release gate.
