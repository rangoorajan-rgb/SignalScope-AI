# Methodology

This document describes the methodology for SignalScope AI, an AI-assisted consulting
workflow, not an autonomous agent. Parts of it are implemented: collecting current
audit evidence, structured Gemini analysis of each saved answer, immutable audit
snapshots and history, the new-run lifecycle, and deterministic comparison of two
preserved runs (see the "As implemented" notes and
[Longitudinal Measurement](#longitudinal-measurement)). Other parts remain design
intent — recurring scheduling and automatic monitoring are not yet implemented, nor
are later platform capabilities (see [CURRENT_SPRINT.md](../CURRENT_SPRINT.md)).

## Independent Query Methodology

Evidence is collected by putting a defined set of realistic, client-relevant questions
to one or more AI search engines, with each query treated as an independent
observation. Independence matters for two reasons:

- **Avoiding compounding bias.** If earlier answers in the same conversation are
  allowed to influence later ones, a single early mention (or omission) of a brand can
  artificially inflate or deflate everything that follows. Running each query
  independently means every result reflects that query alone.
- **Reproducibility.** Independent queries can be repeated at a later date, or by a
  different consultant, and compared on a like-for-like basis, because no hidden
  conversational context is shaping the answer.

Each query is logged with its exact wording, the platform and model used, the date and
time, and the raw response. This raw evidence is the foundation everything else is
built on — see [DATA_DICTIONARY.md](DATA_DICTIONARY.md) for the fields this will
require.

As implemented in v2.3 (`src/run_structured_batch_audit.py`), each buyer question is
sent to Gemini on its own; Gemini's complete answer is saved as a raw evidence file
(the exact question, the model requested, the collection date and the full answer)
before anything else happens; the saved answer is then analysed in a separate step
into structured observations (brand citation and position, competitors, sources and
sentiment); and the result is saved as one structured row. Because the answer is saved
first, the analysis can be traced back to, and if necessary repeated from, the exact
text it was based on. The implementation records the collection date rather than the
time, and the model requested rather than a confirmed served model version — see
[DATA_DICTIONARY.md](DATA_DICTIONARY.md#3-evidence-collection).

## Two-Pass AI Scoring

AI involvement in the workflow is split into two distinct, separated passes:

1. **Pass One — Generation / Extraction.** An AI system is used to extract structured
   observations from the raw evidence collected in the independent queries: for
   example, whether a brand was mentioned, what was said about it, which competitors
   were mentioned alongside it, and what sources (if any) were cited or implied.
2. **Pass Two — Scoring.** A separate AI pass takes the structured observations from
   Pass One — not the original raw response — and applies the scoring model to them.

## Why Scoring and Generation Are Separated

Generation and scoring are deliberately kept as two separate passes, rather than
asking a single AI call to "read the response and give it a score":

- **Reduces conflation of extraction errors and scoring errors.** If a single pass
  gets something wrong, it is very difficult to tell whether the AI misread the
  evidence or misapplied the scoring model. Separating the passes means each can be
  reviewed and validated independently.
- **Makes the scoring model auditable.** Because Pass Two operates on structured,
  human-readable observations rather than free text, a consultant can check the
  scoring logic against those observations directly, without having to re-interpret
  the original AI response themselves.
- **Limits the blast radius of AI error.** An extraction mistake in Pass One is
  visible and correctable at the Data Validation stage, before it can silently
  propagate into a numeric score in Pass Two.

## Human Validation

AI output is never passed directly to a client. The workflow includes two distinct
human checkpoints (see the workflow diagram in [README.md](../README.md)):

- **Data Validation**, after Evidence Collection: a consultant checks that the
  collected evidence is complete, correctly attributed and free of obvious collection
  errors before any AI analysis is run on it.
- **Consultant Review**, after Structured Scoring: a consultant checks the AI's
  extraction and scoring against the underlying evidence, corrects or annotates any
  disagreements, and decides what, if anything, is fit to present to the client.

No stage of the workflow is permitted to skip these checkpoints. This is a governing
principle of the project — see
[ADR-001](decisions/ADR-001-Project-Principles.md).

## Source Attribution Limitations

AI search engines do not always reliably disclose the sources underlying a given
answer, and where they do, that disclosure may be incomplete, approximate, or itself
generated rather than retrieved. SignalScope AI's methodology treats any
source-related output from an AI platform as **evidence to be reported, not fact to be
asserted**:

- Where a platform names or links a source, this is recorded as "the platform
  indicated source X" rather than "brand visibility is caused by source X."
- Where no source is disclosed, this is recorded as an absence of evidence, not as
  evidence of absence.
- Consultants are expected to treat source attribution as directional insight to
  inform recommendations, not as a definitive causal explanation of ranking or
  mention behaviour.

## Model Variability

AI search engines can return different answers to the same query at different times,
even with no material change in the underlying brand or its competitors. This is a
known characteristic of generative AI systems, not a defect in the methodology.
Consequences for the methodology:

- A single query result is treated as one data point, not as a definitive verdict.
- Where the engagement and timeline allow, repeated or multiple queries per question
  are preferred over a single run, so that variability can be observed rather than
  hidden.
- Reports and recommendations should describe findings as reflective of the evidence
  collected at a specific point in time, rather than as permanent, fixed facts about a
  brand's AI visibility.

## Longitudinal Measurement

As implemented in v2.4 (`src/audit_history.py`), change over time is measured between
preserved runs of the same audit:

```text
collect → snapshot → new-run → collect → snapshot → compare
```

- **Immutable historical copies.** Each snapshot keeps its own copy of the audit
  configuration, question set, structured results and raw evidence, verified by
  SHA-256 hashes, so every historical run can be interpreted with the methodology it
  actually used.
- **Comparability.** Two snapshots are compared only when they share the same audit,
  brand, market, category, ordered competitor list and ordered question methodology
  (question ID, buyer journey stage and question text). Otherwise the comparison is
  refused; changed question sets are not normalised or partially compared.
- **Shared-complete Gemini intersection.** Metrics use only Gemini questions that are
  structurally complete in both runs, and the same question IDs on both sides;
  manually entered and incomplete rows are excluded. This prevents missing evidence in
  one run from appearing as a change in visibility.
- **Coverage disclosure.** Each run's own coverage (structurally complete questions of
  all questions) and the number of shared questions used are always reported.
- **Warnings, not conclusions.** If the runs record different requested models or
  SignalScope versions, the comparison runs with a neutral warning. A warning does not
  imply that the difference caused any change in the metrics.
- **GEO Maturity caveat.** In a comparison, GEO Maturity is evaluated over the shared
  question set only, so it reflects brand visibility on those questions. When either
  run is partial, it is not that run's maturity over its full question library.
- **Model variability still applies.** A difference between two runs is a measured
  difference between two recorded datasets, not proof of what caused it.
