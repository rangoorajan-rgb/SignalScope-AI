# SignalScope AI Read-Only Local API — Contract Version 1

This document is the human-readable contract for `READONLY_API_CONTRACT_VERSION = 1`,
introduced in SignalScope AI v2.6.0. The implementation is the source of truth:
[src/readonly_api.py](../src/readonly_api.py) (the resources) and
[src/readonly_api_server.py](../src/readonly_api_server.py) (the HTTP transport).

## A. Purpose

The API is a **local, read-only JSON interface** over the data SignalScope already
keeps: audit configurations, the current run, snapshots, comparisons and the monitoring
plan. It exists so that a separate local tool (for example a frontend) can inspect
SignalScope safely.

- It is a transport over the existing SignalScope engine, not a replacement for it.
  Every rule (slug and run-ID validation, snapshot integrity, comparability, metrics,
  monitoring decisions) is the engine's own.
- It never changes anything: no endpoint creates, resets, snapshots, compares-to-disk,
  collects evidence or calls Gemini.
- It is not a SaaS service: there is no authentication, database, billing or cloud
  infrastructure. The v2.5 CLI commands remain the way to change audit state.

## B. Starting the Server

```bash
python src/readonly_api_server.py --port 8765
python src/readonly_api_server.py --port 8765 --allow-origin http://localhost:3000
```

| Option | Meaning |
|---|---|
| `--port N` | Port on 127.0.0.1, 1–65535 (default 8765) |
| `--allow-origin ORIGIN` | Optional. One exact browser origin (`scheme://host[:port]`) allowed by CORS |

- The server binds only to **127.0.0.1**. There is no `--host` option.
- Browser clients on the same machine can use either `http://127.0.0.1:<port>` or
  `http://localhost:<port>` (see the Host rules below).
- Only `GET` is supported. CORS is exact-origin only; `*` is not supported.
- Stop it with Ctrl+C. It keeps no state between requests.

## C. Security Model

> **This V1 API is intended for local integration, not direct public internet exposure.**
> It is not an internet-facing hardened service.

- **Bind address:** 127.0.0.1 only (IPv4 loopback).
- **Host header:** exactly one `Host` header, equal to `127.0.0.1:<actual-port>` or
  `localhost:<actual-port>` (the hostname is case-insensitive; the port must be the one
  the server is listening on). Any other Host — another hostname, another port, a
  missing, duplicate or malformed header — is refused with `400 bad_request` before any
  routing or resource call. This protects against DNS rebinding. No DNS lookups are made.
- **CORS:** only when `--allow-origin` is set, and only for that exact origin:
  `Access-Control-Allow-Origin: <origin>` and `Vary: Origin`. No wildcard, no
  credentials support, no preflight (OPTIONS is 405). No CORS header on a refused Host.
- **Methods:** GET only; every other method (including HEAD and OPTIONS) is
  `405 method_not_allowed` with `Allow: GET`.
- **No raw evidence:** full raw AI answers, evidence file paths and prompts are never
  returned; question results expose only the structured result fields and the
  500-character `answer_snippet`.
- **No secrets:** the API path does not read `.env` or the Gemini key and never runs
  Gemini.
- **No writes:** no resource changes the filesystem. Probing the monitoring lock never
  creates the lock file.
- **Sanitised errors:** unexpected failures return `500 internal_error` with a fixed
  message — no stack traces, exception text, paths or environment values.
- **Path safety:** path segments are percent-decoded one at a time; a segment containing
  a control character or a decoded `/` or `\`, or with malformed percent-encoding, is
  refused before reaching SignalScope.
- **Every response:** `Content-Type: application/json; charset=utf-8`, `Content-Length`,
  `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Connection: close`.

## D. Contract Version

`GET /health` reports two different versions:

- `signalscope_version` — the SignalScope release (for example `2.6.0`). It changes with
  every release.
- `contract_version` — this API contract (`1`). It changes only when the API's routes or
  response shapes change incompatibly.

## E. Routes

There are exactly eight routes. Anything else is `404 not_found`.

| Route | Resource |
|---|---|
| `GET /health` | Service status and versions |
| `GET /audits` | All audits |
| `GET /audits/{slug}` | One audit |
| `GET /audits/{slug}/current-run` | The audit's current (working) run |
| `GET /audits/{slug}/snapshots` | The audit's snapshot history |
| `GET /audits/{slug}/snapshots/{run_id}` | One snapshot |
| `GET /audits/{slug}/comparison?from_run=…&to_run=…` | Snapshot-to-snapshot comparison |
| `GET /audits/{slug}/monitoring-plan?interval_days=N` | Read-only monitoring plan |

`{slug}` follows the SignalScope audit slug rules (lowercase letters and digits in
single-hyphen-separated groups). `{run_id}`, `from_run` and `to_run` are snapshot run IDs
(`YYYYMMDDTHHMMSSZ`, UTC).

### GET /health

`{"status": "ok", "signalscope_version": "…", "contract_version": 1, "read_only": true}`.
No audit data is read.

### GET /audits

- `audits`: one entry per loadable audit, sorted by folder name: `slug`, `brand`,
  `company_name`, `market`, `category`, `competitors` (ordered), `current_run`
  (a *Current run summary*), `latest_snapshot` (a *Snapshot summary* or `null`),
  `snapshot_count`.
- `invalid_audits`: folders that could not be loaded, each `{folder, error}` — they are
  reported, never hidden.
- `latest_snapshot` is always the snapshot with the highest run ID, **valid or not**.
- Empty state: no audits → `{"audits": [], "invalid_audits": []}`.

### GET /audits/{slug}

`slug`, `brand`, `company_name`, `report_subject`, `market`, `category`, `competitors`,
`question_library`, `current_run` (*Current run summary*), `latest_snapshot`
(*Snapshot summary* or `null`).
Errors: `400 invalid_slug`, `404 unknown_audit`, `404 not_found` (the folder exists but
its `audit_config.json` cannot be loaded).

### GET /audits/{slug}/current-run

- `current_run`: the *Current run summary*.
- `row_basis`: `{total_rows, rows_by_engine, unique_questions}` for the current
  `audit_results.csv`, or `null` if the run cannot be read.
- `metrics`: *Dataset metrics* for all current rows, or `null`.
- `findings`: the seven findings for the current rows, or `[]`.
- `questions`: every buyer question in question-library order: `question_id`,
  `buyer_journey_stage`, `question`, `state_code` (`A`–`F`), `state_label`, `detail`,
  and `gemini_result` — `null` when no Gemini row applies, otherwise `run_date`,
  `brand_cited`, `brand_position` (integer or `null`), `competitors_cited` and
  `sources_cited` (arrays), `sentiment`, `answer_snippet`.

The question states are the engine's own:

| `state_code` | `state_label` |
|---|---|
| A | not started |
| B | answer stored, not yet analysed |
| C | complete with evidence |
| D | legacy incomplete |
| E | complete, no stored full answer |
| F | evidence integrity problem |

A legacy incomplete (D) question can carry a `gemini_result` with blank structured fields.

Empty states: a fresh run has `row_basis.total_rows = 0`, `metrics: null`,
`findings: []` and every question in state A. During an interrupted reset
(`state: "reset interrupted"`) `metrics` is `null` and `findings` is `[]`. An unreadable
run has `current_run.readable: false` with its `error`, and `row_basis: null`,
`metrics: null`, `findings: []`, `questions: []`.
Errors: `400 invalid_slug`, `404 unknown_audit`, `404 not_found`.

### GET /audits/{slug}/snapshots

- `snapshots`: every snapshot in run-ID order; each entry is a *Snapshot summary* plus
  `metrics` (*Dataset metrics* computed from **that snapshot's own** `audit_results.csv`,
  or `null` for an invalid snapshot).
- No findings and no current-run data are included. This list is the raw material for
  trends: use the valid entries with non-null `metrics`.
- Empty state: no snapshots → `{"slug": "…", "snapshots": []}`.
Errors: `400 invalid_slug`, `404 unknown_audit`, `404 not_found`.

### GET /audits/{slug}/snapshots/{run_id}

`snapshot` (*Snapshot summary*), `is_latest`, and for a valid snapshot its own
`row_basis`, `metrics` and `findings` — computed from the snapshot's own
`audit_config.json`, `buyer_questions.csv` and `audit_results.csv`.
An invalid (tampered or malformed) snapshot still returns **200** with
`snapshot.valid: false`, `snapshot.problems`, `row_basis: null`, `metrics: null` and
`findings: []`; there is no fallback to another snapshot.
Errors: `400 invalid_slug`, `400 invalid_run_id`, `404 unknown_audit`,
`404 unknown_snapshot`.

### GET /audits/{slug}/comparison?from_run=…&to_run=…

Both query parameters are required, each exactly once (otherwise
`400 comparison_refused`). See [I. Comparisons](#i-comparisons).

- Comparable result: `comparable: true`, `from_run`, `to_run`,
  `from` and `to` (`{structurally_complete_count, question_count}`),
  `unequal_coverage`, `shared_question_count`, `shared_question_ids`,
  `warnings` (`{requested_models, signalscope_version}`, each a message or `null`),
  `metrics` (seven `{metric_name, before, after, difference, direction}`),
  `overall_assessment`, `generated_at` (date of the request).
- Not comparable: **200** with `{slug, from_run, to_run, comparable: false, problems}`.
Errors: `400 invalid_slug`, `400 invalid_run_id`, `400 comparison_refused`,
`404 unknown_audit`, `404 unknown_snapshot`, `409 snapshot_invalid`.

### GET /audits/{slug}/monitoring-plan?interval_days=N

`interval_days` is required, exactly once, and must be a positive whole number
(otherwise `400 invalid_interval`). See [J. Monitoring Plan](#j-monitoring-plan).
Response: `interval_days`, `plan_outcome`, `outcome`, `planned_steps`, `active_state`,
`latest_snapshot`, `previous_snapshot` (run IDs or `null`), `due`,
`requires_collection`, `integrity_problems`, `methodology_differences`, `reasons`,
`api_key_check` (always `"not_performed"`), `lock_held`.
Errors: `400 invalid_slug`, `400 invalid_interval`, `404 unknown_audit`.

### Shared Blocks

**Current run summary:** `readable`, `error`, `state`, `detail`, `question_count`,
`structurally_complete_count`, `coverage_percent` (structurally complete ÷ questions ×
100, or `null`), `result_row_count` (all result rows, any engine),
`evidence_problem_count`, `requested_models`. When the run cannot be read, `readable`
is `false`, `error` explains why and the other fields are `null`.

**Snapshot summary:** `run_id`, `valid`, `problems`, `created_at`, `status`
(`complete` or `partial`), `signalscope_version`, `question_count`,
`structurally_complete_count`, `requested_models`. For an invalid snapshot the
manifest-derived fields are untrusted (or `null` when unreadable); `valid` and
`problems` say so.

## F. Current Run vs Snapshots

> **The current run and the snapshots are different things, and the API never blurs them.**

- **Current run** — the mutable working state in `audits/<slug>/`. Its `state` is
  `fresh`, `in progress / partial`, `complete`, `snapshotted` or `reset interrupted`.
  `/current-run` describes it; it can change at any time.
- **Snapshot** — a frozen historical run in `audits/<slug>/snapshots/<run_id>/`,
  immutable evidence when valid. `/snapshots` is the history; `/snapshots/{run_id}` is
  one snapshot.
- History is snapshots only. Comparisons are snapshot-to-snapshot only. Trends should be
  derived from valid snapshots.
- The current run is never substituted for a snapshot, and an invalid latest snapshot is
  never replaced by an older valid one.

## G. Metric Semantics

### Dataset metrics (`/current-run`, `/snapshots`, `/snapshots/{run_id}`)

Dataset metrics describe **all rows in that dataset's `audit_results.csv`** (every
engine, including manually entered rows). A dataset with zero rows has
`metrics: null` and `findings: []`.

| Block | Fields | Meaning |
|---|---|---|
| `brand_visibility` | `rate_percent`, `cited`, `not_cited`, `considered`, `excluded` | Rows with `brand_cited` Y ÷ rows with Y or N, as a percentage (`null` if none); rows with any other value are `excluded` |
| `brand_mention_frequency` | integer | Number of rows with `brand_cited` Y |
| `positive_sentiment` | `rate_percent`, `positive`, `neutral`, `negative`, `excluded` | Positive ÷ rows with a valid sentiment, as a percentage (`null` if none) |
| `authority_sources` | `distinct_count`, `rows_with_sources_percent` | Distinct cited sources; rows with any source ÷ all rows, as a percentage |
| `funnel_stage_coverage` | `stages_covered`, `stages_total`, `rows_per_stage` | Standard buyer-journey stages with at least one row (of 5); rows per stage (all five standard stages, 0 when absent, plus any other stage present) |
| `geo_maturity` | `tier` | `Established` (at least 75% of the buyer questions have a result row and brand visibility is at least 50%), `Developing` (at least 40% of questions have a row), otherwise `Early` |

`row_basis` gives the rows behind these metrics: `total_rows`, `rows_by_engine`,
`unique_questions`.

### Comparison metrics (`/comparison`)

Comparison metrics are **not** the dataset metrics above. They are the seven existing
SignalScope measurement metrics, computed only on the Gemini questions that are
structurally complete in **both** snapshots: Brand Visibility, Brand Mention Frequency,
Competitor Mention Change, Sentiment Change (Positive Rate), Authority Source Change,
Funnel Stage Coverage and Overall GEO Maturity. Each has `before`, `after` and
`difference` as display strings and a `direction` (`Improved`, `Declined`,
`No Change` or `Informational`). Because the question basis differs, a comparison value
is not numerically interchangeable with a dataset metric of the same name.

## H. Findings

- Findings belong to one dataset: the current run (`/current-run`) or one snapshot
  (`/snapshots/{run_id}`). There is no bare `/findings` endpoint.
- Each finding is `{title, value, evidence, confidence}`; there are seven per non-empty
  dataset.
- `confidence` is `High`, `Medium` or `Low`, based on how much of the relevant data the
  finding rests on. It is not a statistical probability.

## I. Comparisons

- Snapshot to snapshot only, directional: `from_run` must be earlier than `to_run`, and
  the two must differ (`400 comparison_refused` otherwise).
- Both snapshots must pass the backend's integrity validation; an invalid snapshot
  returns `409 snapshot_invalid`.
- Snapshots whose core configuration or ordered question methodology differ are not
  comparable: this is a legitimate **200** result with `comparable: false` and the
  engine's `problems`.
- Comparable snapshots with no structurally complete question in common are refused
  (`400 comparison_refused`).
- The endpoint writes nothing: no `GEO_PROGRESS.md` is created. The CLI
  `audit_history.py compare` command remains available separately and does write its
  report.
- `warnings.requested_models` and `warnings.signalscope_version` are the engine's neutral
  provenance warnings; neither claims a cause for any change.

## J. Monitoring Plan

- A read-only equivalent of checking the v2.5 monitoring plan (like
  `run_monitoring_cycle.py --dry-run`).
- The caller supplies `interval_days`; SignalScope does not store a schedule. An
  external scheduler (Task Scheduler or cron) still owns recurring invocation.
- The endpoint never runs a cycle, collects evidence, resets the run, creates a snapshot
  or writes a comparison.
- The Gemini key is deliberately not checked: `api_key_check` is `"not_performed"`, and
  plans that need collection are computed as if credentials were configured. A real
  cycle still checks the key before collecting.
- `outcome` is `"already running"` when another process holds the audit's monitoring
  lock, otherwise it equals `plan_outcome` (`ready`, `not due` or
  `operator action required`).

## K. Errors

Every error has the same envelope:

```json
{"error": {"code": "unknown_audit", "message": "Unknown audit 'example-audit'."}}
```

| Status | Code | When |
|---|---|---|
| 400 | `invalid_slug` | The slug fails the SignalScope slug rules or path safety |
| 400 | `invalid_run_id` | A run ID is malformed or fails path safety |
| 400 | `invalid_interval` | `interval_days` is missing, repeated, or not a positive whole number |
| 400 | `comparison_refused` | Missing or repeated comparison parameters, wrong direction, same run, or no shared complete questions |
| 400 | `bad_request` | Transport level: invalid Host header or an unparsable request |
| 404 | `unknown_audit` | No such audit folder |
| 404 | `unknown_snapshot` | No such snapshot |
| 404 | `not_found` | Unknown route, or an audit folder whose configuration cannot be loaded |
| 405 | `method_not_allowed` | Any method other than GET |
| 409 | `snapshot_invalid` | A snapshot in a comparison failed integrity validation |
| 500 | `internal_error` | Unexpected failure (fixed message, no details) |

## L. Empty States

| Situation | What the API returns |
|---|---|
| No snapshots | `/snapshots` → `snapshots: []`; `latest_snapshot: null`; `snapshot_count: 0` |
| Fresh current run | `state: "fresh"`, `metrics: null`, `findings: []`, every question in state A |
| Partial current run | `state: "in progress / partial"`; metrics and findings from the rows present |
| Invalid latest snapshot | Reported as the latest with `valid: false` (no fallback); its detail has `metrics: null`, `findings: []` |
| No comparison available | Comparisons need two existing snapshots: `404 unknown_snapshot`, `409 snapshot_invalid`, `400 comparison_refused` or `comparable: false` |
| Zero-row dataset | `metrics: null`, `findings: []` |
| No monitoring interval supplied | `400 invalid_interval` (there is no stored default) |

## Version Provenance

Snapshots created with SignalScope v2.6.0 record `signalscope_version: "2.6.0"` in their
manifest. Comparing a v2.6.0 snapshot with one created under an earlier version (for
example 2.5.0) returns the existing neutral SignalScope-version warning in
`warnings.signalscope_version`. This is expected provenance behaviour, not an error.
