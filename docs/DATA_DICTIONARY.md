# Data Dictionary

This document defines the fields planned for the SignalScope AI workflow. It is a
design specification: field names below are descriptive, and the implemented storage
differs from it where noted (see the implementation note under
[Evidence Collection](#3-evidence-collection)).

The fields are grouped by the workflow stage in which they are first created (see
[README.md](../README.md) for the stage diagram).

## 1. Engagement

Identifies the client engagement a piece of evidence or analysis belongs to.

| Field | Type | Description |
|---|---|---|
| `engagement_id` | string | Unique identifier for a client engagement/audit. |
| `client_name` | string | Name of the client brand being audited. |
| `engagement_date` | date | Date the audit was commissioned or started. |
| `competitor_names` | list of strings | Named competitor brands to be tracked alongside the client brand. |
| `consultant_name` | string | Consultant responsible for the engagement. |

## 2. Client Question

Captures the business question the client wants answered, before it is turned into
queries.

| Field | Type | Description |
|---|---|---|
| `question_id` | string | Unique identifier for a client question. |
| `engagement_id` | string | Foreign key to the parent engagement. |
| `question_text` | string | The client's original question, in their own words. |
| `business_context` | string | Brief note on why this question matters to the client. |

## 3. Evidence Collection

Represents a single independent query put to an AI search engine and its raw
response. See [METHODOLOGY.md](METHODOLOGY.md#independent-query-methodology).

| Field | Type | Description |
|---|---|---|
| `query_id` | string | Unique identifier for a single query run. |
| `question_id` | string | Foreign key to the client question this query addresses. |
| `query_text` | string | The exact wording of the query submitted to the AI platform. |
| `platform` | string | AI platform used (e.g. ChatGPT, Gemini, Perplexity). |
| `model_name` | string | Specific model/version used, where disclosed by the platform. |
| `run_timestamp` | datetime | Date and time the query was run. |
| `raw_response_text` | string | The complete, unedited response returned by the platform. |
| `run_sequence_number` | integer | Index of this run where a query is repeated multiple times, to support observation of [model variability](METHODOLOGY.md#model-variability). |
| `collection_method` | string | How the query was submitted (e.g. manual entry via platform UI, API). |

**Implementation note (v2.3).** Evidence collected by
`src/run_structured_batch_audit.py` is stored in two places:

- **Raw evidence file** — `audits/<slug>/raw_responses/<question_id>__gemini.json`,
  one per question, holding `format_version`, `audit_slug`, `question_id`, `question`
  (the exact query text sent), `engine` (the platform, `Gemini`), `requested_model`,
  `run_date` and `raw_response_text` (the complete, unedited response). Compared with
  the design above: `requested_model` is the model SignalScope requested, not a
  disclosed served model version; `run_date` is a date, not a timestamp; there is no
  separate `query_id` or `run_sequence_number`, because each question is asked once
  per audit and identified by `(question_id, engine)`.
- **`audits/<slug>/audit_results.csv`** — one structured row per question and engine,
  in the existing 11-column format, including `answer_snippet`: the response collapsed
  to a single line and truncated to 500 characters. It does not contain the complete
  response.

Rows collected before v2.3 (and Perplexity rows, which were recorded manually) have no
raw evidence file; for them, only `answer_snippet` survives.

## 4. Data Validation

Records the consultant's check of collected evidence before it proceeds to AI
analysis.

| Field | Type | Description |
|---|---|---|
| `validation_id` | string | Unique identifier for a validation check. |
| `query_id` | string | Foreign key to the evidence being validated. |
| `validated_by` | string | Consultant who performed the validation. |
| `validation_timestamp` | datetime | Date and time the validation was performed. |
| `validation_status` | enum | One of: `approved`, `rejected`, `needs_recollection`. |
| `validation_notes` | string | Consultant notes on any issues found, or confirmation of completeness. |

## 5. AI Analysis — Pass One (Extraction)

Structured observations extracted from a validated raw response. See
[METHODOLOGY.md](METHODOLOGY.md#two-pass-ai-scoring).

| Field | Type | Description |
|---|---|---|
| `extraction_id` | string | Unique identifier for an extraction record. |
| `query_id` | string | Foreign key to the source evidence. |
| `brand_mentioned` | boolean | Whether the client brand was mentioned in the response. |
| `brand_mention_context` | string | Verbatim or closely paraphrased text describing how the brand was mentioned. |
| `brand_mention_position` | integer | Ordinal position of the brand mention within the response, where applicable (e.g. first, second recommendation). |
| `competitors_mentioned` | list of strings | Competitor brands identified in the response. |
| `sources_disclosed` | list of strings | Any sources, citations or links disclosed or implied by the platform (see [source attribution limitations](METHODOLOGY.md#source-attribution-limitations)). |
| `sentiment_summary` | string | Consultant- or AI-drafted summary of how the brand was characterised, pending human review. |
| `extraction_timestamp` | datetime | Date and time Pass One was run. |
| `extraction_model` | string | AI model used to perform the extraction. |

## 6. Structured Scoring — Pass Two

Scores derived from Pass One extraction output, not from the raw response directly.

| Field | Type | Description |
|---|---|---|
| `score_id` | string | Unique identifier for a scoring record. |
| `extraction_id` | string | Foreign key to the Pass One extraction this score is derived from. |
| `visibility_score` | number | Score representing whether/how prominently the brand appeared. Scale to be defined. |
| `competitive_position_score` | number | Score representing the brand's standing relative to named competitors. Scale to be defined. |
| `source_influence_score` | number | Score representing the apparent influence of disclosed sources, where evidenced. Scale to be defined. |
| `scoring_model_version` | string | Version identifier of the scoring model/rubric applied. |
| `scoring_timestamp` | datetime | Date and time Pass Two was run. |
| `scoring_model` | string | AI model used to perform the scoring. |

## 7. Consultant Review

Records the human review of AI extraction and scoring output before anything is
presented to a client.

| Field | Type | Description |
|---|---|---|
| `review_id` | string | Unique identifier for a review record. |
| `score_id` | string | Foreign key to the score being reviewed. |
| `reviewed_by` | string | Consultant who performed the review. |
| `review_timestamp` | datetime | Date and time the review was performed. |
| `review_outcome` | enum | One of: `accepted`, `adjusted`, `rejected`. |
| `adjustment_notes` | string | Explanation of any changes the consultant made to the AI output, and why. |

## 8. Executive Recommendations

Represents the final, client-facing output of an engagement.

| Field | Type | Description |
|---|---|---|
| `recommendation_id` | string | Unique identifier for a recommendation. |
| `engagement_id` | string | Foreign key to the parent engagement. |
| `recommendation_text` | string | The recommendation as it will be presented to the client. |
| `supporting_evidence_ids` | list of strings | References to the `query_id`/`extraction_id`/`score_id` records underpinning this recommendation. |
| `authored_by` | string | Consultant who authored the recommendation. |
| `approved_by` | string | Consultant or senior reviewer who signed off the recommendation for delivery. |
| `delivery_date` | date | Date the recommendation was delivered to the client. |
