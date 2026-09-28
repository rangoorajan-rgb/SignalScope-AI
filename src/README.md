# src/

Contains the application source code implementing the SignalScope AI workflow.

The primary operator workflow: `create_audit.py` (create an audit workspace),
`run_structured_batch_audit.py` (collect the baseline and any manual run; it calls
Gemini), `audit_history.py` (preserve, reset and compare runs) and, since v2.5,
`run_monitoring_cycle.py` (repeat that lifecycle when an external scheduler invokes
it). `run_batch_audit.py` remains a legacy answers-only runner.

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

## run_structured_batch_audit.py

Structured batch evidence collection (v2.3) — the recommended way to collect evidence
for an audit. For each question still needing work, in `buyer_questions.csv` order, it
asks Gemini (reusing `run_batch_audit.generate_with_retry`), saves the complete answer
as a raw evidence file in `audits/<slug>/raw_responses/<question_id>__gemini.json`
(published atomically, never overwritten), analyses that saved answer with the existing
`response_analyzer.analyze_response` (temporary API errors retried), builds the row
with `run_structured_audit.build_structured_row`, and saves it to `audit_results.csv`
with the existing writer and duplicate check before moving on. A question whose answer
was saved but not analysed is completed from the saved answer without asking Gemini
again; completed, legacy and problem rows are never reprocessed or rewritten. Question
failures are reported and later questions continue; storage or integrity failures stop
the run. It never generates reports.

Run it from the repository root:

```
python src/run_structured_batch_audit.py [--audit SLUG] [--limit N] [--delay S] \
  [--questions PATH] [--results PATH]
```

Exit status is 1 if any question failed or has an evidence problem, 0 otherwise. See
the "Collecting Structured Evidence" section of the [README](../README.md).

`run_batch_audit.py` is the legacy answers-only batch runner, kept unchanged for
backwards compatibility: it stores only a 500-character snippet with blank structured
fields and no raw evidence, and should not be used for new evidence collection or for
runs intended for history.

Corresponding tests are in
[tests/test_run_structured_batch_audit.py](../tests/test_run_structured_batch_audit.py).

## audit_history.py

Audit run history (v2.4). It never calls Gemini. Run it from the repository root:

```
python src/audit_history.py snapshot --audit <slug> [--allow-partial]
python src/audit_history.py list --audit <slug>
python src/audit_history.py new-run --audit <slug>
python src/audit_history.py compare --audit <slug> --from-run <run-id> --to-run <run-id>
```

- `snapshot` preserves the current run as an immutable
  `audits/<slug>/snapshots/<run-id>/` folder (run ID `YYYYMMDDTHHMMSSZ`, UTC): copies
  of the config, questions, results and raw evidence, audit and findings reports
  rendered from those copies, and `snapshot_manifest.json` with a SHA-256 hash of every
  file. A partial run needs `--allow-partial`; evidence problems always block.
- `list` shows every snapshot with its integrity result and the current run's derived
  state (read-only).
- `new-run` resets `audit_results.csv` to its header and removes the current
  `raw_responses/`, only when the latest valid snapshot preserves the current run
  exactly; running it again finishes an interrupted reset.
- `compare` measures change between two valid snapshots with the same core
  configuration and question methodology, on the Gemini questions structurally
  complete in both, using `measurement_engine.compare_audits`, and writes
  `reports/<slug>/comparisons/<from-run>__<to-run>/GEO_PROGRESS.md`.

Snapshot validation checks every hash, recomputes the coverage counts and the
requested models from the snapshot's own files, and treats `signalscope_version`
(from `version.py`) as recorded metadata. Operational errors exit with status 1. See
the "Audit History and Comparison" section of the [README](../README.md).

Corresponding tests are in
[tests/test_audit_history.py](../tests/test_audit_history.py).

## run_monitoring_cycle.py

One recurring monitoring cycle (v2.5). It is not a scheduler: Windows Task Scheduler
or cron decides when to run it, and each invocation performs at most one cycle.

```
python src/run_monitoring_cycle.py --audit <slug> --interval-days N [--dry-run]
```

- `plan_cycle()` is read-only: it derives the one safe next action from the current
  run and its snapshots (evidence problems, the manual baseline, snapshot validity, the
  v2.4 comparability rules, the due check, and a Gemini key-presence check only when
  collection is needed) and never calls Gemini or writes a file. `--dry-run` prints it.
- `run_monitoring_cycle()` takes the audit's `AuditLock`, re-plans while holding it and
  acts: `start_new_run` when due (or to finish an interrupted reset), the structured
  batch in chunks of 5 with a spend circuit breaker, `create_snapshot` for complete
  runs only, and `compare_snapshots` for the previous → new pair. It returns a
  `CycleResult`; the CLI prints it with a one-line JSON summary and exits 0 (done or
  not due), 1 (operator action), 3 (already running) or 4 (incomplete, resumable).
- `AuditLock` is a per-audit operating-system lock on `audits/<slug>/.monitoring.lock`
  (`msvcrt` on Windows, `fcntl` elsewhere), released by the kernel if the process
  dies. The file's metadata is diagnostic only.

See the "Recurring Monitoring" section of the [README](../README.md).

Corresponding tests are in
[tests/test_run_monitoring_cycle.py](../tests/test_run_monitoring_cycle.py).

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
