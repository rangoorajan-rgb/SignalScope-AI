# SignalScope AI

**AI Search Visibility & GEO Intelligence Auditor**

## Project Overview

SignalScope AI is an AI-assisted consulting workflow for measuring how visible a brand
is across modern AI search engines, such as ChatGPT, Gemini and Perplexity. It is
designed to help consultants understand whether a brand appears in AI-generated
recommendations, how it compares against competitors, which sources the underlying
models rely on, and where opportunities exist to improve Generative Engine
Optimisation (GEO).

SignalScope AI is **not** a chatbot and **not** a fully autonomous AI agent. It is a
structured workflow in which AI performs analysis and the consultant validates evidence
and owns every recommendation that reaches a client.

## Business Problem

Search behaviour is shifting from traditional link-based search engines to
AI-generated answers and recommendations. Brands have very little visibility into:

- Whether they are mentioned at all in AI-generated responses to relevant queries.
- How they are positioned relative to competitors within those responses.
- Which underlying sources (websites, reviews, directories, press) AI systems appear
  to be drawing on when forming those answers.
- What actions might plausibly improve their standing in AI-generated results.

Without a structured way to observe and evidence this, brands and their consultants are
making GEO decisions on guesswork rather than data.

## Target Users

- **Marketing and SEO/GEO consultants** who need a repeatable, evidence-based method
  for auditing a client's AI search visibility.
- **In-house marketing and brand teams** who want to understand their standing in
  AI-generated recommendations before commissioning external work.
- **Agencies** seeking a defensible, structured methodology to offer as part of a
  broader search or digital visibility service.

## High-Level Workflow

```
Client Question
      ↓
Evidence Collection
      ↓
Data Validation
      ↓
AI Analysis
      ↓
Structured Scoring
      ↓
Consultant Review
      ↓
Executive Recommendations
```

Each stage produces artefacts that feed the next. AI is used within the Evidence
Collection, AI Analysis and Structured Scoring stages; the Data Validation and
Consultant Review stages are deliberately human-owned checkpoints. See
[docs/METHODOLOGY.md](docs/METHODOLOGY.md) for the full rationale behind this design,
and [docs/PROJECT_SCOPE.md](docs/PROJECT_SCOPE.md) for what is and is not in scope.

## Technology Roadmap

No implementation technology has been chosen yet. This repository currently contains
only the project foundation (documentation, structure and governance). Technology
decisions — including language, AI provider(s), data storage and any tooling — will be
made deliberately and recorded as Architecture Decision Records in
[docs/decisions/](docs/decisions/) once work on the workflow itself begins.

## Governance Statement

This project follows three governing principles, detailed in full in
[ADR-001](docs/decisions/ADR-001-Project-Principles.md):

1. **Evidence first.** Every claim made about a brand's AI search visibility must be
   traceable to collected evidence.
2. **AI second.** AI is used to analyse and structure evidence, not to originate
   unverified claims.
3. **Human judgement always.** A consultant reviews all evidence and AI output before
   any recommendation is issued to a client. AI does not make final decisions.

## Current Project Status

**Sprint 0 — Project Foundation.** This repository currently contains only the
project's documentation and directory structure. No application logic, data pipelines,
prompts or scoring mechanisms have been built. See
[CURRENT_SPRINT.md](CURRENT_SPRINT.md) for current status and
[docs/CHANGELOG.md](docs/CHANGELOG.md) for version history.
