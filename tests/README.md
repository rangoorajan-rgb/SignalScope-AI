# tests/

Automated tests covering the SignalScope AI workflow's source code in
[src/](../src/). All tests use Python's built-in `unittest` module, never call the
real Gemini API, and never write to the committed audit data or reports.

Run the complete suite (484 tests) from the repository root with:

```
python -m unittest discover -s tests -v
```

## v2.2 audit creation tests

- `test_create_audit.py` — `src/create_audit.py`:
  - input validation (exactly three competitors, brand not a competitor, whitespace,
    line breaks, control characters, brackets, slug format) and master template
    validation (columns, IDs, stages, placeholders);
  - deterministic question generation for a fictional client with `&`, apostrophes,
    accents, commas and quotes, including an exact CSV round trip;
  - Boots recreation: generating Boots from its config reproduces the committed
    `audit_config.json` and `buyer_questions.csv` byte for byte;
  - on-disk creation, refusal of an existing audit or report folder (including Boots),
    rollback after failures injected at every write, the staged check and the final
    rename, and dry runs that write nothing;
  - the CLI, and immediate use of a new audit with the existing `--audit` runners;
  - release governance: the `.gitignore` client-data rules (checked with
    `git check-ignore`), the dashboard version, and no client literals in the module.

  Every workspace is created under a temporary directory; the real `audits/`,
  `reports/` and master template are verified unchanged after each test, and the Gemini
  SDK is blocked.

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
