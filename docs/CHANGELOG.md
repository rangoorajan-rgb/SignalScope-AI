# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this
project will adhere to [Semantic Versioning](https://semver.org/) once a first
functional release exists.

## [2.1.0] — 2026-09-23

Multi-company audit foundation. The existing Boots UK Health & Beauty audit remains
the default and its behaviour is unchanged. (Releases between 0.2 and 2.0.0 were not
recorded in this changelog; see the git history.)

### Added

- `audits/<slug>/audit_config.json` per-audit configuration (brand, company name,
  report subject, market, category, ordered competitors, question library name), with
  the Boots audit's values in `audits/boots-uk-health-beauty/audit_config.json`.
- `src/audit_config.py`: strict, stdlib-only loader producing a frozen `AuditConfig`,
  derived per-audit file paths, `default_audit_config()`, and the shared `--audit`
  argument parser.
- `--audit SLUG` option on every command-line entry point (`audit_runner`,
  `run_single_audit`, `write_single_audit_result`, `run_batch_audit`,
  `run_structured_audit`, `run_end_to_end_demo`, `report_generator`,
  `geo_findings_analyzer`, `recommendation_engine`, `measurement_engine`). Omitting it
  runs the default audit; explicit path arguments still take precedence.
- Tests: golden-master tests reproducing the committed Boots reports byte for byte;
  configuration loader tests; fictional-client propagation tests; CLI, dashboard,
  compatibility and static client-literal guard tests.

### Changed

- The Audit, Insights, Recommendation and Measurement Engines and all runners accept an
  optional keyword-only `audit_config`. Client-specific values (brand, market,
  category, report title subject, competitors, default paths) come from it instead of
  hardcoded Boots values. Calculations, thresholds, prompt wording, report structure
  and CSV schemas are unchanged.
- Module constants such as `BRAND`, `MARKET`, `CATEGORY`, `KNOWN_COMPETITORS` and the
  `DEFAULT_*` paths remain available and are now derived from the default audit config.
- The Streamlit dashboard reads its project metadata and file locations from the
  default audit config and shows version 2.1.0. It still displays one audit, with no
  client selector.
- Root `config.py` is now a backwards-compatible shim over the default audit config,
  keeping `COMPANY_NAME`, `INDUSTRY`, `COUNTRY`, `COMPETITORS` and `QUESTION_LIBRARY`.
- `run_batch_audit.py`: `--questions` and `--results` now default to the selected
  audit's files (the default audit's files when `--audit` is omitted, as before).

### Not included

- No database, scheduled monitoring, authentication, client selector, automatic
  question-set generation from the master library, or audit snapshot history. These
  remain future work.

## [0.2] — 2026-07-16

### Added

- [AUDIT_SPECIFICATION.md](AUDIT_SPECIFICATION.md): the consulting specification for
  Build 1 of the SignalScope AI audit, covering business rationale, audit objective,
  scope, target markets, buyer personas, competitor selection, the buyer journey
  framework, methodology, the four-dimensional scoring framework (Visibility,
  Prominence, Authority, Sentiment), human validation, governance, limitations,
  planned outputs and success criteria.

No implementation, code, prompts, or numeric scoring formulae were added in this
version — see the specification's own notes on decisions deferred to Build 1.

## [0.1] — 2026-07-16

### Added

- Initial project foundation: repository structure and directories (`docs/`, `data/`,
  `prompts/`, `src/`, `tests/`).
- Core project documentation: [README.md](../README.md),
  [PROJECT_SCOPE.md](PROJECT_SCOPE.md), [METHODOLOGY.md](METHODOLOGY.md),
  [DATA_DICTIONARY.md](DATA_DICTIONARY.md).
- Project governance record:
  [ADR-001-Project-Principles.md](decisions/ADR-001-Project-Principles.md).
- Sprint tracking: [CURRENT_SPRINT.md](../CURRENT_SPRINT.md), covering Sprint 0.
- `.gitignore` with illustrative Python-oriented entries as a starting-point
  placeholder only; no language decision has been made (see the "Technology Roadmap"
  section of [README.md](../README.md)).

No application logic, data, prompts or dependencies were added in this version.
