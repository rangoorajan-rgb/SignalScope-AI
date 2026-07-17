# tests/

Automated tests covering the SignalScope AI workflow's source code in
[src/](../src/).

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
