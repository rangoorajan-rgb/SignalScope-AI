# Audit Specification — Build 1

This document is the authoritative consulting specification for Build 1 of
SignalScope AI. It defines what a SignalScope AI audit sets out to establish, for
whom, against what criteria, and to what standard of evidence — independent of any
particular technology choice.

SignalScope AI is an **AI-assisted consulting workflow**, not an autonomous AI agent.
It does not run unattended, and it does not publish findings without a consultant's
review. This document is a consulting specification, not a build guide: it defines no
technical implementation, and nothing described here has been built yet (see
[CURRENT_SPRINT.md](../CURRENT_SPRINT.md)). It should be read alongside
[PROJECT_SCOPE.md](PROJECT_SCOPE.md), [METHODOLOGY.md](METHODOLOGY.md),
[DATA_DICTIONARY.md](DATA_DICTIONARY.md) and
[ADR-001](decisions/ADR-001-Project-Principles.md), which it does not duplicate but
builds upon.

## 1. Business Problem

Buyers increasingly form judgements about brands, products and services from AI
search and answer engines before they ever visit a website. These engines synthesise
an answer from many sources and present it as a single, authoritative-sounding
recommendation, often without the buyer clicking through to verify it. A brand that is
absent from that answer, or present but poorly characterised, may never enter the
buyer's consideration set — regardless of how strong its traditional search or brand
presence is. Brand owners currently have no structured, evidence-based way to observe
this, compare it against competitors, or understand what is driving it.

## 2. Why AI Search Visibility Matters

- **Discovery is shifting upstream.** Buyers are increasingly forming a shortlist from
  a single AI-generated answer rather than a page of search results, compressing the
  traditional discovery journey into fewer, higher-stakes moments.
- **The AI is now an intermediary, not just a channel.** The engine selects,
  summarises and characterises a brand on the buyer's behalf; the brand has far less
  direct control over its own message than in owned or paid channels.
- **Absence is invisible until measured.** A brand can be entirely excluded from
  AI-generated recommendations while remaining unaware of it, because there is no
  ranking page to check and no click-through data to review.
- **Misrepresentation carries reputational risk.** Where a brand is included but
  inaccurately or unfavourably characterised, this can shape buyer perception at
  scale, with no obvious mechanism for the brand to correct it.
- **Competitors are being compared automatically.** Where an AI response names
  alternatives, it is performing an implicit competitive comparison on the buyer's
  behalf, whether or not the brand has any visibility into how that comparison was
  formed.

## 3. Audit Objective

The objective of a Build 1 SignalScope AI audit is to produce an evidence-based
assessment of a client brand's standing within AI-generated answers to realistic
buyer questions, benchmarked against a defined set of competitors, structured around a
four-dimensional framework (see [Section 11](#11-core-metrics)), and reviewed by a
consultant before any finding or recommendation is presented to the client.

## 4. Scope

A Build 1 audit covers:

- A single client brand, assessed within an agreed [target market](#6-target-markets)
  and against an agreed set of [competitors](#8-competitor-selection-criteria).
- A defined set of realistic buyer queries, constructed around agreed
  [buyer personas](#7-target-buyer-personas) and mapped to the
  [buyer journey](#9-buyer-journey-framework).
- Evidence collected as a point-in-time snapshot, not continuous monitoring (see
  [Limitations](#15-limitations)).
- Structured scoring of that evidence across the four core dimensions, validated by a
  consultant.
- A consultant-reviewed report of findings and strategic recommendations (see
  [Planned Outputs](#16-planned-outputs)).

## 5. Out of Scope

A Build 1 audit does not cover:

- Continuous or real-time monitoring of AI search visibility.
- Any guarantee of improved visibility, prominence, authority or sentiment as an
  outcome of acting on the audit's recommendations.
- Direct implementation of technical or content changes on the client's behalf (for
  example, publishing content, editing a website, or managing citations); the audit
  produces recommendations, not implementation work.
- Paid media, traditional SEO, or public relations activity.
- Legal, regulatory or brand-safety advice.
- Any method of accessing AI platforms that breaches their terms of service.
- Publication of any finding or recommendation to the client without consultant
  review and sign-off.

## 6. Target Markets

Each audit defines its target market explicitly and in agreement with the client,
rather than assuming a single global market. A target market definition addresses:

- **Geographic scope** — the country or countries the audit represents, since AI
  responses can vary by region.
- **Language scope** — the language(s) in which queries will be posed, since this can
  materially change which sources an AI system draws on.
- **Sector or category scope** — the specific industry, product or service category
  the brand competes within, defined precisely enough to distinguish it from adjacent
  categories.
- **Sub-segment scope**, where relevant — for example, an enterprise versus small
  business audience within the same broad category.

This scope is agreed with the client before evidence collection begins and is
recorded against the engagement (see [DATA_DICTIONARY.md](DATA_DICTIONARY.md#1-engagement)).

## 7. Target Buyer Personas

Buyer personas ground the audit's queries in how real buyers actually ask questions,
rather than in how the brand describes itself. For each audit, the consultant defines
one or more personas in collaboration with the client, each covering:

- **Role and context** — the persona's job role or life situation, and their
  relationship to the purchase decision (for example, decision-maker, influencer, or
  end user).
- **Need state** — the underlying problem or goal driving the persona to seek a
  solution.
- **Buying-stage relevance** — which stages of the [buyer journey](#9-buyer-journey-framework)
  this persona is likely to be active in.
- **Likely question framing** — the kind of language and level of specificity this
  persona would realistically use when asking an AI system about the category.

Personas are a consulting input, agreed with the client, not a technical construct;
they exist to keep the audit's query set representative of real buyers rather than of
the brand's own preferred terminology.

## 8. Competitor Selection Criteria

Competitors are selected deliberately and transparently, not automatically, so that
every benchmarking comparison in the audit can be explained and defended. Selection
draws on:

- **Client-nominated competitors** — brands the client already considers direct
  rivals.
- **Category leaders** — brands with recognised leading market position or brand
  recognition in the target market.
- **Emerging or disruptor competitors** — newer entrants gaining visible traction in
  the category, which the client may not yet consider a primary threat.
- **Adjacent or substitute solutions**, where relevant — alternative approaches a
  buyer might be offered instead of the category the client operates in.

A typical competitor set is kept small enough to support a focused, explainable
comparison (as a guide, three to six named competitors); the exact composition and
rationale for each engagement is agreed with the client and recorded before evidence
collection begins.

## 9. Buyer Journey Framework

Queries are constructed to reflect how a buyer's questions change as they move
through a purchase decision, so that visibility can be understood by journey stage
rather than as a single undifferentiated score. The framework uses four stages:

1. **Awareness** — the buyer is exploring a problem or need and has not yet framed it
   in terms of named solutions or brands (for example, "what are the options for
   solving [problem]?").
2. **Consideration** — the buyer is aware that solutions and brands exist and is
   forming a shortlist (for example, "who are the leading providers of [category]?").
3. **Evaluation** — the buyer is comparing specific, named options against each other
   (for example, "how does [brand] compare to [competitor]?").
4. **Decision** — the buyer is validating a near-final choice (for example, "is
   [brand] a good choice for [need]?" or "reviews of [brand]").

Every query in the evidence set is tagged to the journey stage it represents, so
findings can show not only whether a brand is visible overall, but at which stages of
the buyer's decision it is strong or weak.

## 10. Audit Methodology

The audit methodology follows the process defined in
[METHODOLOGY.md](METHODOLOGY.md) and is not repeated in full here. In summary, and
specific to a Build 1 audit:

- Queries are constructed from the agreed personas and journey stages, and put to AI
  search platforms as **independent queries** (see
  [METHODOLOGY.md](METHODOLOGY.md#independent-query-methodology)), so that no single
  query's result is shaped by another.
- Each query and its response are logged as raw evidence and pass through
  **Data Validation** before any analysis is performed.
- Analysis follows the **two-pass** approach — structured extraction, then scoring —
  described in [METHODOLOGY.md](METHODOLOGY.md#two-pass-ai-scoring), so that
  extraction and scoring can each be checked independently.
- Where the engagement timeline allows, queries are run more than once to observe
  [model variability](METHODOLOGY.md#model-variability) rather than treating a single
  response as definitive.

## 11. Core Metrics

Findings are organised around four dimensions. Together, they distinguish *whether* a
brand appears from *how well* it appears — a brand can be visible without being
prominent, and prominent without being portrayed favourably.

- **Visibility** — whether the brand appears at all in AI-generated responses to the
  defined query set. This is the foundational, binary question: is the brand part of
  the conversation at all, and for what proportion of relevant queries.
- **Prominence** — how strongly the brand features when it is visible: its position
  relative to other brands mentioned, the amount of detail or space it is given, and
  whether it appears as the leading recommendation or a minor aside.
- **Authority** — the degree to which the AI's response treats the brand as a
  credible, trustworthy option, including any sources the platform discloses or
  implies (see [source attribution limitations](METHODOLOGY.md#source-attribution-limitations)),
  and how confidently or tentatively the brand is discussed.
- **Sentiment** — the tone and characterisation applied to the brand where it is
  mentioned: positive, neutral, negative or mixed, and whether qualifying language
  strengthens or undermines that characterisation.

Indicative metrics within each dimension include:

| Dimension | Indicative metrics |
|---|---|
| Visibility | Mention rate across the query set; coverage by persona and journey stage |
| Prominence | Average position among brands mentioned; relative share of voice against named competitors; depth of mention |
| Authority | Rate and nature of source disclosure; confidence of language used to describe the brand |
| Sentiment | Distribution of positive, neutral and negative characterisation; frequency of hedging or qualifying language |

The precise calculation of each metric is a Build 1 implementation decision and is
not specified here; see [DATA_DICTIONARY.md](DATA_DICTIONARY.md#5-ai-analysis--pass-one-extraction)
for the underlying fields these metrics will be derived from.

## 12. Scoring Rubric

Each dimension is scored on a common, descriptive banded scale, so that a score is
always interpretable in plain language rather than as an opaque number:

| Band | Indicative meaning |
|---|---|
| Absent | No evidence of the brand on this dimension within the query set |
| Emerging | Limited or inconsistent evidence on this dimension |
| Established | Consistent, comparable evidence on this dimension relative to competitors |
| Leading | Evidence that the brand outperforms its named competitors on this dimension |

A brand therefore receives a band for each of Visibility, Prominence, Authority and
Sentiment, rather than a single blended figure — preserving the distinction between,
for example, a brand that is highly visible but poorly characterised, and one that is
rarely mentioned but favourably described when it is.

Whether and how these four bands are combined into a single composite score is
deliberately left open in this specification; any such composite must remain
traceable back to the four underlying bands and is a decision for a future ADR (see
[ADR-001](decisions/ADR-001-Project-Principles.md)), not this document. Precise
numeric thresholds behind each band are similarly a Build 1 decision, flagged as such
rather than fixed here (see [DATA_DICTIONARY.md](DATA_DICTIONARY.md#6-structured-scoring--pass-two)).

## 13. Human Validation Process

No score or finding reaches a client without passing through the two human
checkpoints defined in [METHODOLOGY.md](METHODOLOGY.md#human-validation):

- **Data Validation**, applied to the raw evidence before any AI analysis, confirming
  the evidence collected is complete and correctly attributed to the right query,
  persona and journey stage.
- **Consultant Review**, applied to the extracted observations and the scoring band
  assigned to each dimension, in which the consultant checks the AI's output against
  the underlying evidence, corrects or annotates any disagreement, and decides what is
  fit to present to the client.

A consultant may adjust a band assigned by the scoring process where the underlying
evidence supports a different reading; any such adjustment is recorded, together with
its rationale (see [DATA_DICTIONARY.md](DATA_DICTIONARY.md#7-consultant-review)).

## 14. Governance Principles

A Build 1 audit is bound by the same governing principles as the rest of the project
(see [ADR-001](decisions/ADR-001-Project-Principles.md)):

1. **Evidence first.** Every band, finding and recommendation must be traceable to
   specific, collected evidence.
2. **AI second.** AI is used to extract structured observations from evidence and to
   apply the scoring rubric to them — not to originate unverified claims about a
   brand.
3. **Human judgement always.** A consultant validates the evidence, reviews the AI's
   extraction and scoring, and owns every recommendation that reaches a client. AI
   does not make final decisions.

## 15. Limitations

- **Point in time, not continuous.** A Build 1 audit is a snapshot of AI search
  behaviour at the time evidence was collected; AI platforms and their responses
  change over time, and the audit does not claim to represent an ongoing or future
  state.
- **Sample-based, not exhaustive.** The audit reflects a defined query set built from
  agreed personas and journey stages; it cannot represent every possible way a buyer
  might phrase a question.
- **Model variability.** AI platforms can return different answers to the same query
  at different times, for reasons outside the audit's control (see
  [METHODOLOGY.md](METHODOLOGY.md#model-variability)); a single result is one data
  point, not a definitive verdict.
- **Source attribution is limited.** Where an AI platform discloses or implies a
  source, this is reported as evidence of what the platform indicated, not as a
  proven causal explanation of the brand's standing (see
  [METHODOLOGY.md](METHODOLOGY.md#source-attribution-limitations)).
- **No outcome guarantee.** The audit assesses current standing and informs
  recommendations; it cannot guarantee that acting on those recommendations will
  change future AI-generated responses.

## 16. Planned Outputs

A Build 1 audit is intended to produce, once consultant-reviewed:

- An **executive summary** describing the client brand's overall standing across the
  four dimensions, in plain language for a non-technical audience.
- A **scorecard** per brand (client and each named competitor) showing the banded
  score for each dimension, broken down by buyer journey stage where evidence
  supports it.
- A **competitive benchmarking view** comparing the client brand against its named
  competitors across all four dimensions.
- An **evidence appendix** referencing the underlying queries and responses each
  finding is drawn from, so that every claim in the report can be traced back to its
  source evidence.
- A set of **strategic recommendations**, authored and approved by the consultant,
  addressing where and how the client brand could improve its AI search standing.

## 17. Success Criteria

A Build 1 audit is judged successful where:

- Every band and finding in the delivered report can be traced back to specific,
  logged evidence.
- A consultant can explain, in plain English and without reference to any underlying
  technology, how each score was reached.
- The client can see not only whether their brand is visible, but where in the buyer
  journey and relative to which competitors it is strong or weak.
- No finding or recommendation reached the client without having passed through both
  human validation checkpoints defined in [Section 13](#13-human-validation-process).
- The audit's limitations (see [Section 15](#15-limitations)) are stated alongside its
  findings, rather than findings being presented as more certain than the evidence
  supports.
