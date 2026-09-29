<div align="center">

# 📡 SignalScope AI

### Evidence-Driven Generative Engine Optimisation (GEO) Intelligence Platform

**Measure AI Visibility • Generate Explainable Insights • Prioritise Optimisation • Measure Improvement**

![Version](https://img.shields.io/badge/version-v2.6.0-blue)
![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-863-brightgreen)
![Architecture](https://img.shields.io/badge/architecture-modular-orange)
![Status](https://img.shields.io/badge/status-complete-success)

---

SignalScope AI is an evidence-first GEO intelligence platform that helps organisations understand how Large Language Models (LLMs) such as Google Gemini, ChatGPT and Perplexity represent their brand during AI-powered search experiences.

Instead of attempting to automatically optimise websites, SignalScope AI measures AI visibility, analyses evidence, generates explainable optimisation recommendations and measures improvement over time.

**Version:** 2.6.0

</div>

---

# Table of Contents

- Executive Summary
- Why SignalScope AI Exists
- Product Overview
- Project Highlights
- Quick Start
- Streamlit Dashboard
- Creating a New Audit
- Collecting Structured Evidence
- Audit History and Comparison
- Recurring Monitoring
- SignalScope AI v2.6 — Read-Only Local API
- Architecture Overview
- Technology Stack
- Repository Structure
- End-to-End Workflow
- Core Engines
  - Audit Engine
  - Insights Engine
  - Recommendation Engine
  - Measurement Engine
- Reporting
- Testing
- Example Outputs
- Engineering Philosophy
- AI Design Principles
- Key Design Decisions
- Current Limitations
- Future Roadmap
- Portfolio Value
- Lessons Learned
- About the Author
- Acknowledgements
- License

---

# Executive Summary

Generative AI is changing how customers discover products, services and organisations.

Instead of browsing multiple websites through a traditional search engine, users increasingly ask conversational AI systems questions such as:

> Which CRM should we buy?

> What is the best accounting software for small businesses?

> Which cybersecurity company should we choose?

Large Language Models now synthesise information from many sources and generate a single conversational answer.

For organisations this introduces an entirely new optimisation challenge.

Unlike traditional Search Engine Optimisation (SEO), there is currently very little visibility into:

- whether AI mentions a brand,
- which competitors dominate AI answers,
- why competitors are recommended,
- which sources influence AI responses,
- and whether optimisation efforts improve AI visibility.

SignalScope AI was created to answer these questions through an evidence-driven Generative Engine Optimisation (GEO) workflow.

The platform combines deterministic software engineering with explainable AI reasoning to transform AI-generated responses into structured business intelligence.

Rather than acting as an autonomous optimisation tool, SignalScope AI functions as an intelligence platform that supports consultants, marketers and business leaders in making evidence-based GEO decisions.

---

# Why SignalScope AI Exists

Traditional SEO tools were built to analyse search engine result pages.

They answer questions such as:

- What keywords rank highest?
- Which backlinks exist?
- Which pages receive traffic?

Generative AI changes this model.

Large Language Models no longer present a list of links.

Instead, they generate a single answer that synthesises knowledge from multiple sources.

This creates several strategic questions that existing SEO platforms cannot fully answer:

- Does AI recognise our brand?
- How often are competitors recommended instead?
- Which websites influence AI recommendations?
- Which buyer questions expose weaknesses in our visibility?
- Are our GEO improvements actually working?

SignalScope AI was designed to provide transparent, repeatable answers to these questions.

The platform follows one core principle throughout its architecture:

> **Evidence before interpretation.**

Every recommendation produced by the system can be traced back to measurable audit evidence.

---

# Product Overview

SignalScope AI is built around a modular four-engine architecture.

Each engine performs one clearly defined responsibility.

```text
Website / Brand
        │
        ▼
Audit Engine
        │
        ▼
Insights Engine
        │
        ▼
Recommendation Engine
        │
        ▼
Organisation Implements Changes
        │
        ▼
Measurement Engine
```

This separation improves:

- maintainability,
- explainability,
- testing,
- scalability,
- and future extensibility.

Rather than allowing AI to perform every task, deterministic Python logic is used wherever objective calculations are required.

Artificial Intelligence is reserved for tasks that genuinely benefit from reasoning and interpretation.

---

# Project Highlights

## Business Capabilities

- Evidence-driven GEO audits
- AI visibility analysis
- Competitor intelligence
- Authority source analysis
- Explainable recommendations
- Progress measurement
- Human-readable reports

## Engineering Highlights

- Modular architecture
- Four independent processing engines
- 863 automated tests
- Deterministic analytics
- Explainable AI workflow
- Structured Markdown reporting
- Git versioned development

---

# Quick Start

Clone the repository.

```bash
git clone https://github.com/rangoorajan-rgb/SignalScope-AI.git

cd SignalScope-AI
```

Create a virtual environment.

```bash
python -m venv .venv
```

Activate the environment.

Windows

```bash
.venv\Scripts\activate
```

Linux / macOS

```bash
source .venv/bin/activate
```

Install dependencies.

```bash
pip install -r requirements.txt
```

Configure your environment.

Create a `.env` file.

```text
GEMINI_API_KEY=your_api_key_here
```

Run the complete workflow.

```bash
python src/run_end_to_end_demo.py
```

Every command-line entry point runs the default Boots UK demonstration audit unless another audit is selected with `--audit SLUG` (see [Audit Configuration](#audit-configuration)).

```bash
python src/report_generator.py --audit boots-uk-health-beauty
```

To set up an audit for another company, see [Creating a New Audit](#creating-a-new-audit), then [Collecting Structured Evidence](#collecting-structured-evidence).

Run all automated tests.

```bash
python -m unittest discover -s tests -v
```

---

# Streamlit Dashboard

SignalScope AI includes a read-only Streamlit dashboard that presents existing GEO audit data and generated reports through a simple browser interface.

The dashboard provides:

- Current project details
- Total AI responses analysed
- Brand citation metrics
- Competitor citation metrics
- Source citation metrics
- Structured audit evidence
- Selectable report views
- Markdown report downloads
- Project architecture overview

The dashboard is intentionally read-only. It does not modify audit data, execute new audits or regenerate reports. It only reads and displays the CSV audit results and Markdown reports that the four engines have already generated.

The dashboard displays the default audit only. Its project metadata and file locations come from that audit's `audit_config.json`; there is no client selector yet.

The dashboard shows the **current run only**. It has no snapshot selector, history browser or comparison view; audit history is managed from the command line (see [Audit History and Comparison](#audit-history-and-comparison)). After `audit_history.py new-run`, the dashboard may appear empty or show no current audit evidence until the structured batch collects the fresh run; this is expected, and the previous run remains preserved in its snapshot. The dashboard has no schedule, monitoring-history or lock controls; recurring monitoring is driven from the command line by an external scheduler (see [Recurring Monitoring](#recurring-monitoring)).

## Project Scope

The bundled demonstration engagement is **Boots UK**, in the Health & Beauty Retail category, within the United Kingdom market, benchmarked against Superdrug, Amazon and Holland & Barrett. It remains the default audit for every command and for the dashboard.

Since v2.1, SignalScope AI provides a **multi-company audit foundation**: the Audit, Insights, Recommendation and Measurement Engines are no longer tied to one company and can run any audit that has its own configuration file. Since v2.2, an operator can create a new client audit workspace with one command (see [Creating a New Audit](#creating-a-new-audit)), and since v2.3 collect structured evidence for all of its questions with one resumable command (see [Collecting Structured Evidence](#collecting-structured-evidence)). Since v2.4, a completed run can be preserved as an immutable snapshot, a fresh run collected later, and two preserved runs compared (see [Audit History and Comparison](#audit-history-and-comparison)). Since v2.5, that lifecycle can recur unattended: an external scheduler runs one safe monitoring cycle at a time (see [Recurring Monitoring](#recurring-monitoring)). Since v2.6, a local read-only JSON API lets a separate local tool inspect audits, runs, snapshots and comparisons without changing anything (see [Read-Only Local API](#signalscope-ai-v26--read-only-local-api)).

SignalScope AI remains an **operator-assisted audit system, not a SaaS product**. It has no built-in scheduler (recurring monitoring is triggered externally), no persistent database, no authentication or user accounts, no billing, no client self-service, no client selector and no history view in the dashboard.

## Audit Configuration

Each audit lives in its own folder, identified by a slug, and is described by an `audit_config.json` file:

```text
audits/<slug>/audit_config.json      # client and scope values
audits/<slug>/buyer_questions.csv    # the audit's question set
audits/<slug>/audit_results.csv      # structured audit evidence
reports/<slug>/                      # generated Markdown reports
```

```json
{
  "slug": "boots-uk-health-beauty",
  "brand": "Boots",
  "company_name": "Boots UK",
  "report_subject": "Boots UK Health & Beauty",
  "market": "United Kingdom",
  "category": "Health & Beauty Retail",
  "competitors": ["Superdrug", "Amazon", "Holland & Barrett"],
  "question_library": "UK Retail GEO Library"
}
```

- `brand` is the name the Audit Engine looks for in AI answers; `company_name` is the display name; `report_subject` is the report title suffix. They are deliberately separate fields.
- `competitors` order is significant: it maps to `[COMPETITOR_1]`, `[COMPETITOR_2]`, … in the question library.
- The file is validated strictly by [src/audit_config.py](src/audit_config.py): missing, unexpected, empty or wrongly typed fields, a slug that does not match its folder, and malformed JSON are all rejected with a clear error.

Select an audit on any command-line entry point with `--audit SLUG`. Omitting it runs the default Boots audit exactly as before, and explicit file-path arguments still override the selected audit's default paths:

```bash
python src/report_generator.py --audit <slug>
python src/run_structured_batch_audit.py --audit <slug> --limit 5
python src/measurement_engine.py <baseline.csv> <followup.csv> --audit <slug>
```

New audits are created with `src/create_audit.py` rather than by hand (see [Creating a New Audit](#creating-a-new-audit)).

The root-level `config.py` is kept only as a backwards-compatible shim that re-exposes the default audit's values; edit an audit's `audit_config.json` instead.

## Run the Dashboard

```bash
python -m streamlit run streamlit_app.py
```

The dashboard opens in your browser and reads directly from the existing `audits/` and `reports/` directories — running it does not trigger a new audit.

---

# Creating a New Audit

Since v2.2, an operator creates a complete, immediately usable audit workspace for a new client with one command, run from the repository root:

```bash
python src/create_audit.py \
  --slug acme-uk-garden \
  --brand "Acme" \
  --company-name "Acme Ltd" \
  --report-subject "Acme Ltd Garden Supplies" \
  --market "United Kingdom" \
  --category "Garden Supplies Retail" \
  --competitor "Competitor One" \
  --competitor "Competitor Two" \
  --competitor "Competitor Three" \
  --question-library "Standard GEO Buyer Question Library"
```

All eight values are required and are never derived from one another:

| Option | Meaning |
|---|---|
| `--slug` | Audit folder name: lowercase letters, digits and single hyphens |
| `--brand` | The name the Audit Engine looks for in AI answers |
| `--company-name` | Display name |
| `--report-subject` | Report title subject |
| `--market` | Geographic or language market |
| `--category` | Category the brand competes in |
| `--competitor` | Given **exactly three times**; the order maps to `[COMPETITOR_1]`–`[COMPETITOR_3]` |
| `--question-library` | Question library display name |

Add `--dry-run` to run every check and show what would be created without writing anything.

The command creates exactly:

```text
audits/<slug>/
  audit_config.json     # the eight values above
  buyer_questions.csv   # generated from questions/buyer_questions_master.csv
  audit_results.csv     # header only, no results yet
```

- **Questions are generated deterministically.** The six placeholders in the master template are replaced with the supplied values; question IDs, buyer journey stages and order are unchanged, and no LLM is involved. The master template is never modified. See [docs/QUESTION_GENERATION_GUIDE.md](docs/QUESTION_GENERATION_GUIDE.md) for the human review that should follow.
- **Input is validated strictly** before anything is written: blank values, surrounding whitespace, line breaks, control characters and square brackets are rejected, competitors must be distinct, and the brand must not also be a competitor.
- **Existing audits are never overwritten.** If `audits/<slug>/` or `reports/<slug>/` already exists, the command refuses. There is no `--force` option.
- **Creation is all-or-nothing.** Files are written to a temporary staging folder, checked with the same loaders the rest of SignalScope AI uses, and then moved into place in one step. If anything fails, no partial audit is left behind.
- **Report folders are created later**, when reports are first generated for the audit.
- **Client data stays out of Git.** `.gitignore` ignores every folder under `audits/` and `reports/` except the Boots UK demonstration audit, which remains tracked.

The new audit can be used immediately with the existing `--audit` workflow:

```bash
python src/audit_runner.py --audit acme-uk-garden
python src/run_structured_batch_audit.py --audit acme-uk-garden --limit 1
```

Creating the workspace does not collect any evidence. Review the generated `buyer_questions.csv` (see [docs/QUESTION_GENERATION_GUIDE.md](docs/QUESTION_GENERATION_GUIDE.md)), then collect evidence as described in [Collecting Structured Evidence](#collecting-structured-evidence).

---

# Collecting Structured Evidence

Since v2.3, one command collects complete structured evidence for an audit's buyer questions, run from the repository root:

```bash
python src/run_structured_batch_audit.py --audit acme-uk-garden
```

For each question that still needs evidence, in `buyer_questions.csv` order, it:

1. asks Gemini the question;
2. saves Gemini's **complete answer** as a raw evidence file;
3. analyses that saved answer with the existing structural analysis (brand citation, position, competitors, sources, sentiment);
4. saves one structurally complete row to `audit_results.csv` before moving to the next question.

| Option | Meaning |
|---|---|
| `--audit SLUG` | The audit to work on (default: the Boots UK demonstration audit) |
| `--limit N` | Attempt at most N questions that still need work (default: all) |
| `--delay S` | Seconds to wait between questions (default: 5) |
| `--questions PATH` | Use a different question file than the audit's own |
| `--results PATH` | Use a different results file; raw evidence is then stored beside it |

A cautious way to start a new audit (guidance, not a requirement):

```bash
python src/run_structured_batch_audit.py --audit acme-uk-garden --limit 1   # check one question end to end
python src/run_structured_batch_audit.py --audit acme-uk-garden --limit 5   # a small batch
python src/run_structured_batch_audit.py --audit acme-uk-garden             # all remaining questions
```

**Resuming is automatic.** Each run skips questions that are already complete and continues with the next one. A question whose answer was saved but not yet analysed (for example after an analysis error or an interruption) is completed from the saved answer, without asking Gemini again. Re-running a finished audit makes no Gemini calls and changes no files.

**Cost.** A new question takes about two Gemini calls (the answer, then its analysis); a question completed from a saved answer takes about one. Temporary API errors are retried, which can add calls. The run prints how many questions need work before it starts, so `--limit` can be used to control how many calls a run makes.

**Failures.** If a question fails (an API error after retries, or an analysis Gemini returns in an unusable form), it is reported, no row is saved for it, and the run continues with later questions; any answer already saved is kept for the next run. If saving itself fails, or a results or evidence file changes unexpectedly, the run stops immediately so nothing is corrupted; everything saved before that point is kept. The command exits with status 1 if any question failed or needs investigation, and 0 otherwise.

When evidence collection is finished, run the existing reports (for example `python src/report_generator.py --audit acme-uk-garden` and `python src/geo_findings_analyzer.py --audit acme-uk-garden`). Reports state whether structured Gemini results exist for the complete question library.

## Raw Evidence Files

Every new Gemini answer is saved in full, before it is analysed, in:

```text
audits/<slug>/raw_responses/<question_id>__gemini.json
```

| Field | Content |
|---|---|
| `format_version` | `1` |
| `audit_slug` | The audit the answer belongs to |
| `question_id`, `question` | The question, exactly as sent to Gemini |
| `engine` | `Gemini` |
| `requested_model` | The model SignalScope asked for (for example `gemini-2.5-flash`). It does **not** prove which exact model version answered |
| `run_date` | The date the answer was collected |
| `raw_response_text` | The complete, unedited answer |

`audit_results.csv` holds the structured evidence, with a normalised 500-character `answer_snippet` of each answer; the raw evidence file holds the complete answer for traceability. Reports read only `audit_results.csv`. A saved raw answer shows what Gemini said; it does not make that answer factually correct.

Raw evidence files are never overwritten. A malformed or conflicting file is reported and left untouched for the operator to investigate; there is no automatic repair.

**Raw AI responses are not committed to Git.** `.gitignore` ignores every `raw_responses/` folder under `audits/` at any depth (including those inside snapshots, and the Boots demonstration audit's, whose other files remain tracked), and client audit folders are ignored entirely.

## Existing Results

- **Rows collected before v2.3 are never rewritten.** A Gemini row that is missing its structured fields (for example from the legacy `run_batch_audit.py`) is reported as legacy incomplete and left alone: its 500-character snippet is not analysed, and a new answer is not requested in its place. The Boots demonstration audit's PA01–PA03 rows are like this.
- A complete Gemini row without a raw evidence file (such as the Boots PA04 and PA05 rows) remains a valid historical result and is not regenerated just to create one.
- Perplexity rows are ignored by the structured batch.

## Legacy Answers-Only Runner

`src/run_batch_audit.py` is kept for backwards compatibility. It saves only a 500-character snippet of each answer, leaves the structured fields blank, and stores no raw evidence. **Use `run_structured_batch_audit.py` for all new evidence collection;** a row created by the legacy runner is treated as legacy incomplete and is not completed later.

---

# Audit History and Comparison

Since v2.4, an audit keeps a history of its runs. A finished run is preserved as an immutable **snapshot**, the current files are then reset for a **new run**, and two snapshots of the same audit can be **compared** to measure change. All history commands live in [src/audit_history.py](src/audit_history.py) and are run from the repository root. None of them calls Gemini; only the structured batch does.

## Workflow

```bash
# 1. Create the audit workspace
python src/create_audit.py --slug acme-uk-garden ...

# 2. Review audits/acme-uk-garden/buyer_questions.csv

# 3. Collect structured evidence (start small, then run the rest)
python src/run_structured_batch_audit.py --audit acme-uk-garden --limit 1
python src/run_structured_batch_audit.py --audit acme-uk-garden --limit 5
python src/run_structured_batch_audit.py --audit acme-uk-garden

# 4. Preserve the current run
python src/audit_history.py snapshot --audit acme-uk-garden
#    (a deliberately incomplete run: add --allow-partial)

# 5. Inspect the history
python src/audit_history.py list --audit acme-uk-garden

# 6. Start a fresh collection cycle (only after step 4)
python src/audit_history.py new-run --audit acme-uk-garden

# 7. Collect the later run with the same structured batch (step 3)
# 8. Snapshot the later run (step 4)

# 9. Compare two preserved runs
python src/audit_history.py compare \
  --audit acme-uk-garden \
  --from-run <EARLIER_RUN_ID> \
  --to-run <LATER_RUN_ID>
```

> **Snapshot must come before new-run.** `new-run` is not an archive command: it clears the current results and evidence, and it refuses to run unless the latest snapshot already preserves the current run exactly.

## Snapshots

`snapshot` copies the current run into:

```text
audits/<slug>/snapshots/<run-id>/
  snapshot_manifest.json
  audit_config.json          # the configuration used for this run
  buyer_questions.csv        # the question set used for this run
  audit_results.csv          # the structured results
  raw_responses/             # the full raw answers, if the run has any
  reports/audit_report.md    # rendered from this snapshot's own copies
  reports/GEO_FINDINGS.md
```

- **Run ID.** `YYYYMMDDTHHMMSSZ`, the UTC time the snapshot was created (for example `20261001T090000Z`). It sorts chronologically and is safe as a folder name on Windows. Two snapshots cannot share a run ID.
- **Self-contained.** The config, questions, results and evidence are byte-for-byte copies, so a historical run stays interpretable even if the audit's current files change later.
- **Frozen reports.** The audit report and GEO findings are rendered once, from the snapshot's own copies, to record the deterministic reports for that run. A later SignalScope version may word reports differently; the preserved source evidence is what keeps the run interpretable. Recommendations are **not** part of a snapshot.
- **Immutable once published.** A snapshot is built in a staging folder, checked, and published with a single rename, so either the complete snapshot exists or nothing does. SignalScope never writes into, overwrites, repairs or deletes a published snapshot. There is no `--force`, no repair and no pruning.
- **Complete or partial.** A run is *complete* when every buyer question has a structurally complete Gemini result, and *partial* otherwise. `snapshot` refuses a partial run unless `--allow-partial` is given, so an incomplete run is only preserved deliberately. A stored raw answer that was never successfully analysed, and a legacy incomplete row, do not count as structurally complete. Evidence integrity problems (for example a raw answer that disagrees with its results row) always block a snapshot, with or without `--allow-partial`. A run with no structurally complete result, or one already preserved, is refused.

### Snapshot Manifest

| Field | Meaning |
|---|---|
| `format_version` | Manifest format (`1`) |
| `audit_slug` | The audit the snapshot belongs to |
| `run_id` | The run ID; must match the folder name |
| `created_at` | The same instant as ISO-8601 UTC (`2026-10-01T09:00:00Z`) |
| `signalscope_version` | The SignalScope version recorded when the snapshot was created (see below) |
| `status` | `complete` or `partial` |
| `question_count` | Number of buyer questions in the snapshot |
| `structurally_complete_count` | Number of questions with a structurally complete Gemini result |
| `requested_models` | Sorted, distinct Gemini models requested for the preserved raw answers (`[]` when the run has none) |
| `files` | SHA-256 hash of every other file in the snapshot |

### Integrity Verification

Every snapshot is validated whenever it is read: each file's SHA-256 hash must match the manifest, no undeclared file may be present, every manifest field must be well formed, and the coverage counts and `requested_models` are **recomputed** from the snapshot's own files and must match. A snapshot that fails any check is reported as invalid by `list` and cannot be used by `new-run` or `compare`.

This is tamper **detection**, not tamper prevention: the hashes are not a digital signature, and anyone with file access can still change a snapshot — the change is detected, not blocked.

- `requested_models` is derived from the preserved raw evidence, so a manifest that disagrees with the evidence makes the snapshot invalid. It records the model SignalScope *asked for*, not proof of the exact model version that answered.
- `signalscope_version` is recorded provenance metadata only. It identifies the version recorded at creation time; it is not cryptographic proof and cannot be recomputed from historical code.

## Listing History and Current-Run States

`list` shows every snapshot (run ID, creation time, status, coverage, models, version and integrity result) and the state of the current run. It is read-only and exits with status 1 if any snapshot is invalid. The current-run state is derived from the files themselves; there is no active-run manifest:

| State | Meaning |
|---|---|
| fresh | No result rows (of any engine) and no raw evidence |
| in progress / partial | Results or evidence exist, but not every question is structurally complete; not snapshotted |
| complete | Every question is structurally complete; not yet snapshotted |
| snapshotted | Identical to the latest snapshot, which is valid |
| reset interrupted | A `new-run` was interrupted; run `new-run` again to finish it |

## Starting a New Run

```bash
python src/audit_history.py new-run --audit <slug>
```

`new-run` proceeds only when the latest snapshot is valid and the current run matches it exactly (config, questions, results and every raw evidence file). It never falls back to an older snapshot, and it refuses if the current run has changed since the snapshot ("snapshot the current run first") or is already fresh. On success:

- `audit_config.json` and `buyer_questions.csv` are kept unchanged;
- `audit_results.csv` is reset to the valid header-only 11-column file;
- the current `raw_responses/` folder is removed (its contents remain in the snapshot);
- the snapshot is not touched;
- the structured batch sees every question as not started, and the next collection asks Gemini again.

**Interrupted resets are recoverable.** The evidence is first moved into a hidden `snapshots/.retired-raw-<run-id>-*` folder, then the results are reset, then the retired evidence is verified against the snapshot and deleted. If this is interrupted, `list` shows *reset interrupted* and `snapshot` refuses; running `new-run` again verifies the retired evidence against the snapshot and finishes the reset. At every point the snapshot holds the complete previous run. Do not delete a retirement folder by hand.

## Comparing Two Runs

```bash
python src/audit_history.py compare --audit <slug> --from-run <EARLIER_RUN_ID> --to-run <LATER_RUN_ID>
```

The comparison is directional: `--from-run` must be earlier than `--to-run`, and the two must differ. The runs are never swapped silently. Both snapshots must pass full validation, and only their own copies are read — never the current run.

**Comparability.** Two snapshots are compared only when their own configs have the same audit slug, brand, market, category and **ordered** competitor list, and their question files have the same ordered sequence of `question_id`, `buyer_journey_stage` and question text. Display-only fields (company name, report subject, question-library name) and question intent or notes may differ. If a question was added, removed, reordered, reworded or moved to another stage, or a core config value changed, the comparison is refused with a list of the differences. SignalScope does not normalise or partially compare changed methodologies.

**Shared-question rule.** Metrics use only Gemini questions that are structurally complete in **both** runs, and exactly the same question IDs on both sides. Perplexity and other manually entered rows, and incomplete Gemini rows, are excluded. Each run's own coverage is shown separately. For example:

```text
From run: 40 / 40 structurally complete     To run: 30 / 40 structurally complete
Comparison universe: the 30 questions complete in both runs
Metrics: those 30 vs the same 30 (not 40 vs 30)
```

This prevents a change caused only by missing evidence from looking like a change in visibility. Unequal coverage is allowed and both runs may be partial, but at least one shared structurally complete question is required; with none, the comparison is refused.

**Metrics.** The comparison reuses the existing Measurement Engine metrics unchanged: Brand Visibility, Brand Mention Frequency, Competitor Mention Change, Positive Sentiment Rate, Authority Source Change, Funnel Stage Coverage and GEO Maturity. No composite score is calculated.

**GEO Maturity caveat.** In a comparison, GEO Maturity is evaluated over the shared question set only (the question total given to the Measurement Engine is the shared count). Its coverage requirement is therefore always met, and the tier reflects brand visibility on the shared questions. When either run is partial, the comparison's tier is not that run's maturity over its full question library; each run's actual coverage is shown separately in the report.

**Warnings.** If the two snapshots record different requested model sets, or different SignalScope versions, the comparison still runs and the report shows a neutral warning. These warnings do not mean the difference caused any metric change, and they do not make the results invalid.

**Output.** The report is written to:

```text
reports/<slug>/comparisons/<from-run>__<to-run>/GEO_PROGRESS.md
```

It is a derived report, not part of either snapshot: re-running the same pair regenerates and replaces it, and the snapshots are never modified. In the report, *Before* is the from run and *After* is the to run; a Run Comparison section names both runs, each run's coverage, the number of shared questions used and any warnings. Nothing is written if any check fails.

## Operator Safety

- Run only **one write operation per audit at a time**: never run the structured batch, `snapshot` or `new-run` concurrently for the same audit. The commands re-check their inputs and stop rather than corrupt data, but concurrent use is not supported.
- `list` and `compare` are read-only with respect to the audit, but avoid editing an audit's files while other commands for it are running.
- `snapshot`, `list`, `new-run` and `compare` make no Gemini calls. Only the structured batch calls Gemini.
- While a recurring monitoring cycle is working on an audit, do not run these write commands against it (see [Manual Commands Alongside Monitoring](#manual-commands-alongside-monitoring)).

## Upgrading from v2.3

No migration is required. An existing v2.3 workspace (`audit_config.json`, `buyer_questions.csv`, `audit_results.csv` and any `raw_responses/`) simply becomes the current, unsnapshotted run. The first `snapshot` creates the `snapshots/` folder; nothing existing is rewritten. Rows without raw evidence (such as the Boots demonstration rows) can be preserved with `--allow-partial` and record `requested_models: []`.

The legacy `run_batch_audit.py` saves only answer snippets, leaves the structured fields blank and stores no raw evidence, so it should not be used to collect runs for history; use `run_structured_batch_audit.py`.

## Git and Confidentiality

Client audit folders are ignored entirely. Within any audit (including the Boots demonstration audit), `raw_responses/` folders at any depth, `snapshots/` folders and `reports/<slug>/comparisons/` are ignored, so full raw answers, snapshots and comparisons are never committed. Since v2.5 the `.monitoring.lock` file is ignored for every audit as well. The Boots demonstration audit's top-level data and reports remain tracked.

---

# Recurring Monitoring

Since v2.5, the v2.4 lifecycle (new run → collect → snapshot → compare) can repeat unattended. [src/run_monitoring_cycle.py](src/run_monitoring_cycle.py) runs **at most one monitoring cycle per invocation**, and an external scheduler decides when to invoke it. It reuses the existing structured batch, snapshot, new-run and comparison functions; it does not reimplement any of them.

## Service Workflow

```text
Manual baseline (once):
  create audit → review questions → collect baseline → snapshot baseline

Recurring monitoring (every trigger):
  external trigger → planner → per-audit lock → due check
    → new-run when due → structured collection / resume
    → complete snapshot → previous snapshot → new snapshot comparison
    → completed; nothing more happens until the next interval is due
```

Each completed cycle leaves a new historical snapshot and one `GEO_PROGRESS.md` comparing it with the previous snapshot.

| SignalScope owns | The external scheduler owns |
|---|---|
| State validation and evidence integrity | When the command is invoked |
| Overlap protection (per-audit lock) | The local clock and calendar |
| Collection orchestration and spend protection | Machine uptime and missed-run behaviour |
| Snapshot and comparison safety | The environment and credentials of the scheduled user |
| A machine-readable outcome (exit code and JSON summary) | |

## The Command

```bash
python src/run_monitoring_cycle.py --audit <slug> --interval-days 30
python src/run_monitoring_cycle.py --audit <slug> --interval-days 30 --dry-run
```

- `--interval-days` is required and must be a positive whole number.
- A new cycle is **due** when the time since the latest snapshot's run ID (its UTC creation time) is at least `--interval-days` days. This is a plain UTC duration; there is no calendar or time-zone logic.
- One invocation performs at most one cycle. There is no internal scheduler, daemon or background service.

**Dry run.** `--dry-run` inspects the current run and its snapshots and reports: the current-run state, evidence integrity, the latest and previous snapshots, whether a cycle is due, the methodology check, whether collection would be needed and — only then — whether a Gemini API key is configured, whether another process holds the monitoring lock, the planned actions and the exit code a real run would start with. It makes no Gemini call, writes no file, does not create the lock file and does not change the audit. It checks only that a key is *present*; it never validates the key with Gemini.

## Before Enabling Monitoring: the Manual Baseline

> **Recurring monitoring does not create the first baseline.** Before scheduling an audit, the operator must create the audit, review its question library, collect the baseline with the structured batch and snapshot it (see [Audit History and Comparison](#audit-history-and-comparison)).

Without a valid snapshot the command exits with *operator action required* and makes no Gemini call. The baseline is the reference for every later comparison, so its questions and results are reviewed and accepted by a person.

## What One Invocation Does

The command takes the audit's lock, plans from the files themselves (there is no cycle-state file), and takes the one safe next action:

| Situation | Action |
|---|---|
| Evidence integrity problem, no baseline, or invalid latest snapshot | Stop: operator action (no Gemini call) |
| Latest snapshot younger than `--interval-days`, comparison present | Nothing: *not due* |
| Due (latest snapshot is the current run) | new-run → collect → snapshot → compare |
| Fresh or in-progress current run | Collect / resume → snapshot → compare |
| Interrupted new-run | Finish it (v2.4 recovery) → collect → snapshot → compare |
| Complete run not yet snapshotted | Snapshot → compare (no Gemini call) |
| Snapshot present, its comparison missing | Compare only (no Gemini call) |

**Collection.** Collection uses the released structured batch (`run_structured_batch_audit`), called with absolute paths in chunks of **5** questions. Completed questions are skipped; a question whose answer is stored but not yet analysed is analysed from the stored answer without a new answer call. An interrupted or incomplete run is resumed by the next invocation.

**Spend circuit breaker.** After each chunk SignalScope checks whether the run made progress (more questions structurally complete, or fewer not yet started). If a chunk records failures and makes no progress, the cycle stops instead of working through the rest of the question library. There is no whole-cycle retry and no additional retry schedule; the batch's own per-question retries (temporary 429/5xx errors) remain authoritative. If a chunk makes no progress and all of its failures are temporary API errors, the cycle ends as *incomplete* (exit 4) and a later trigger resumes it; any other failure, such as an authentication error, needs the operator (exit 1).

**Known limitation.** Because the batch always starts from the earliest collectable questions, a question that keeps failing is attempted again in later chunks of the same cycle while other questions continue to progress. Spend stays bounded by the chunking and the batch's retry limits, completed questions are never repeated and evidence integrity is not affected; changing this would require redesigning the collector. This is accepted for v2.5.

**Partial runs.** Automation never snapshots a partial run. If collectable questions remain, the cycle exits 4 and the next trigger resumes them. If nothing more can be collected automatically (for example a legacy incomplete row), it exits 1 and the operator decides whether to preserve the run with `python src/audit_history.py snapshot --audit <slug> --allow-partial`; the next invocation then compares that snapshot using the v2.4 shared-question and coverage rules.

**Snapshots.** A snapshot is created automatically only when every question is structurally complete, using the v2.4 `create_snapshot` with `allow_partial=False`. All v2.4 snapshot gates, hashes and duplicate protection apply unchanged.

**Comparisons.** Each completed cycle compares the **immediately previous snapshot → the new snapshot** with the v2.4 comparison, writing `reports/<slug>/comparisons/<previous>__<new>/GEO_PROGRESS.md`. There is one automatic comparison per cycle, always in that direction; the first baseline is not automatically compared with every later run. An existing comparison is not regenerated. Other comparisons can still be made manually with `audit_history.py compare`.

**Methodology guard.** Before any collection, the current `audit_config.json` and `buyer_questions.csv` are checked against the latest snapshot with the same comparability rules as the v2.4 comparison. An incompatible change stops the cycle before any Gemini call; display-only changes that v2.4 allows are allowed.

**Re-baselining.** If the operator deliberately snapshots a run under changed core methodology, that newer snapshot becomes the new monitoring baseline and nothing is compared across the break. For example, with A (old methodology), B (a manual re-baseline under the new methodology) and C (the next recurring run), the automatic comparison is B → C only — never A → B or A → C, and there is no fallback to an older compatible snapshot. The cadence is measured from B.

**Comparison failures.** If a comparison is refused (for example zero shared structurally complete questions) or cannot be written after a new snapshot was published, the snapshot is kept — nothing is rolled back — and the cycle exits 1. The next invocation retries the comparison only; it never starts a new collection because a comparison failed. The snapshot is preserved evidence; the comparison is derived output.

**API key.** A Gemini key is checked only when collection is actually needed, and for a due cycle it is checked *before* new-run changes the current run. No key is needed to decide that a cycle is not due, to inspect history, to snapshot an already complete run, or to create a comparison. Key presence does not prove the key is valid.

**Recommendations.** Recurring monitoring does not run the Recommendation Engine: recommendations add LLM calls and variability, while the monitoring core is evidence and measurement. The manual recommendation workflow is unchanged.

## Crash and Resume

Every step is re-derived from the files on the next invocation, so no cycle-state file is needed:

| Interrupted after | Next invocation |
|---|---|
| new-run, before collection | Sees a fresh run and collects it |
| 17 of 40 questions | Collects only the remaining questions |
| An answer was stored but not analysed | Analyses the stored answer (no new answer call) |
| Complete collection, before the snapshot | Snapshots it without collecting again |
| The snapshot, before the comparison | Compares only: no Gemini call, no new-run, no duplicate snapshot |

## Exit Codes and Summary

| Code | Meaning |
|---|---|
| 0 | Success or nothing to do: not due, a comparison-only recovery, or a completed cycle |
| 1 | Operator action required or operational failure: no baseline, an evidence integrity problem, an invalid or tampered snapshot, an incompatible methodology change, no API key when collection is needed, a permanent collection failure, a comparison refusal or write failure, a partial run with nothing left to collect, or a lock that cannot be provided |
| 2 | Invalid command-line arguments |
| 3 | Another monitoring process holds this audit's lock; nothing was done |
| 4 | Collection is incomplete but recoverable; a later trigger resumes it |

The last line of output is a single JSON object for scheduler wrappers and future automation, with `audit_slug`, `mode`, `outcome`, `action`, `active_state`, `final_state`, `latest_snapshot`, `new_snapshot`, `comparison`, `requires_collection` and `exit_code` (a dry run's summary has `due`, `previous_snapshot` and `lock_held` instead of `final_state`, `new_snapshot` and `comparison`). It never contains the API key, answers or evidence.

## Per-Audit Lock

A cycle holds an operating-system lock on `audits/<slug>/.monitoring.lock` from planning to the end of the comparison (Windows: `msvcrt.locking`; Linux/macOS: `fcntl.flock`). The lock is per audit and non-blocking: if another monitoring process holds the same audit's lock, the command exits 3 and does nothing. Different audits can be monitored at the same time.

- The **lock file may remain** after a cycle; its existence does **not** mean the audit is locked. Only the operating system's lock on an open handle counts, and the operating system releases it when the process ends, including after a crash.
- The file holds diagnostic details only (`audit_slug`, `started_at`, `process_id`, `hostname`, `signalscope_version`). SignalScope never reads them to decide anything: it does not judge staleness by age or process ID, does not delete old lock files, and has no unlock command.
- The lock is designed for **local filesystems**. v2.5 provides no distributed locking, multi-host coordination, network-filesystem leases or cloud-worker coordination.

## Scheduling

v2.5 deliberately has no internal scheduler. SignalScope provides the safe one-cycle command; the deployment decides when to run it. Trigger it **daily** with `--interval-days 30`: each day the scheduler asks whether the audit is due, most invocations exit 0 as *not due* without any Gemini call, and a full audit runs only about once every 30 days. A daily trigger does not mean daily audits.

**Windows Task Scheduler** (recommended on the current operator platform):

- Trigger: daily.
- Action: program = the project's Python (for example `C:\path\to\SignalScope-AI\.venv\Scripts\python.exe`), arguments = `src\run_monitoring_cycle.py --audit <slug> --interval-days 30`, **Start in** = the repository root.
- Settings: *If the task is already running* → **Do not start a new instance**; enable **Run task as soon as possible after a scheduled start is missed** if the machine may be off at the trigger time.
- Run it as a user who can read the project and its `.env` (the Gemini key is read from the repository's `.env` or the environment).
- To keep a record, run it through `cmd /c "... >> monitoring.log 2>&1"`; `*.log` files are git-ignored.

**cron** (Linux/macOS equivalent):

```cron
0 6 * * * cd /path/to/SignalScope-AI && .venv/bin/python src/run_monitoring_cycle.py --audit <slug> --interval-days 30 >> monitoring.log 2>&1
```

cron owns the invocation time; SignalScope still owns the due check and the lock.

**Missed runs.** If the machine is off when an audit becomes due, the next invocation simply runs one due cycle. SignalScope never calculates or launches catch-up audits: an audit that became due on Monday while the machine was off until Wednesday gets one cycle on Wednesday — not Monday, Tuesday and Wednesday.

Make.com and cloud triggers are not part of v2.5; they remain future deployment and platform work.

## Manual Commands Alongside Monitoring

All manual commands remain available and unchanged: `run_structured_batch_audit.py`, `audit_history.py snapshot`, `list`, `new-run` and `compare`. They do **not** take the monitoring lock, so do not run mutating manual commands against an audit while `run_monitoring_cycle.py` is working on it. The existing integrity checks still protect stored data, but simultaneous manual work may waste Gemini calls or make one of the operations refuse.

To intervene manually:

1. Pause the scheduled task.
2. Inspect with `python src/audit_history.py list --audit <slug>` and/or `python src/run_monitoring_cycle.py --audit <slug> --interval-days 30 --dry-run`.
3. Resolve the issue with the manual commands (for example `snapshot --allow-partial`, or a new baseline).
4. Resume the scheduled task; the next invocation continues from the files.

## Monitoring Output

Recurring monitoring produces no new report type. Each cycle's output is the historical snapshot (`snapshot_manifest.json`, `audit_config.json`, `buyer_questions.csv`, `audit_results.csv`, `raw_responses/`, `reports/audit_report.md`, `reports/GEO_FINDINGS.md`) and the derived `reports/<slug>/comparisons/<previous>__<new>/GEO_PROGRESS.md`. The dashboard remains current-run only, with no schedule, monitoring-history, comparison or lock controls.

The `.monitoring.lock` file is git-ignored for every audit, including the Boots demonstration audit, and is operational state only — never audit evidence. Client audits, raw responses, snapshots and comparisons keep the v2.4 confidentiality rules.

---

# SignalScope AI v2.6 — Read-Only Local API

Since v2.6, SignalScope can serve its existing data as JSON to a separate local tool, such as a future frontend. The API is a thin, read-only layer over the same engine: every rule (validation, snapshot integrity, comparability, metrics, monitoring decisions) stays in SignalScope, and the CLI commands remain the only way to change audit state.

```bash
python src/readonly_api_server.py --port 8765
python src/readonly_api_server.py --port 8765 --allow-origin http://localhost:3000
```

It answers eight `GET` routes: health, the audit list, one audit, the current run, the snapshot history, one snapshot, a snapshot-to-snapshot comparison, and a read-only monitoring plan. The full contract — routes, fields, metric meanings, empty states and error codes — is in [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

> **Local and read-only.** The server binds only to `127.0.0.1`, accepts only `Host: 127.0.0.1:<port>` or `localhost:<port>`, answers only `GET`, and allows cross-origin browser access only for one exact origin given with `--allow-origin`. It is intended for local integration, not internet exposure: there is no authentication, database, billing or hosted service.

- **Nothing is changed.** No endpoint writes a file, resets a run, creates a snapshot, writes a comparison report, collects evidence, calls Gemini or reads the `.env` key.
- **Current run and history are kept apart.** `/current-run` describes the working files; `/snapshots` is the immutable history. Comparisons use snapshots only, and an invalid latest snapshot is reported as such rather than replaced by an older one.
- **Monitoring stays external.** The monitoring-plan endpoint only reports what a cycle would do for a given `interval_days`; the external scheduler still runs `run_monitoring_cycle.py`.
- The dashboard is unchanged, and no frontend is connected to the API yet.

---

# Architecture Overview

SignalScope AI follows a modular, pipeline-based architecture where each engine has a single responsibility. Rather than allowing one large AI model to make every decision, deterministic software performs objective analysis while AI is used only where reasoning and interpretation genuinely add value.

```text
                    ┌────────────────────┐
                    │   Website / Brand  │
                    └──────────┬─────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │   Audit Engine     │
                    │────────────────────│
                    │ Collect Evidence   │
                    │ Detect Mentions    │
                    │ Extract Sources    │
                    │ Score Visibility   │
                    └──────────┬─────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │  Insights Engine   │
                    │────────────────────│
                    │ Pattern Discovery  │
                    │ Competitor Trends  │
                    │ Opportunity Areas  │
                    └──────────┬─────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │Recommendation Engine│
                    │────────────────────│
                    │ Prioritisation     │
                    │ Business Actions   │
                    │ GEO Strategy       │
                    └──────────┬─────────┘
                               │
                               ▼
                    Organisation Implements
                           Improvements
                               │
                               ▼
                    ┌────────────────────┐
                    │ Measurement Engine │
                    │────────────────────│
                    │ Compare Audits     │
                    │ Validate Progress  │
                    │ Generate Reports   │
                    └────────────────────┘
```

This modular approach keeps each component independently testable while allowing future engines to be added without rewriting the existing architecture.

---

# Technology Stack

| Category | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| AI Model | Google Gemini |
| Dashboard | Streamlit |
| Testing | unittest |
| Reporting | Markdown |
| Version Control | Git |
| Dependency Management | pip |
| Environment Variables | Minimal built-in `.env` loader (no external dependency) |
| Architecture | Modular Pipeline |
| Development | VS Code |
| Repository | GitHub |

---

# Repository Structure

```text
SignalScope-AI/
│
├── src/
│   ├── audit_config.py              # Per-audit configuration loader and --audit parsing
│   ├── create_audit.py              # Creates a new audit workspace (operator CLI)
│   ├── audit_runner.py              # Loads and validates the buyer question library
│   ├── gemini_client.py             # Minimal Gemini API wrapper
│   ├── response_analyzer.py         # Structured extraction from a raw AI response
│   ├── write_single_audit_result.py # Shared, atomic audit-results CSV writer
│   ├── run_single_audit.py          # Single-question Gemini integration
│   ├── run_batch_audit.py           # Legacy answers-only batch runner (kept for compatibility)
│   ├── run_structured_batch_audit.py # Structured batch evidence collection (primary)
│   ├── run_structured_audit.py      # Single-question structured audit pipeline
│   ├── report_generator.py          # Insights Engine: audit_report.md
│   ├── geo_findings_analyzer.py     # Insights Engine: GEO_FINDINGS.md
│   ├── recommendation_engine.py     # Recommendation Engine: GEO_RECOMMENDATIONS.md
│   ├── measurement_engine.py        # Measurement Engine: GEO_PROGRESS.md
│   ├── audit_history.py             # Audit history: snapshot, list, new-run, compare (operator CLI)
│   ├── version.py                   # SignalScope version recorded in snapshot manifests
│   ├── run_monitoring_cycle.py      # One recurring monitoring cycle (for an external scheduler)
│   ├── readonly_api.py              # Read-only API resources (JSON-safe views of the engine)
│   ├── readonly_api_server.py       # Localhost GET-only HTTP server over readonly_api
│   ├── run_end_to_end_demo.py       # Full pipeline, single question
│   ├── check_gemini_connection.py   # Standalone Gemini connectivity check
│   └── dashboard_data.py            # Non-UI data layer for the Streamlit dashboard
│
├── tests/                           # One test module per src/ file (unittest)
│
├── audits/
│   └── boots-uk-health-beauty/      # Default demonstration audit
│       ├── audit_config.json        # Client and scope values for this audit
│       ├── buyer_questions.csv      # Placeholder-substituted question set
│       ├── audit_results.csv        # Structured audit evidence (11-column schema)
│       ├── raw_responses/           # Full Gemini answers from v2.3 runs (git-ignored)
│       ├── snapshots/<run-id>/      # Immutable preserved runs, when created (git-ignored)
│       └── .monitoring.lock         # Monitoring lock file, once monitoring has run (git-ignored)
│
├── reports/
│   └── boots-uk-health-beauty/
│       ├── audit_report.md
│       ├── GEO_FINDINGS.md
│       ├── GEO_RECOMMENDATIONS.md
│       ├── GEO_PROGRESS.md
│       └── comparisons/             # Derived run comparisons, when created (git-ignored)
│
├── questions/
│   └── buyer_questions_master.csv   # Reusable, placeholder-only question library
│
├── docs/                            # Methodology, specification and ADRs
│
├── streamlit_app.py                 # Read-only dashboard
├── config.py                        # Backwards-compatible shim over the default audit config
├── requirements.txt
├── README.md
├── CURRENT_SPRINT.md
└── .env.example
```

The repository is organised as a flat, functional pipeline: each `src/` module has a single responsibility and its own dedicated test file, making navigation straightforward as the project continues to grow.

---

# End-to-End Workflow

SignalScope AI follows an evidence-first workflow designed to mirror how a GEO consultant would analyse a brand.

## Step 1 — Audit

The Audit Engine sends carefully designed prompts to the selected Large Language Model and records the complete responses.

During this stage the platform extracts:

- Brand mentions
- Competitor mentions
- Citation sources
- Recommendation reasoning
- Response metadata
- Visibility metrics

No interpretation occurs during this stage.

The objective is simply to collect reliable evidence.

---

## Step 2 — Insights

Once evidence has been collected, the Insights Engine searches for patterns.

Instead of analysing each AI response independently, the engine looks across every response to identify recurring trends.

Typical discoveries include:

- Frequently recommended competitors
- Missing brand visibility
- Dominant authority websites
- Recurring customer questions
- Industry positioning
- Common strengths
- Common weaknesses

The objective is not merely reporting data but converting evidence into business understanding.

---

## Step 3 — Recommendations

After the evidence has been interpreted, the Recommendation Engine generates prioritised improvement opportunities.

Recommendations are grouped according to their expected business value.

Examples include:

- Improve product comparison content
- Increase authoritative citations
- Publish missing topical content
- Strengthen expertise signals
- Improve structured information
- Enhance trust indicators

Each recommendation references supporting audit evidence to maintain explainability.

The platform deliberately avoids making unsupported optimisation claims.

---

## Step 4 — Implementation

SignalScope AI intentionally stops after producing recommendations.

The platform does not automatically modify websites.

Instead, organisations implement the recommended improvements through their existing content, SEO or development teams.

This design decision keeps the platform focused on intelligence rather than automation.

---

## Step 5 — Measurement

After improvements have been implemented, a second audit can be performed.

The Measurement Engine compares the previous and current audits to identify genuine changes. Since v2.4, the earlier and later audits are two immutable snapshots of the same audit, compared with `audit_history.py compare` (see [Audit History and Comparison](#audit-history-and-comparison)). Since v2.5 this comparison is produced automatically at the end of each recurring monitoring cycle (see [Recurring Monitoring](#recurring-monitoring)).

Rather than assuming improvements occurred, every reported change must be supported by measurable evidence.

If only a single audit exists, the engine reports that historical comparison is unavailable rather than generating speculative conclusions.

This reflects one of the core engineering principles of the project:

> Never invent evidence.

---

# Core Engines

SignalScope AI consists of four independent engines that together create the complete GEO workflow.

Each engine performs a single responsibility, making the application easier to maintain, test and extend.

---

# Audit Engine

The Audit Engine forms the foundation of SignalScope AI.

Every downstream insight, recommendation and measurement depends upon the quality of the evidence collected during this stage.

For that reason, the Audit Engine deliberately performs **data collection rather than interpretation**.

Its primary responsibility is to ask structured GEO prompts, capture the complete responses generated by the selected Large Language Model and transform those responses into structured audit data.

By separating evidence collection from interpretation, the system reduces bias and ensures every subsequent conclusion can be traced back to measurable observations.

---

## Responsibilities

The Audit Engine is responsible for:

- Executing GEO prompts
- Capturing complete LLM responses
- Extracting brand mentions
- Identifying competitor mentions
- Recording authority sources
- Measuring visibility metrics
- Producing structured audit outputs

No optimisation recommendations are generated during this stage.

---

## Audit Pipeline

```text
User Input
      │
      ▼
Prompt Generation
      │
      ▼
LLM Response
      │
      ▼
Response Parsing
      │
      ▼
Evidence Extraction
      │
      ▼
Structured Audit
```

---

## Evidence Collected

Each audit records multiple categories of information.

### Brand Visibility

The engine identifies whether the audited organisation is mentioned within AI-generated responses.

Metrics include:

- Mention frequency
- Relative prominence
- Position within responses
- Overall visibility

---

### Competitor Visibility

Competitor mentions are extracted separately to allow comparative analysis.

This enables organisations to understand:

- Which competitors dominate conversations
- Which competitors appear alongside the brand
- Which competitors consistently outperform visibility

---

### Citation Sources

Where available, the engine records external sources referenced by the model.

Typical examples include:

- Official company websites
- Wikipedia
- Industry publications
- Government websites
- Documentation
- Review platforms

These sources later become an important input for recommendation generation.

---

### Response Metadata

The engine also records metadata required for later comparison, including:

- Prompt identifier
- Timestamp
- Audit identifier
- Response length
- Processing status

---

## Design Principles

The Audit Engine follows several engineering principles.

### Deterministic Extraction

Objective information is extracted using deterministic Python logic wherever possible.

This improves repeatability and makes testing significantly easier.

---

### AI Independence

The Audit Engine does not ask the language model to interpret its own answers.

Instead, it simply captures the evidence.

Interpretation occurs later inside the Insights Engine.

---

### Reproducibility

Running the same audit with identical inputs should produce consistent structured outputs, subject to the natural variability of LLM responses.

The architecture therefore separates:

- evidence collection
- evidence interpretation
- recommendation generation

into independent processing stages.

---

# Insights Engine

Once the audit has been completed, SignalScope AI begins analysing the collected evidence.

Unlike the Audit Engine, which focuses solely on recording observations, the Insights Engine searches for meaningful patterns across the complete dataset.

Its purpose is to transform raw evidence into business intelligence.

---

## Responsibilities

The Insights Engine identifies:

- recurring trends
- competitive positioning
- topical gaps
- authority patterns
- customer intent
- strategic opportunities

Rather than analysing a single response in isolation, the engine evaluates the audit as a whole.

---

## Processing Pipeline

```text
Audit Results
      │
      ▼
Evidence Aggregation
      │
      ▼
Pattern Detection
      │
      ▼
Opportunity Identification
      │
      ▼
Business Insights
```

---

## Types of Insights

### Brand Position

The engine evaluates how consistently the organisation appears across multiple AI responses.

Questions include:

- Is the brand recognised?
- Is it recommended?
- Is it mentioned only occasionally?
- Is it completely absent?

---

### Competitive Landscape

SignalScope AI identifies which competitors dominate AI-generated recommendations.

This provides valuable context for GEO strategy by highlighting organisations currently receiving the greatest visibility.

---

### Authority Analysis

The engine analyses the authority sources appearing throughout responses.

Patterns frequently emerge regarding which websites AI systems appear to trust for specific industries.

These findings often influence later recommendation generation.

---

### Content Opportunities

The engine identifies recurring questions that are not adequately answered by the audited organisation.

These represent opportunities for future GEO-focused content development.

---

### Strategic Themes

Rather than producing hundreds of disconnected observations, related findings are grouped into higher-level themes.

Examples include:

- weak authority signals
- missing educational content
- limited comparison pages
- inconsistent expertise indicators
- low brand familiarity

Grouping related findings improves readability while reducing information overload.

---

## Engineering Approach

The Insights Engine deliberately combines deterministic analytics with AI reasoning.

Objective calculations remain within Python.

Interpretative summaries are generated only after the supporting evidence has been collected.

This separation improves explainability while reducing the risk of unsupported conclusions.

---

# Recommendation Engine

The Recommendation Engine converts analytical findings into prioritised business actions.

Unlike traditional SEO tools that simply report issues, SignalScope AI explains what should be improved and why.

Every recommendation is linked to evidence generated during previous stages.

This evidence-first approach ensures recommendations remain transparent and defensible.

---

## Responsibilities

The Recommendation Engine is responsible for:

- Prioritising optimisation opportunities
- Translating analytical findings into business actions
- Grouping related recommendations
- Explaining the reasoning behind each recommendation
- Maintaining complete traceability to audit evidence

The engine intentionally avoids producing generic SEO advice.

Instead, every recommendation is derived from the specific findings of the current audit.

---

## Recommendation Pipeline

```text
Insights
     │
     ▼
Opportunity Detection
     │
     ▼
Impact Assessment
     │
     ▼
Priority Ranking
     │
     ▼
Business Recommendations
```

---

## Recommendation Categories

Recommendations are organised into logical themes to improve readability and implementation.

### Content Improvements

Examples include:

- Create missing educational content
- Expand comparison pages
- Improve topical coverage
- Address unanswered customer questions

---

### Authority Improvements

Examples include:

- Increase citations from authoritative sources
- Improve trust signals
- Publish expert-led content
- Strengthen evidence supporting expertise

---

### Brand Visibility

Examples include:

- Improve consistency of messaging
- Increase topical relevance
- Strengthen entity recognition
- Improve brand differentiation

---

### Technical Improvements

Where appropriate, the engine may recommend:

- Structured data enhancements
- Better information architecture
- Clearer product descriptions
- Improved accessibility of important content

---

## Prioritisation Strategy

Not every recommendation delivers the same business value.

SignalScope AI therefore assigns priorities based on:

- expected impact
- supporting evidence
- implementation complexity
- strategic importance

This allows organisations to focus their efforts where improvements are most likely to influence AI visibility.

---

## Explainability

Every recommendation is supported by audit findings.

Rather than producing statements such as:

> Improve authority.

SignalScope AI instead explains why the recommendation exists.

For example:

- Competitors were cited in 8 of 10 responses.
- The audited organisation appeared only twice.
- Government and industry sources dominated citations.
- No evidence of expert content was identified.

This approach improves trust while making recommendations easier to justify to stakeholders.

---

# Measurement Engine

The Measurement Engine closes the GEO improvement loop.

After recommendations have been implemented, organisations can run another audit and compare the results against previous evidence.

The objective is not simply to report differences but to determine whether meaningful progress has occurred.

---

## Responsibilities

The Measurement Engine performs:

- audit comparison
- visibility comparison
- competitor comparison
- citation comparison
- recommendation validation
- improvement reporting

---

## Measurement Workflow

```text
Previous Audit
        │
        ├────────────┐
        │            │
        ▼            ▼
Current Audit   Structural Validation
        │            │
        └──────┬─────┘
               ▼
Comparison Engine
               │
               ▼
Improvement Report
```

---

## Structural Validation

One of the defining features of Version 2 is structural validation.

Before generating comparisons, the engine verifies that sufficient historical evidence exists.

If only one audit is available, SignalScope AI reports that historical comparison cannot yet be performed.

The platform intentionally avoids manufacturing improvements where no previous evidence exists.

This behaviour reflects the project's guiding principle:

> Evidence should always take precedence over assumption.

---

## Comparison Categories

When multiple audits exist, the Measurement Engine evaluates:

### Brand Visibility

- Increased mentions
- Reduced mentions
- Stable visibility

---

### Competitor Visibility

- Competitors gaining visibility
- Competitors losing visibility
- Newly emerging competitors

---

### Authority Sources

The engine evaluates whether citation patterns have changed over time.

Examples include:

- additional authoritative sources
- reduced dependency on weaker sources
- improved diversity of citations

---

### Recommendation Progress

Recommendations generated during previous audits can be reviewed alongside current evidence.

This enables organisations to determine:

- which improvements were implemented
- which recommendations remain relevant
- where additional work is required

---

# Reporting

Every engine contributes towards producing clear, human-readable reports.

SignalScope AI deliberately favours Markdown output because it is:

- portable
- version controllable
- easy to review
- compatible with GitHub
- suitable for consultants
- suitable for business stakeholders

Reports are designed to be understandable by both technical and non-technical audiences.

---

# Testing

Software quality was treated as a first-class requirement throughout development.

Rather than relying solely on manual testing, SignalScope AI includes an extensive automated testing suite covering both individual components and complete workflows.

---

## Test Coverage

The project contains **863 automated tests**, including:

- unit tests
- integration tests
- parser tests
- engine tests
- reporting tests
- measurement validation
- regression tests

The objective is to ensure future development can occur with confidence while reducing the likelihood of introducing regressions.

v2.1 added three regression safeguards:

- **Golden-master tests** regenerate the deterministic Boots reports and require them to match the committed reports byte for byte, and pin the recommendations renderer's output.
- **Multi-client tests** run the complete workflow for a fictional company, entirely in temporary directories with Gemini mocked, and require that no Boots value leaks into its output.
- **A static guard** fails if client-specific business values are written as literals in reusable production code.

v2.2 added audit-creation tests: generating the Boots workspace from its configuration and the master template reproduces the committed Boots `audit_config.json` and `buyer_questions.csv` byte for byte, and fictional-client tests cover validation, collision refusal, rollback after injected failures, dry runs, the CLI and immediate `--audit` use.

v2.3 added structured batch tests: a full 40-question run for a fictional client with Gemini faked, complete raw evidence, resuming (including from a saved answer without a second answer call), `--limit` and `--delay`, failure and stop behaviour, interruption, protection of the historical Boots rows (run against a copy), and the create → collect → report chain, including the complete-versus-partial report wording. No test calls the Gemini API.

v2.4 added audit history tests: complete and partial snapshots, SHA-256 tamper detection, verification of recorded requested models against the preserved evidence, failure rollback, the safe new-run reset and recovery from every interruption point, a multi-run lifecycle, and run comparisons (the shared-question rule, unequal and partial coverage, every comparability refusal, direction, model and version warnings). All of them use fictional audits in temporary folders with Gemini faked; the Boots golden reports are unchanged.

v2.5 added recurring monitoring tests: the planner and every start state, the due calculation, the methodology and API-key ordering guards, the per-audit lock (including a killed process releasing it), the read-only dry run, chunked collection and the spend circuit breaker, resume, complete-only snapshots, the partial-run policy, previous → new comparisons, re-baselining, recovery after a crash at each step, a multi-cycle history and the duplicate-trigger guard. Mutation checks confirmed the tests catch each deliberately broken safeguard. No test calls the Gemini API.

v2.6 added read-only API tests: the extracted comparison computation (byte-identical reports, same refusals, the pre-write re-validation), every resource's exact response shape, no writes and no Gemini or `.env` access, path and Host-header safety (including DNS rebinding), the method and CORS policies, sanitised errors, and end-to-end journeys through a real localhost server — including the separation of the current run from snapshots and the real Boots audit read without changes.

---

## Running Tests

Execute the complete test suite with:

```bash
python -m unittest discover -s tests -v
```

All engines are tested independently before being validated as part of the complete end-to-end workflow.

---

# Example Outputs

SignalScope AI generates structured Markdown reports covering:

- audit summaries
- competitor analysis
- authority analysis
- insight reports
- recommendation reports
- measurement reports

These outputs are designed to support consultant reviews, internal reporting and future audit comparisons.

---

# Engineering Philosophy

SignalScope AI was developed around a small number of engineering principles that guided every architectural decision throughout the project.

Rather than maximising the amount of AI used, the objective was to maximise reliability, explainability and maintainability.

The project deliberately combines deterministic software engineering with Large Language Models, allowing each technology to be used where it provides the greatest value.

The following principles shaped the entire system.

---

## 1. Evidence Before Interpretation

The platform never generates recommendations before collecting evidence.

Every optimisation opportunity originates from measurable observations produced during the audit process.

This separation reduces unsupported conclusions while making every recommendation traceable.

---

## 2. Deterministic Where Possible

Tasks involving objective calculations remain within traditional Python code.

Examples include:

- parsing responses
- counting mentions
- calculating visibility
- comparing audits
- validating historical data

Keeping these operations deterministic improves repeatability while making automated testing significantly easier.

---

## 3. AI Where It Adds Value

Large Language Models are used for reasoning rather than arithmetic.

Within SignalScope AI, AI is responsible for tasks such as:

- identifying strategic themes
- summarising findings
- explaining recommendations
- communicating insights

Objective calculations are intentionally kept outside the language model.

---

## 4. Modular Architecture

Each engine performs a single responsibility.

This provides several advantages:

- easier maintenance
- independent testing
- simpler debugging
- cleaner future expansion
- improved readability

Future functionality can therefore be added without redesigning the existing architecture.

---

## 5. Human Decision Making

SignalScope AI intentionally avoids making autonomous business decisions.

The platform supports decision making by presenting evidence, insights and recommendations.

Final implementation decisions remain with the organisation.

---

# AI Design Principles

One of the primary goals of this project was demonstrating responsible AI engineering.

Several safeguards were intentionally incorporated into the architecture.

## Explainability

Every recommendation references supporting evidence gathered during previous stages.

Recommendations are therefore transparent rather than opaque AI opinions.

---

## Traceability

Every stage of the pipeline builds upon outputs produced by the previous engine.

This creates a clear audit trail from raw AI response through to final recommendation.

---

## Validation

The Measurement Engine validates historical evidence before generating comparisons.

If insufficient evidence exists, the platform reports this explicitly instead of producing speculative conclusions.

---

## Separation of Responsibilities

The system deliberately avoids asking the language model to perform every task.

Traditional software engineering and AI each perform the work they are best suited for.

This hybrid architecture improves robustness while reducing unnecessary dependence upon AI.

---

# Key Design Decisions

Several architectural decisions intentionally differ from many AI applications.

## Markdown Reports

Markdown was selected because it is:

- lightweight
- version controllable
- human readable
- GitHub compatible
- consultant friendly

---

## Four Independent Engines

Instead of one large processing pipeline, functionality is separated into:

- Audit
- Insights
- Recommendations
- Measurement

This improves maintainability and future extensibility.

---

## No Autonomous Website Changes

SignalScope AI never edits website content automatically.

Instead, it provides evidence-based recommendations that organisations can implement through their existing teams.

This maintains human oversight throughout the optimisation process.

---

## Evidence-Based Measurement

Progress reports are generated only when sufficient historical evidence exists.

The platform never fabricates improvements simply to create more impressive reports.

---

# Current Limitations

SignalScope AI is intentionally positioned as a portfolio prototype rather than a production SaaS platform.

Current limitations include:

- single-user execution
- local processing
- manual audit execution
- limited provider support
- Markdown reporting only
- no persistent database
- no web interface
- no authentication
- no built-in scheduler: recurring monitoring is triggered by an external scheduler (Task Scheduler or cron)
- no history view in the dashboard; comparisons cover exactly two snapshots at a time
- the read-only API is local only (127.0.0.1, GET only, no authentication) and is not for internet exposure
- the monitoring lock is for local filesystems only; a persistently failing question may be re-attempted in later chunks of the same cycle (see [Recurring Monitoring](#recurring-monitoring))
- new audits require exactly three competitors and use the single master question template

Operational rules:

- **Run commands from the repository root.** `create_audit.py` always writes to the project's own `audits/` folder, but the `--audit` runners resolve audit and report paths relative to the current working directory.
- **Run one structured batch per audit at a time.** The runner detects another process writing to the same audit and stops rather than risk duplicate or corrupted results.
- **Run one write operation per audit at a time.** Do not run the structured batch, `snapshot` or `new-run` concurrently for the same audit, or while a monitoring cycle is working on it (see [Operator Safety](#operator-safety)).
- **Raw evidence needs hard-link support.** Evidence files are published with a filesystem hard link so an existing file can never be replaced. On a filesystem without hard links the run stops rather than fall back to overwriting.
- **Leftover temporary files.** Failed or interrupted (Ctrl-C) runs clean up after themselves. Only a hard process kill can leave an `audits/.creating-<slug>-*` staging folder (from `create_audit.py`) or a dot-prefixed `.tmp` file in a `raw_responses/` folder (from the structured batch). Neither is used as evidence, and both can be deleted manually. A hard kill during `snapshot` can likewise leave a `snapshots/.creating-*` staging folder, which is never listed or used as a snapshot. A `snapshots/.retired-raw-*` folder is different: it belongs to an unfinished `new-run` and must not be deleted by hand; run `new-run` again to finish it.
- **Historical rows are not backfilled.** Legacy incomplete Gemini rows are not reprocessed, and older complete rows are not regenerated to create raw evidence (see [Existing Results](#existing-results)).

These limitations were accepted in favour of demonstrating software architecture and engineering quality.

---

# Future Roadmap

## Version Roadmap

| Version | Focus | Status |
|---|---|---|
| v2.1 | Multi-company configuration foundation | Released |
| v2.2 | Repeatable client audit creation | Released |
| v2.3 | Structured batch evidence collection | Released |
| v2.4 | Audit snapshots and longitudinal history | Released |
| v2.5 | Recurring monitoring workflow | Released |
| v2.6 | Read-only local integration API | Current release |

Later platform work (database, cloud scheduling, a multi-project interface, authentication and cloud deployment, with billing and client self-service only when justified) is not yet scheduled.

Potential future enhancements include:

## Product

- Interactive web dashboard
- Multi-project management
- Historical trend visualisation
- Cloud-scheduled GEO monitoring and notifications
- Team collaboration
- API integrations
- Cloud deployment
- Export to PDF and PowerPoint

---

## AI

- Support for additional LLM providers
- Multi-model comparison
- Prompt optimisation
- Confidence scoring
- Recommendation confidence metrics

---

## Engineering

- Docker deployment
- CI/CD pipelines
- Database persistence
- REST API
- Authentication
- User management
- Containerised deployment
- Performance optimisation

---

# Portfolio Value

SignalScope AI was developed as a portfolio project demonstrating practical software engineering, AI integration and product thinking.

The project showcases experience across multiple disciplines, including:

- Python development
- AI application design
- Modular architecture
- Prompt engineering
- Software testing
- Product strategy
- Technical documentation
- Git workflows
- Version control
- Business analysis

Rather than focusing solely on technical implementation, the project demonstrates the complete lifecycle of transforming a business problem into a structured software solution.

---

# Lessons Learned

Developing SignalScope AI reinforced several important engineering lessons.

Building with AI requires thoughtful system design rather than simply connecting a language model to an application.

Separating deterministic processing from AI reasoning significantly improves reliability, testing and explainability.

Equally important was recognising that good AI products are not defined by how much AI they contain, but by how effectively AI and traditional software engineering complement one another.

---

# About the Author

SignalScope AI was designed and developed by **Rangoo Rajan** as part of a professional portfolio exploring the intersection of Artificial Intelligence, Marketing Technology, Revenue Operations and Software Engineering.

The project reflects a strong interest in designing practical AI systems that solve genuine business problems through evidence-driven decision making rather than automation for its own sake.

Areas of interest include:

- Artificial Intelligence
- Marketing Technology
- Revenue Operations
- Growth Strategy
- Automation
- Product Thinking
- Data-Driven Decision Making

---

# Acknowledgements

This project was built using the wider Python ecosystem together with Google's Gemini models.

It also benefited from modern software engineering practices including automated testing, modular architecture and Git-based version control.

---

# License

This project is released under the MIT License.

You are free to use, modify and distribute the software in accordance with the terms of the license.

See the accompanying `LICENSE` file for full details.

---

<div align="center">

**SignalScope AI v2.6.0**

*Evidence-Driven Generative Engine Optimisation Intelligence Platform*

Built with Python, AI and a passion for thoughtful software engineering.

</div>

