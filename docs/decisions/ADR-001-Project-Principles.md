# ADR-001: Project Principles

## Status

Accepted — 2026-07-16

## Context

SignalScope AI is an AI-assisted consulting workflow that analyses how brands appear in
AI-generated search results and produces recommendations that consultants deliver to
clients. Because the workflow involves AI
at multiple stages (evidence extraction and scoring), and because AI outputs can be
inaccurate, inconsistent between runs, or presented with unwarranted confidence, the
project needs a clear, agreed set of engineering principles before any implementation
work begins. These principles are intended to govern every future technical decision
in this project, including technology choices, prompt design, and data handling.

## Decision

The project adopts the following principles:

### 1. Evidence first

Every claim made about a brand's AI search visibility must be traceable to specific,
collected evidence (a logged query and raw response — see
[DATA_DICTIONARY.md](../DATA_DICTIONARY.md)). No output in this workflow is permitted
to originate from an unverified or un-sourced AI assertion.

### 2. AI second

AI is used to analyse and structure evidence that has already been collected and
validated — not to originate facts, and not to be treated as an authority in its own
right. Its role is bounded to two specific tasks in the workflow: extracting
structured observations from evidence (Pass One), and applying a scoring model to
those observations (Pass Two). See
[METHODOLOGY.md](../METHODOLOGY.md#two-pass-ai-scoring).

### 3. Human judgement always

A consultant reviews evidence before AI analysis runs on it, and reviews AI output
before it can reach a client. AI does not make final decisions, and no stage of the
workflow is permitted to bypass a human checkpoint. See
[METHODOLOGY.md](../METHODOLOGY.md#human-validation).

### 4. Separation of generation and scoring

AI extraction and AI scoring are implemented as two distinct, separated passes rather
than a single combined step, so that extraction errors and scoring errors can be
identified and corrected independently, and so the scoring logic remains auditable
against structured, human-readable observations rather than free text. See
[METHODOLOGY.md](../METHODOLOGY.md#why-scoring-and-generation-are-separated).

### 5. Explainability over automation

Every score and recommendation must be explainable in plain English to a
non-technical client, with a clear line back to the evidence that produced it.
Technical sophistication is never a substitute for a consultant being able to justify
a finding.

### 6. No overstatement of functionality or certainty

Documentation and project communications will describe only what has actually been
built or decided. Model outputs are inherently variable (see
[METHODOLOGY.md](../METHODOLOGY.md#model-variability)) and source attribution from AI
platforms is inherently limited (see
[METHODOLOGY.md](../METHODOLOGY.md#source-attribution-limitations)); the project will
not present either as more certain than the evidence supports.

## Consequences

- Every future technical decision (choice of AI provider(s), data storage, scoring
  implementation, prompt design) must be checked against these principles before being
  adopted.
- Features that would allow AI output to reach a client without a human review step
  are explicitly disallowed by this ADR and would require a new ADR to supersede it.
- Some workflow steps will necessarily be slower than a fully automated alternative,
  because human validation and review are mandatory, not optional, stages. This is an
  accepted trade-off in favour of accuracy and defensibility over speed.
- Future ADRs that touch technology choices, data handling or scoring design should
  reference this ADR as the baseline they must remain consistent with.
