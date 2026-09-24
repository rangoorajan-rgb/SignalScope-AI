<div align="center">

# 📡 SignalScope AI

### Evidence-Driven Generative Engine Optimisation (GEO) Intelligence Platform

**Measure AI Visibility • Generate Explainable Insights • Prioritise Optimisation • Measure Improvement**

![Version](https://img.shields.io/badge/version-v2.2.0-blue)
![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-484-brightgreen)
![Architecture](https://img.shields.io/badge/architecture-modular-orange)
![Status](https://img.shields.io/badge/status-complete-success)

---

SignalScope AI is an evidence-first GEO intelligence platform that helps organisations understand how Large Language Models (LLMs) such as Google Gemini, ChatGPT and Perplexity represent their brand during AI-powered search experiences.

Instead of attempting to automatically optimise websites, SignalScope AI measures AI visibility, analyses evidence, generates explainable optimisation recommendations and measures improvement over time.

**Version:** 2.2.0

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
- 484 automated tests
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

To set up an audit for another company, see [Creating a New Audit](#creating-a-new-audit).

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

## Project Scope

The bundled demonstration engagement is **Boots UK**, in the Health & Beauty Retail category, within the United Kingdom market, benchmarked against Superdrug, Amazon and Holland & Barrett. It remains the default audit for every command and for the dashboard.

Since v2.1, SignalScope AI provides a **multi-company audit foundation**: the Audit, Insights, Recommendation and Measurement Engines are no longer tied to one company and can run any audit that has its own configuration file. Since v2.2, an operator can create a new client audit workspace with one command (see [Creating a New Audit](#creating-a-new-audit)).

SignalScope AI remains an **operator-assisted audit system, not a SaaS product**. It has no complete structured batch audit across all 40 questions yet, no audit snapshots or history, no scheduled monitoring, no persistent database, no authentication or user accounts, no billing, no client self-service and no client selector in the dashboard.

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
python src/run_batch_audit.py --audit <slug> --limit 5
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
python src/run_batch_audit.py --audit acme-uk-garden --limit 5
```

v2.2 creates the workspace; it does not yet run a complete structured audit across all 40 questions. `run_batch_audit.py` records answers without the structured brand, competitor, source and sentiment fields, and the structured runners each process a single question. Structured batch evidence collection is planned for v2.3.

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
│   ├── run_batch_audit.py           # Batch runner with retry logic
│   ├── run_structured_audit.py      # Single-question structured audit pipeline
│   ├── report_generator.py          # Insights Engine: audit_report.md
│   ├── geo_findings_analyzer.py     # Insights Engine: GEO_FINDINGS.md
│   ├── recommendation_engine.py     # Recommendation Engine: GEO_RECOMMENDATIONS.md
│   ├── measurement_engine.py        # Measurement Engine: GEO_PROGRESS.md
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
│       └── audit_results.csv        # Structured audit evidence (11-column schema)
│
├── reports/
│   └── boots-uk-health-beauty/
│       ├── audit_report.md
│       ├── GEO_FINDINGS.md
│       ├── GEO_RECOMMENDATIONS.md
│       └── GEO_PROGRESS.md
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

The Measurement Engine compares the previous and current audits to identify genuine changes.

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

The project contains **484 automated tests**, including:

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

v2.2 added audit-creation tests: generating the Boots workspace from its configuration and the master template reproduces the committed Boots `audit_config.json` and `buyer_questions.csv` byte for byte, and fictional-client tests cover validation, collision refusal, rollback after injected failures, dry runs, the CLI and immediate `--audit` use. No test calls the Gemini API.

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
- no scheduled monitoring
- no complete structured batch audit across all 40 questions yet (planned for v2.3)
- new audits require exactly three competitors and use the single master question template

Two operational points apply in v2.2:

- **Run commands from the repository root.** `create_audit.py` always writes to the project's own `audits/` folder, but the existing `--audit` runners resolve audit and report paths relative to the current working directory.
- **Leftover staging folders.** A failed or interrupted (Ctrl-C) audit creation cleans up after itself. Only a hard process kill can leave an `audits/.creating-<slug>-*` folder behind; it is not a valid audit and can be deleted manually.

These limitations were accepted in favour of demonstrating software architecture and engineering quality.

---

# Future Roadmap

## Version Roadmap

| Version | Focus | Status |
|---|---|---|
| v2.1 | Multi-company configuration foundation | Released |
| v2.2 | Repeatable client audit creation | This release |
| v2.3 | Structured batch evidence collection | Planned |
| v2.4 | Audit snapshots and longitudinal history | Planned |
| v2.5 | Recurring monitoring workflow | Planned |

Later platform work (database, scheduling, a multi-project interface, authentication and cloud deployment, with billing and client self-service only when justified) is not yet scheduled.

Potential future enhancements include:

## Product

- Interactive web dashboard
- Multi-project management
- Historical trend visualisation
- Scheduled GEO monitoring
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

**SignalScope AI v2.2.0**

*Evidence-Driven Generative Engine Optimisation Intelligence Platform*

Built with Python, AI and a passion for thoughtful software engineering.

</div>

