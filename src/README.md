# src/

Contains the application source code implementing the SignalScope AI workflow.

## audit_config.py

Loads and validates one audit's `audits/<slug>/audit_config.json` into a frozen
`AuditConfig` (brand, company name, report subject, market, category, ordered
competitors, question library name) and derives that audit's standard file paths from
its slug. `default_audit_config()` returns the default audit
(`boots-uk-health-beauty`), which every engine and runner uses when no audit is
selected. `parse_audit_arg()` implements the shared `--audit SLUG` command-line
option. `validate_audit_config_data()` checks an in-memory config mapping with exactly
the rules the loader applies to `audit_config.json`. See the "Audit Configuration"
section of the [README](../README.md).

Corresponding tests are in
[tests/test_audit_config.py](../tests/test_audit_config.py).

## create_audit.py

Creates a new audit workspace (v2.2). `create_audit_workspace()` validates the
operator's eight config values (the v2.1 rules plus creation-only rules: exactly three
competitors, the brand not a competitor, and no surrounding whitespace, line breaks,
control characters or square brackets), validates the master question template,
generates `buyer_questions.csv` by single-pass placeholder substitution, and creates
`audits/<slug>/audit_config.json`, `buyer_questions.csv` and a header-only
`audit_results.csv`. Files are written to a `.creating-*` staging folder, checked with
the existing loaders, then published with one rename; an existing audit or report
folder is never overwritten, and any failure leaves nothing behind. It never calls an
LLM, and it does not run any part of the audit itself.

Run it from the repository root:

```
python src/create_audit.py --slug <slug> --brand "<brand>" --company-name "<name>" \
  --report-subject "<subject>" --market "<market>" --category "<category>" \
  --competitor "<first>" --competitor "<second>" --competitor "<third>" \
  --question-library "<library name>" [--dry-run]
```

`--dry-run` performs every check and writes nothing. See the "Creating a New Audit"
section of the [README](../README.md).

Corresponding tests are in
[tests/test_create_audit.py](../tests/test_create_audit.py).

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
