# Question Generation Guide

This guide explains how to use and maintain the buyer question library at
[questions/buyer_questions_master.csv](../questions/buyer_questions_master.csv) (and
its `.xlsx` equivalent). It is a consulting reference document, not a technical
specification: it describes how a consultant should work with the library, not how any
part of it is built or automated.

## Purpose of the Question Library

The library is a **reusable set of 40 buyer questions**, evenly split across the five
stages of the buyer journey used at this stage of the project (eight questions per
stage — see [Buyer journey stage naming](#buyer-journey-stage-naming-a-note-for-reviewers)
below):

1. Problem Awareness
2. Solution Discovery
3. Vendor Comparison
4. Vendor Evaluation
5. Purchase Decision

Each question is written in natural, conversational language — the way a real buyer
would put a question to a conversational AI tool — rather than as a short keyword
search. The library exists so that every SignalScope AI audit starts from the same
well-considered, methodology-aligned question set, instead of a consultant improvising
questions from scratch for each engagement. This supports the "independent query
methodology" described in [METHODOLOGY.md](METHODOLOGY.md#independent-query-methodology)
and the buyer-journey-mapped evidence collection described in
[AUDIT_SPECIFICATION.md](AUDIT_SPECIFICATION.md#9-buyer-journey-framework): consistent,
comparable questions are what make evidence collected across different engagements,
brands and time periods meaningfully comparable.

The library is a **template**. It contains no real brand, company or market names —
see the next section.

## Why Placeholders Are Used

Every question uses one or more of six placeholders in place of real names:

| Placeholder | Represents |
|---|---|
| `[BRAND]` | The client brand being audited |
| `[CATEGORY]` | The product or service category the brand competes in |
| `[MARKET]` | The geographic or language market the audit covers |
| `[COMPETITOR_1]` | The client's first named competitor |
| `[COMPETITOR_2]` | The client's second named competitor |
| `[COMPETITOR_3]` | The client's third named competitor |

Placeholders are used, rather than a worked example with a real company, for three
reasons:

- **Reusability.** The same 40 questions can be used, unchanged in structure, for
  every future audit — only the placeholder values change from one engagement to the
  next.
- **Neutrality.** A library built around one real brand risks embedding that brand's
  specific language, category framing or competitive set into what should be a
  general-purpose template.
- **Governance.** Per [PROJECT_SCOPE.md](PROJECT_SCOPE.md#out-of-scope) and
  [ADR-001](decisions/ADR-001-Project-Principles.md), no real client or brand data
  belongs in shared, reusable project assets. Keeping the master library placeholder-
  only means it can be stored, reviewed and version-controlled without any
  confidentiality concern.

## How to Replace Placeholders for a Real Audit

1. **Do not edit the master file.** Copy `buyer_questions_master.csv` (or `.xlsx`) to
   a working file for the specific engagement — for example, into
   [data/input/](../data/input/) — and edit the copy. The master stays a clean,
   placeholder-only template for the next audit.
2. **Confirm all six values before starting**, agreed with the client per
   [AUDIT_SPECIFICATION.md](AUDIT_SPECIFICATION.md): the brand name (`[BRAND]`), the
   category as the client would recognise it (`[CATEGORY]`), the target market
   (`[MARKET]`), and the three competitors selected under the
   [competitor selection criteria](AUDIT_SPECIFICATION.md#8-competitor-selection-criteria)
   (`[COMPETITOR_1]`–`[COMPETITOR_3]`).
3. **Use a consistent find-and-replace pass** across the whole file for each
   placeholder in turn, rather than editing questions individually — this avoids
   missing an instance or introducing inconsistent naming partway through the file.
4. **Keep the wording of the question unchanged** wherever possible. The questions
   have been written and reviewed as natural, conversational phrasing; changing wording
   as well as placeholders makes it harder to compare results against other audits
   that used the standard library.
5. **Re-read every question once replacement is complete**, to catch anything that no
   longer reads naturally once real names are inserted (for example, a category name
   that does not fit the sentence grammatically) — see [Validation](#how-to-validate-generated-questions)
   below.

## How to Validate Generated Questions

Before a replaced (real-world) question set is used to collect evidence, check it
against the following:

- **No placeholders remain.** Search the completed file for any remaining `[` or `]`
  characters — every placeholder should have been replaced.
- **The question reads naturally.** Read each question aloud. It should sound like
  something a real person would type into a conversational AI tool, not like a
  templated sentence with words dropped in.
- **The question is still a genuine question.** It should be a complete, natural
  sentence ending in a question mark — not a keyword fragment.
- **The brand, category, market and competitor names are used correctly and
  consistently**, matching the spelling and form agreed with the client throughout
  (for example, not switching between a full company name and an abbreviation).
- **No duplicate questions have been introduced**, including near-duplicates created
  by editing the same question twice under different `question_id` values.
- **The `question_id`, `intent` and `notes` columns still make sense** against the
  final question wording — if a question's phrasing was adjusted, check its `intent`
  and `notes` still describe it accurately.
- **A second reviewer reads the completed set** before it is used, consistent with
  the [Human Validation Process](AUDIT_SPECIFICATION.md#13-human-validation-process):
  the question set is itself a piece of consulting work product and benefits from the
  same review discipline as the evidence it will be used to collect.

## Common Mistakes to Avoid

- **Editing the master file directly.** This erodes the library over time and leaves
  no clean template for the next engagement.
- **Leaving a placeholder unreplaced**, most often `[MARKET]` or a `[COMPETITOR_n]`
  value in a question that is easy to skim past.
- **Replacing placeholders inconsistently** — for example, using a brand's full legal
  name in some questions and a shortened or informal name in others, which can affect
  how an AI platform responds.
- **Turning a question back into a keyword search** when adapting it — for example,
  simplifying "How does [BRAND] compare to [COMPETITOR_1] for [CATEGORY]?" down to
  "[BRAND] vs [COMPETITOR_1] [CATEGORY]". This works against the independent query
  methodology's intent to reflect how buyers actually ask AI tools questions.
- **Adding or removing questions per engagement without recording it.** If a
  question genuinely needs to be added or dropped for a specific audit, record this
  as a documented deviation for that engagement, rather than silently diverging from
  the standard set.
- **Treating the library as exhaustive.** It is a representative, reviewed starting
  set, not a claim that every possible buyer question has been covered — see
  [AUDIT_SPECIFICATION.md](AUDIT_SPECIFICATION.md#15-limitations).

## Best Practice for Maintaining the Library Over Time

- **Version the master file deliberately.** Record any change to the master question
  set in [CHANGELOG.md](CHANGELOG.md), rather than editing it silently, so that past
  audits can be understood against the question set that was actually used at the
  time.
- **Keep the CSV as the source of truth.** The `.xlsx` file is provided for ease of
  review and use in spreadsheet tools; if the two ever diverge, the `.csv` should be
  treated as authoritative and the `.xlsx` regenerated from it.
- **Retire, don't silently rewrite, questions that stop working well.** If a question
  consistently produces unusable or malformed results across multiple engagements,
  raise it for review rather than quietly adjusting its wording, so the reason for any
  change is preserved.
- **Review the library periodically against the methodology.** As
  [METHODOLOGY.md](METHODOLOGY.md) or [AUDIT_SPECIFICATION.md](AUDIT_SPECIFICATION.md)
  evolve, check the question set still reflects the current buyer journey framework
  and independent query methodology.
- **Keep questions placeholder-only in the master.** Any engagement-specific, replaced
  version belongs with that engagement's evidence (see
  [data/input/](../data/input/)), never back in the shared master library.

## Buyer Journey Stage Naming

This library's five buyer journey stages (Problem Awareness, Solution Discovery,
Vendor Comparison, Vendor Evaluation, Purchase Decision) are the single buyer journey
framework used across the SignalScope AI project, matching
[AUDIT_SPECIFICATION.md](AUDIT_SPECIFICATION.md#9-buyer-journey-framework).
