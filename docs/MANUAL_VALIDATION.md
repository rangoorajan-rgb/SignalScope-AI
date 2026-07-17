# Manual Validation — Boots UK Health & Beauty

This document records a manual validation of the SignalScope AI methodology and audit
schema, carried out before any automation, using five representative questions from
the reusable buyer question library, substituted for the Boots UK Health & Beauty
audit instance (see
[audits/boots-uk-health-beauty/buyer_questions.csv](../audits/boots-uk-health-beauty/buyer_questions.csv)).

SignalScope AI is an AI-assisted consulting workflow, not an autonomous AI agent. This
validation was carried out manually, outside this repository's tooling, by a
consultant querying an AI platform directly and recording the observed responses. It
is a record of that manual exercise, not a technical implementation.

## Methodology

- **Platform tested:** Perplexity.
- **Session handling:** a fresh chat was used for every question, consistent with the
  [independent query methodology](METHODOLOGY.md#independent-query-methodology) — no
  question's result was allowed to be shaped by an earlier question in the same
  conversation.
- **Question selection:** five representative questions were selected across the
  buyer journey to validate the methodology before automation.

## Validated Questions

| Question ID | Buyer Journey Stage | Observation |
|---|---|---|
| PA01 | Problem Awareness | The AI understood the category challenges. Boots was not cited, because the question was framed at category level. |
| PA08 | Problem Awareness | The AI explained commercial, operational and regulatory risks, using relevant UK retail examples. |
| SD04 | Solution Discovery | Boots was identified as the leading UK health & beauty retailer, followed by Superdrug and other major competitors. |
| VE04 | Vendor Evaluation | Boots was presented as the more established and reputable brand, while Superdrug was positioned as the stronger value-focused alternative. |
| PD08 | Purchase Decision | Boots was recommended as the default choice for nationwide coverage, with competitors recommended for specific use cases. |

## Conclusion

The manual validation confirmed that:

- the question framework works;
- the audit schema (see
  [audit_results.csv](../audits/boots-uk-health-beauty/audit_results.csv)) captures
  meaningful information;
- AI responses vary by buyer journey stage;
- the methodology is ready for automation.
