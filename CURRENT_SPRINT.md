# Current Sprint

## v2.3 — Structured Batch Evidence Collection

**Status:** Complete — ready for commit and release (not yet released)

### Baseline: v2.2.0 (released)

v2.2.0 made client audit creation repeatable (`src/create_audit.py`), with 484 tests.
But a new audit could not yet be filled with structured evidence: the batch runner
recorded answers only, with blank structured fields, and the structured runners each
processed a single fixed question. Only a 500-character snippet of each answer was
kept.

### Objective

Complete structured batch evidence collection for a configured audit, preserving every
new Gemini answer in full, without changing the results file format or any existing
calculation or report output for the Boots demonstration audit.

### Delivered

- **Checkpoint A — raw evidence, question states and single-question processing.**
  Full raw evidence files (`audits/<slug>/raw_responses/<question_id>__gemini.json`)
  with strict validation and a no-overwrite atomic publish; filename-safe question-ID
  checks; a structural completeness check against the existing results schema; the
  question states (not started, answer stored, complete, legacy incomplete, legacy
  complete without evidence, evidence problem); retried analysis for temporary API
  errors; and single-question processing that saves the answer before analysing the
  saved file, so an answered question resumes without a second answer call. A
  `.gitignore` rule keeps raw responses out of Git.
- **Checkpoint B — the structured batch.** `src/run_structured_batch_audit.py`: pre-flight
  checks before any API call, a sequential run over all 40 questions in question-file
  order, one row saved immediately per question, `--limit` and `--delay`, question
  failures reported while later questions continue, storage or integrity failures
  stopping the run, safe resume after failure or interruption, a summary and exit
  codes, and the CLI.
- **Checkpoint C — report accuracy, documentation and release.** The audit and
  findings reports describe the dataset as partial only when not every question has a
  structurally complete Gemini result, and mention Perplexity only when Perplexity rows
  exist; the Boots reports stay byte-identical. Documentation covers the structured
  batch, raw evidence, the historical-row policy, the legacy runner and operator rules.
  The dashboard shows version 2.3.0.
- **Test protection.** 568 tests pass: the 484 from v2.2, 84 structured batch and
  report-coverage tests. The v2.1 golden reports are unchanged. No test calls Gemini.

### Known limitations

- Commands must be run from the repository root.
- Only one structured batch should run against an audit at a time; a second writer is
  detected and the run stops.
- Raw evidence publishing needs a filesystem with hard-link support.
- A hard process kill can leave a dot-prefixed `.tmp` file in `raw_responses/`; it is
  never used as evidence and can be deleted manually.
- Historical rows are not backfilled, and `requested_model` records the model
  requested, not a confirmed served model version.

### Deferred

- v2.4: audit snapshots and longitudinal history.
- v2.5: recurring monitoring workflow.
- Later platform work: database, scheduling, multi-project interface, authentication,
  cloud deployment; billing and client self-service only when justified.
- Not planned for a specific version yet: recording the served model version, storing
  the analyser's responses, backfilling historical evidence, variable competitor
  counts, alternative question templates, a dashboard audit selector, removing the
  legacy answers-only runner.

---

## Previous release records

### v2.2 — Repeatable Client Audit Creation

**Status:** Released as v2.2.0. Recorded as written at release.

#### Baseline: v2.1.0

v2.1.0 made the Audit, Insights, Recommendation and Measurement Engines, the runners and
the dashboard configuration-driven: each audit is described by
`audits/<slug>/audit_config.json` and selected with `--audit SLUG`, with Boots UK as the
default (395 tests). But creating a new audit was still manual: making the folder,
writing the JSON by hand, copying the master question file and replacing its
placeholders, and creating a results file with the exact header.

#### Objective

Turn the v2.1 configuration foundation into a repeatable, safe client audit creation
workflow, without changing any existing audit, report or engine behaviour.

#### Delivered

- **Checkpoint A — validation and in-memory generation.** A public
  `validate_audit_config_data()` in `src/audit_config.py` reuses the v2.1 config rules.
  `src/create_audit.py` adds the creation-only input rules (exactly three competitors,
  brand not a competitor, no surrounding whitespace, line breaks, control characters or
  square brackets), master template validation, single-pass placeholder substitution
  across all columns, and CSV serialisation in the existing file format. Generating
  Boots from its config reproduces the committed Boots question file byte for byte.
- **Checkpoint B — safe workspace creation and CLI.** `create_audit_workspace()` and the
  `python src/create_audit.py` operator CLI create `audit_config.json`,
  `buyer_questions.csv` and a header-only `audit_results.csv` through a staging folder,
  a check with the existing loaders and a single rename. It refuses existing audit or
  report folders, rolls back on any failure, and supports `--dry-run`. A new audit is
  immediately usable with the existing `--audit` runners.
- **Checkpoint C — governance, documentation and release.** `.gitignore` keeps client
  audit and report folders out of Git while the Boots demonstration audit stays tracked.
  The dashboard shows version 2.2.0. The README, question generation guide, changelog
  and module READMEs describe the workflow, its limitations and the version roadmap.
- **Test protection.** 484 tests pass: the 395 from v2.1 plus 89 audit-creation tests
  (validation, template checks, generation, Boots recreation, collision refusal,
  rollback after injected failures, dry runs, CLI, `--audit` usability, governance).
  One v2.1 dashboard assertion was relaxed from pinning version 2.1.0 to checking that a
  version is shown; the exact version is checked in the new tests. No test calls Gemini.

#### Known limitations

- Commands must be run from the repository root: `create_audit.py` always writes to the
  project's `audits/` folder, but the existing `--audit` runners resolve paths relative
  to the current directory.
- A hard process kill during creation can leave an `audits/.creating-<slug>-*` staging
  folder. It is not a valid audit and can be deleted manually.

#### Deferred

- v2.3: structured batch evidence collection across all 40 questions (the batch runner
  currently records answers without structured fields, and the structured runners each
  process one question).
- v2.4: audit snapshots and longitudinal history.
- v2.5: recurring monitoring workflow.
- Later platform work: database, scheduling, multi-project interface, authentication,
  cloud deployment; billing and client self-service only when justified.
- Not planned for a specific version yet: variable competitor counts, alternative
  question templates, a dashboard audit selector.

---

### v2.1 — Multi-Company Foundation

**Status:** Released as v2.1.0. Recorded as written at release; its deferred list
reflects the roadmap at that time.

#### Baseline: v2.0.0

v2.0.0 is the working SignalScope AI prototype: the Audit, Insights, Recommendation and
Measurement Engines, Markdown reporting, a read-only Streamlit dashboard and an
automated `unittest` suite (291 tests), demonstrated on the Boots UK Health & Beauty
audit. In v2.0 the Boots client values and folder paths were hardcoded across the
engines, runners and dashboard.

#### Objective

Remove company-specific coupling from the application so that the existing audit,
insights, recommendation, measurement and reporting workflow runs from a central
client/audit configuration, without changing the behaviour of the existing Boots
implementation.

#### Delivered

- **Configuration generalisation.** Each audit has an `audits/<slug>/audit_config.json`
  loaded and validated by `src/audit_config.py`. All engines and runners accept an
  optional `AuditConfig`, and every command-line entry point accepts `--audit SLUG`.
  Boots remains the default. The Streamlit dashboard and the root `config.py` (now a
  compatibility shim) read the default audit config.
- **Regression protection.** Golden-master tests regenerate the deterministic Boots
  reports and require byte-identical output against the committed reports; the
  recommendations renderer and the Boots Gemini prompts are pinned. All 291 original
  tests pass without modification.
- **Multi-client coverage.** A fictional company is run through every engine, runner and
  CLI in temporary directories with Gemini mocked, proving configuration propagation
  and no leakage of Boots values. A static guard keeps client literals out of reusable
  production code.

Implemented in three reviewed checkpoints: (A) safety net and configuration foundation,
(B) core engine parameterisation, (C) runners, `--audit` CLI, dashboard, compatibility
shim and documentation.

#### Deferred to v2.2 and later

- v2.2: reusable client audit workflow — generating a client's `buyer_questions.csv`
  from the master library, client onboarding, a dashboard audit selector.
- v2.3: repeatable audit snapshots and history.
- v2.4: recurring GEO measurement workflow.
- v2.5: client-ready audit and monitoring service.
- Later (V3): database, multi-project management, historical visualisation, scheduled
  monitoring, additional LLM providers, web application, authentication, cloud
  deployment.

---

## Historical sprint records

The records below are preserved as originally written. Their status lines reflect the
time of writing; see the git history for the sprints completed between them and v2.1.

### Sprint 1 — Audit Specification

**Status (as written):** In progress

**Objective:** Define the consulting specification for Build 1 of the SignalScope AI
audit — what an audit assesses, for whom, and against what criteria — independent of
any implementation technology.

#### Scope of this sprint

- Write [docs/AUDIT_SPECIFICATION.md](docs/AUDIT_SPECIFICATION.md), covering the
  business rationale, audit objective, scope, target markets, buyer personas,
  competitor selection, buyer journey framework, methodology, the four-dimensional
  scoring framework (Visibility, Prominence, Authority, Sentiment), human validation,
  governance, limitations, planned outputs and success criteria.

#### Explicitly out of scope for this sprint

- Any implementation detail, code, or API documentation.
- Any Python files or notebooks.
- Precise numeric scoring formulae or thresholds (flagged within the specification as
  a Build 1 implementation decision, not fixed here).
- Any real or sample client data or audit results.

#### Definition of done

- `docs/AUDIT_SPECIFICATION.md` exists and covers all required sections.
- No functionality or technical implementation is claimed to exist beyond what has
  actually been written.
- Nothing in this sprint has been committed to version control; that remains a
  separate, explicit action for the project owner.

### Sprint 0 — Project Foundation

**Status (as written):** Complete

**Objective:** Establish the professional project foundation for SignalScope AI before
any application logic, data pipelines or AI integrations are built.

#### Scope of this sprint

- Create the top-level repository structure (`docs/`, `data/`, `prompts/`, `src/`,
  `tests/`).
- Write foundational documentation:
  - [README.md](README.md)
  - [docs/PROJECT_SCOPE.md](docs/PROJECT_SCOPE.md)
  - [docs/METHODOLOGY.md](docs/METHODOLOGY.md)
  - [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)
  - [docs/CHANGELOG.md](docs/CHANGELOG.md)
  - [docs/decisions/ADR-001-Project-Principles.md](docs/decisions/ADR-001-Project-Principles.md)
- Establish a starter `.gitignore`, using common Python patterns as an illustrative
  placeholder only — no language decision has been made (see the "Technology Roadmap"
  section of [README.md](README.md)).
- Record engineering principles as an Architecture Decision Record.

#### Explicitly out of scope for this sprint

- Any application or workflow logic.
- Any package installation or dependency management.
- Any Python files or notebooks.
- Any AI prompt design or scoring implementation.
- Any real or sample client data.

#### Definition of done

- All files and folders listed above exist and are populated with accurate,
  non-speculative content.
- No functionality is claimed to exist beyond what has actually been created.
- Nothing in this sprint has been committed to version control; that remains a
  separate, explicit action for the project owner.
