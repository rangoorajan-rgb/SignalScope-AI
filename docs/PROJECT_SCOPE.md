# Project Scope

## Problem Statement

Brands increasingly appear — or fail to appear — in AI-generated answers from tools
such as ChatGPT, Gemini and Perplexity, but have no structured, evidence-based way to
observe this. Consultants advising these brands currently rely on informal, ad hoc
checks (manually asking an AI tool a few questions) rather than a repeatable,
defensible methodology. SignalScope AI is an AI-assisted consulting workflow designed
to address this gap, by providing a structured process for collecting, validating and
scoring evidence of AI search visibility.

## Objectives

- Provide a repeatable method for collecting evidence of how a brand appears in
  AI-generated responses to relevant, real-world queries.
- Enable structured comparison between a brand and its named competitors within that
  evidence.
- Surface the sources an AI system appears to draw on, where this can be evidenced.
- Produce a consistent, structured scoring model that a consultant can interpret and
  explain to a client.
- Keep AI analysis and human judgement clearly separated at every stage, so that every
  client-facing recommendation is consultant-owned.

## In Scope

- Definition of an evidence collection process for AI search visibility.
- Definition of a data validation step prior to AI analysis.
- Definition of a two-pass AI analysis and scoring methodology.
- Definition of the fields and structures needed to represent this evidence and
  scoring consistently (see [DATA_DICTIONARY.md](DATA_DICTIONARY.md)).
- Definition of the consultant review and executive recommendation stages.
- Governance and engineering principles for how the project will be built (see
  [decisions/ADR-001-Project-Principles.md](decisions/ADR-001-Project-Principles.md)).

## Out of Scope

- Automated, unsupervised publication of recommendations to clients.
- Any claim of real-time or continuous monitoring; the workflow is designed around
  discrete, point-in-time audits unless and until a future sprint scopes otherwise.
- Scraping or accessing AI platforms in ways that breach their terms of service.
- Guaranteeing improved AI search rankings as an outcome; the project produces
  evidence and recommendations, not guaranteed results.
- At this stage: any application code, integrations, prompts or data. This sprint is
  documentation and structure only.

## Deliverables

The eventual deliverables of the SignalScope AI workflow (not yet built) are expected
to be:

- A structured evidence set per client engagement.
- A scoring output per brand/competitor per query set.
- A consultant-reviewed executive report with recommendations.

The deliverable of the **current** sprint (Sprint 0) is limited to the project
foundation: documentation, structure and governance, as tracked in
[CURRENT_SPRINT.md](../CURRENT_SPRINT.md).

## Success Criteria

- A consultant can pick up the methodology and explain, step by step, how a score or
  recommendation was reached, with evidence to support it.
- Every scoring output can be traced back to specific, collected evidence rather than
  an unverified AI claim.
- No stage of the workflow allows AI output to reach a client without a documented
  human review step.

## Constraints

- The project must not present AI-generated analysis as fact without a validation
  step.
- The project must not depend on scraping methods that violate the terms of service of
  the AI platforms being audited.
- The project must remain explainable to a non-technical client; scoring and
  methodology should be describable in plain English, not only in code.
- Model outputs from AI search engines are inherently variable between runs (see
  [METHODOLOGY.md](METHODOLOGY.md#model-variability)); the methodology must account
  for this rather than treating a single AI response as ground truth.
