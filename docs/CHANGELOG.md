# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this
project will adhere to [Semantic Versioning](https://semver.org/) once a first
functional release exists.

## [2.3.0] — 2026-09-26

Structured batch evidence collection. An operator can now collect complete structured
Gemini evidence for every question of an audit with one resumable command. The results
file format and all existing engine and report calculations are unchanged, and the
Boots UK Health & Beauty demonstration audit and its reports are unchanged.

### Added

- `src/run_structured_batch_audit.py`, the structured multi-question evidence
  collection runner and CLI (`--audit`, `--limit`, `--delay`, `--questions`,
  `--results`). Questions are processed one at a time in question-file order; each
  answer is analysed with the existing response analyser and saved as one structurally
  complete row before the next question starts.
- Full raw-response evidence files:
  `audits/<slug>/raw_responses/<question_id>__gemini.json` holds the complete,
  unedited answer with `format_version`, `audit_slug`, `question_id`, `question`,
  `engine`, `requested_model` (the model requested, not a confirmed served version),
  `run_date` and `raw_response_text`. The answer is saved before it is analysed, and
  analysis always reads the saved file.
- Resumable processing: questions not yet started are answered and analysed; questions
  whose answer was saved but not analysed are completed from the saved answer without
  a second answer call; completed questions are skipped. Re-running a finished audit
  makes no API calls and changes no files.
- `--limit N` (attempt the next N questions still needing work) and `--delay S`
  (seconds between questions).
- No-overwrite evidence integrity: evidence files are published atomically with a
  filesystem hard link and are never replaced; malformed or conflicting evidence is
  reported and left untouched; filesystems without hard links stop the run rather
  than fall back to overwriting.
- Per-question atomic persistence of `audit_results.csv` using the existing writer and
  duplicate check. Question-level failures are reported and later questions continue;
  storage or integrity failures, and unexpected changes to the results file, stop the
  run with earlier results kept.
- `.gitignore` rule `audits/*/raw_responses/`, so raw AI responses are never committed,
  including for the Boots demonstration audit.
- Tests: `tests/test_run_structured_batch_audit.py` (raw evidence, question states,
  single-question processing, a full 40-question run, resume, `--limit`/`--delay`,
  failure and stop behaviour, interruption, historical Boots protection, the
  create → collect → report chain and the report coverage wording). No test calls
  Gemini.

### Changed

- The audit report's and GEO findings report's "partial dataset" wording (and the
  "Not all … questions" and "Complete the remaining …" statements) now appear only
  when not every question has a structurally complete Gemini result; a complete audit
  is described as complete. Statements and the engine-coverage line about Perplexity
  rows appear only when Perplexity rows exist. Output for the Boots demonstration audit
  is byte-identical to before.
- `run_structured_batch_audit.py` is the recommended evidence collection workflow.
- Documentation (README, data dictionary, methodology, module READMEs) describes the
  structured batch, raw evidence storage, the historical-row policy and operator
  rules. The Streamlit dashboard shows version 2.3.0.

### Preserved / not included

- `src/run_batch_audit.py` is kept unchanged for backwards compatibility; it collects
  answers only and should not be used for new evidence collection.
- The 11-column `audit_results.csv` format is unchanged.
- Historical rows are not backfilled: legacy rows without structured fields are not
  reprocessed, and older complete rows are not regenerated to create raw evidence.
- No database, scheduling, SaaS interface, multi-provider orchestration, audit
  snapshots or history.

## [2.2.0] — 2026-09-24

Repeatable client audit creation. An operator can now create a complete, immediately
usable audit workspace for a new client with one command. Existing audit, report and
engine behaviour is unchanged, and the Boots UK Health & Beauty audit remains the
default.

### Added

- `src/create_audit.py`, the audit creation module and operator CLI
  (`python src/create_audit.py --slug … --brand … --company-name … --report-subject …
  --market … --category … --competitor … ×3 --question-library … [--dry-run]`). It
  creates `audits/<slug>/audit_config.json`, `buyer_questions.csv` and a header-only
  `audit_results.csv`.
- Deterministic buyer-question generation: the six placeholders in
  `questions/buyer_questions_master.csv` are replaced in a single pass in every column,
  preserving question IDs, stages and order. No LLM is used, and the master template is
  only read. The master template itself is validated (exact columns, unique IDs, known
  stages, supported and well-formed placeholders).
- Creation-time input rules on top of the v2.1 config rules: exactly three
  competitors, the brand not listed as a competitor, and no surrounding whitespace,
  line breaks, control characters or square brackets in any value.
- Collision protection: creation refuses if `audits/<slug>/` or `reports/<slug>/`
  already exists. There is no overwrite option.
- Staged, rollback-safe creation: files are written to a temporary `.creating-*` folder
  inside `audits/`, reloaded with the existing production loaders, then published with
  a single rename. Any failure removes the staging folder and leaves no partial audit.
- `--dry-run`: performs every check, including collision checks, and writes nothing.
- Client-data ignore policy in `.gitignore`: folders under `audits/` and `reports/` are
  ignored except the Boots UK demonstration audit, which remains tracked.
- Tests: `tests/test_create_audit.py`, covering validation, template checks, question
  generation, byte-for-byte recreation of the committed Boots `audit_config.json` and
  `buyer_questions.csv`, collision refusal, rollback after injected failures, dry runs,
  the CLI, immediate `--audit` use, and release governance. No test calls Gemini.

### Changed

- `src/audit_config.py`: new public `validate_audit_config_data()` validates an
  in-memory config with exactly the rules `load_audit_config()` applies. The loader's
  behaviour and the 8-field schema are unchanged.
- The Streamlit dashboard shows version 2.2.0.
- `tests/test_v21_cli_and_compat.py`: the dashboard test now checks that a version
  number is shown rather than pinning 2.1.0; the exact version is checked in
  `tests/test_create_audit.py`.
- Documentation: README (new "Creating a New Audit" section, version roadmap,
  limitations, corrected table of contents and test counts), the question generation
  guide (generation replaces the manual copy-and-replace steps; review steps kept),
  `CURRENT_SPRINT.md`, `src/README.md` and `tests/README.md`.

### Not included

- Structured batch evidence collection across all 40 questions (planned for v2.3).
- Audit snapshots and history, scheduled monitoring, a database, authentication,
  billing, client self-service or any SaaS functionality.
- Variable competitor counts and alternative question templates.

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
