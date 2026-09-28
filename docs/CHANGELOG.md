# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this
project will adhere to [Semantic Versioning](https://semver.org/) once a first
functional release exists.

## [2.5.0] — 2026-09-28

Recurring monitoring. The proven v2.4 lifecycle (new run, collection, snapshot,
comparison) can now run unattended: an external scheduler invokes one safe monitoring
cycle at a time, and SignalScope decides whether a cycle is due and what the one safe
next action is. The results file format, the structured batch, the audit history
commands and all metrics are unchanged, and the Boots UK Health & Beauty demonstration
audit and its reports are unchanged. Ready for release.

### Added

- `src/run_monitoring_cycle.py`: a one-cycle monitoring command
  (`--audit`, `--interval-days`, `--dry-run`) that performs at most one cycle per
  invocation, reusing `start_new_run`, the structured batch, `create_snapshot` and
  `compare_snapshots` rather than reimplementing them.
- A read-only planner and `--dry-run`: the next action, derived from the current run
  and its snapshots, with no Gemini call and no file written.
- Pre-collection guards: evidence integrity, a valid manual baseline (monitoring never
  creates the first baseline), no fallback from an invalid latest snapshot, the v2.4
  comparability rules applied to the current methodology, and a Gemini key-presence
  check only when collection is needed and before new-run changes anything.
- A per-audit operating-system lock (`audits/<slug>/.monitoring.lock`; `msvcrt` on
  Windows, `fcntl` on Linux/macOS) held for the whole cycle; a second process for the
  same audit exits 3.
- A due guard: a new cycle starts only when the latest snapshot is at least
  `--interval-days` old (a UTC duration); one invocation never runs catch-up cycles.
- Resumable collection in chunks of 5 questions with a spend circuit breaker that
  stops when a chunk makes no progress.
- Automatic snapshots of structurally complete runs only (`allow_partial=False`).
- Automatic comparison of the immediately previous snapshot with the new one, and
  comparison-only recovery when a snapshot's comparison is missing; methodology breaks
  (manual re-baselines) are never compared across.
- Exit codes 0 (done or not due), 1 (operator action), 2 (usage), 3 (already running)
  and 4 (incomplete, resumable), and a one-line JSON summary as the last output line.
- Documentation for external scheduling with Windows Task Scheduler or cron.
- Tests: `tests/test_run_monitoring_cycle.py` (102 tests). No test calls Gemini.

### Changed

- Version 2.5.0 (`src/version.py`, recorded in new snapshot manifests) and the
  dashboard version display.
- The monitoring workflow now supports unattended, externally triggered operation.
- `.gitignore`: `audits/*/.monitoring.lock` is ignored, including for the Boots
  demonstration audit.
- Documentation (README, data dictionary, methodology, module READMEs).

### Preserved / Not Included

- The v2.3/v2.4 manual commands, the 11-column results schema, the structured batch,
  the audit history rules and all metrics are unchanged.
- Not included: an internal scheduler or daemon, a database, authentication, billing
  or a SaaS portal, automatic acceptance of partial runs, automatic recommendations,
  distributed or network-filesystem locking, Make.com or other cloud triggers, and
  monitoring controls in the dashboard.
- Known limitation: a persistently failing question may be re-attempted in later
  chunks of the same cycle, because the batch always starts from the earliest
  collectable question; spend stays bounded and completed questions are never
  repeated.

## [2.4.0] — 2026-09-28

Audit snapshots and longitudinal history. An operator can preserve a finished run as an
immutable, verifiable snapshot, reset the audit for a fresh run, and compare two
snapshots of the same audit with the existing Measurement Engine. The results file
format, the structured batch and all existing engine calculations are unchanged, and
the Boots UK Health & Beauty demonstration audit and its reports are unchanged. Ready
for release.

### Added

- `src/audit_history.py`, the audit history CLI (`snapshot`, `list`, `new-run`,
  `compare`). None of its commands calls Gemini.
- Immutable snapshots in `audits/<slug>/snapshots/<run-id>/` (run ID
  `YYYYMMDDTHHMMSSZ`, UTC): byte-for-byte copies of the run's `audit_config.json`,
  `buyer_questions.csv`, `audit_results.csv` and `raw_responses/`, plus
  `reports/audit_report.md` and `reports/GEO_FINDINGS.md` rendered from those copies.
  Snapshots are built in a staging folder, validated and published with one rename;
  a published snapshot is never overwritten.
- `snapshot_manifest.json` with provenance, coverage and a SHA-256 hash of every other
  snapshot file. Every read verifies the hashes, rejects undeclared files and
  recomputes the coverage counts (tamper detection, not prevention).
- Complete and partial snapshots: a partial run is preserved only with
  `--allow-partial`; evidence integrity problems always block a snapshot.
- `list`: every snapshot with its integrity result, and the current run's derived
  state (fresh, in progress / partial, complete, snapshotted, reset interrupted).
- `new-run`: resets `audit_results.csv` to its header and removes the current
  `raw_responses/`, keeping the config and questions, only when the latest valid
  snapshot preserves the current run exactly.
- Interrupted-reset recovery: evidence is retired into a hidden folder and verified
  against the snapshot before deletion; running `new-run` again finishes an
  interrupted reset.
- `compare --from-run --to-run`: directional comparison of two valid snapshots that
  share the same core configuration (slug, brand, market, category, ordered
  competitors) and question methodology (ordered question ID, buyer journey stage
  and text), written to
  `reports/<slug>/comparisons/<from-run>__<to-run>/GEO_PROGRESS.md`.
- Shared-question comparison: metrics use only Gemini questions structurally complete
  in both runs, with each run's own coverage reported separately.
- Neutral warnings when the two runs record different requested model sets or
  SignalScope versions (the comparison still runs).
- Verified requested-model provenance: snapshot validation recomputes
  `requested_models` from the preserved evidence and rejects a manifest that
  disagrees. `signalscope_version` remains recorded metadata.
- `src/version.py` (`SIGNALSCOPE_VERSION`), recorded in snapshot manifests.
- Tests: `tests/test_audit_history.py` (109 tests). No test calls Gemini.

### Changed

- Dashboard version shows 2.4.0.
- `.gitignore`: `raw_responses/` folders are ignored at any depth under `audits/`, and
  `audits/*/snapshots/` and `reports/*/comparisons/` are ignored, including for the
  Boots demonstration audit.
- `measurement_engine.render_markdown` accepts an optional run-comparison context
  (run IDs, coverage, shared question count, warnings). Without it, output is
  byte-identical to before.
- Documentation (README, data dictionary, methodology, module READMEs) describes the
  history workflow.

### Preserved / Not Included

- The 11-column `audit_results.csv` schema is unchanged.
- `src/run_structured_batch_audit.py` and the existing metrics are unchanged.
- Boots demonstration data and reports are unchanged.
- Not included: scheduling, a database, authentication, billing, a SaaS portal,
  multi-provider orchestration, snapshot deletion, repair or pruning, trend analysis
  across more than two runs, and a history view in the dashboard (which remains
  current-run only).

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
