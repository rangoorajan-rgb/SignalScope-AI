# src/

Contains the application source code implementing the SignalScope AI workflow.

## audit_config.py

Loads and validates one audit's `audits/<slug>/audit_config.json` into a frozen
`AuditConfig` (brand, company name, report subject, market, category, ordered
competitors, question library name) and derives that audit's standard file paths from
its slug. `default_audit_config()` returns the default audit
(`boots-uk-health-beauty`), which every engine and runner uses when no audit is
selected. `parse_audit_arg()` implements the shared `--audit SLUG` command-line
option. See the "Audit Configuration" section of the [README](../README.md).

Corresponding tests are in
[tests/test_audit_config.py](../tests/test_audit_config.py).

## audit_runner.py

The first working layer of the audit runner (see
[CURRENT_SPRINT.md](../CURRENT_SPRINT.md), Sprint 5 — Basic Audit Runner). It loads a
`buyer_questions.csv` file for an audit instance (see [audits/](../audits/)),
validates that the required columns (`question_id`, `buyer_journey_stage`,
`question`) are present, and prints each question in a human-readable format,
followed by a total count.

It does not query any AI platform, perform any scoring, or produce a report — those
remain future work.

Run it with:

```
python src/audit_runner.py [path/to/buyer_questions.csv] [--audit SLUG]
```

If no path is given, it defaults to the selected audit's `buyer_questions.csv`
(without `--audit`, the default audit:
`audits/boots-uk-health-beauty/buyer_questions.csv`).

Corresponding tests are in
[tests/test_audit_runner.py](../tests/test_audit_runner.py).
