# tests/

Automated tests covering the SignalScope AI workflow's source code in
[src/](../src/). All tests use Python's built-in `unittest` module, never call the
real Gemini API, and never write to the committed audit data or reports.

Run the complete suite from the repository root with:

```
python -m unittest discover -s tests -v
```

## v2.1 multi-company tests

- `test_audit_config.py` — the `audit_config.json` loader: the Boots config
  reproduces the v2.0 values and paths exactly, and every invalid-config case fails
  clearly.
- `test_boots_golden_outputs.py` — golden-master regression tests: the deterministic
  Boots reports are regenerated in a temporary directory and must match the
  committed reports byte for byte (line endings normalised); the recommendations
  renderer is pinned against fixed canned recommendations.
- `test_multi_client_config.py` — a fictional client's `AuditConfig` flows through
  every engine and runner with no Boots value leaking into its output, while
  no-config calls still produce the Boots behaviour.
- `test_v21_cli_and_compat.py` — the `--audit SLUG` option on every command-line
  entry point, the path-only runners, the legacy defaults, the root `config.py`
  shim, the Streamlit dashboard (via `streamlit.testing`), and a static guard
  against client literals in reusable production code.

## test_audit_runner.py

Tests for `src/audit_runner.py`, written with Python's built-in `unittest` module
(no additional dependency required). Covers: loading a valid question file, a
missing file, a file missing required columns, an empty question file, the printed
output format, and an integration check against the real
[Boots UK Health & Beauty audit instance](../audits/boots-uk-health-beauty/buyer_questions.csv).

Run the tests with:

```
python -m unittest discover -s tests
```
