# SignalScope AI

> **AI Search Visibility & Generative Engine Optimisation (GEO)
> Intelligence Platform**

SignalScope AI is a Python application that helps organisations
understand how their brand is represented within AI-powered search
experiences such as Google Gemini, ChatGPT, Claude and Perplexity. It
automates the collection, analysis and reporting of AI-generated
responses to realistic buyer questions, enabling consultants and
marketing teams to measure brand visibility, competitor presence and
supporting evidence.

------------------------------------------------------------------------

# Table of Contents

-   Overview
-   Business Problem
-   Why I Built This
-   Target Users
-   Key Features
-   Architecture
-   Workflow
-   Repository Structure
-   Technology Stack
-   Installation
-   Configuration
-   Running the Project
-   Running Tests
-   Example Output
-   Design Principles
-   Governance
-   Current Status
-   Roadmap
-   Contributing
-   Author

------------------------------------------------------------------------

# Overview

SignalScope AI is designed to support the emerging discipline of
**Generative Engine Optimisation (GEO)**.

Rather than manually asking dozens of questions across AI assistants and
analysing lengthy responses, SignalScope AI automates the workflow by:

-   Loading buyer questions
-   Querying an AI model
-   Extracting structured insights
-   Recording evidence
-   Producing an executive audit report

The platform is intentionally **human-in-the-loop**. AI performs
structured analysis while consultants remain responsible for
interpreting evidence and making recommendations.

------------------------------------------------------------------------

# Business Problem

Customer search behaviour is changing.

Instead of relying solely on traditional search engines, customers
increasingly ask AI assistants for recommendations before making
purchasing decisions.

Organisations currently have very limited visibility into:

-   Whether their brand is mentioned.
-   How competitors are positioned.
-   Which sources influence AI responses.
-   Whether AI sentiment is favourable.
-   Where GEO improvements should be prioritised.

SignalScope AI provides a repeatable, evidence-based workflow for
measuring these outcomes.

------------------------------------------------------------------------

# Why I Built This

I built SignalScope AI to explore how AI-powered search is changing
digital marketing.

As generative AI becomes part of the customer buying journey, marketers
require new ways to understand how brands appear inside AI-generated
recommendations.

This project combines my interests in:

-   Marketing Operations
-   Growth Marketing
-   AI Automation
-   MarTech
-   Python
-   Data-driven decision making

------------------------------------------------------------------------

# Target Users

-   Marketing consultants
-   GEO / SEO consultants
-   In-house marketing teams
-   Digital agencies
-   Brand strategy teams

------------------------------------------------------------------------

# Key Features

-   Buyer question library
-   Google Gemini integration
-   Structured response analysis
-   Brand visibility detection
-   Competitor identification
-   Source extraction
-   Sentiment classification
-   CSV audit dataset generation
-   Executive Markdown reporting
-   Duplicate protection
-   Automated regression testing

------------------------------------------------------------------------

# Architecture

``` text
Buyer Questions
      │
      ▼
Google Gemini
      │
      ▼
Structured Response Analysis
      │
      ▼
Audit Results (CSV)
      │
      ▼
Executive GEO Report
```

------------------------------------------------------------------------

# Workflow

1.  Load a buyer question.
2.  Generate an AI response.
3.  Analyse the response.
4.  Extract structured marketing insights.
5.  Save the audit record.
6.  Regenerate the executive report.

------------------------------------------------------------------------

# Repository Structure

``` text
SignalScope-AI/
├── audits/
├── docs/
├── questions/
├── reports/
├── src/
├── tests/
├── README.md
├── CURRENT_SPRINT.md
└── requirements.txt
```

------------------------------------------------------------------------

# Technology Stack

-   Python
-   Google Gemini API
-   CSV
-   Markdown
-   unittest

------------------------------------------------------------------------

# Installation

``` bash
git clone https://github.com/rangoorajan-rgb/SignalScope-AI.git
cd SignalScope-AI
pip install -r requirements.txt
```

------------------------------------------------------------------------

# Configuration

Create your environment variables (or local configuration) and provide
your Google Gemini API key before running the application.

------------------------------------------------------------------------

# Running the Project

``` bash
python src/run_end_to_end_demo.py
```

------------------------------------------------------------------------

# Running Tests

``` bash
python -m unittest discover -s tests -v
```

Current status:

-   167 / 167 tests passing

------------------------------------------------------------------------

# Example Output

Each audit records:

  Field            Description
  ---------------- ----------------------------------
  Question ID      Buyer question identifier
  Question         Original buyer question
  AI Engine        AI model used
  Brand Cited      Whether the brand appears
  Brand Position   Relative recommendation position
  Competitors      Competitors mentioned
  Sources          Supporting evidence
  Sentiment        Positive / Neutral / Negative
  Answer Snippet   Summary of the AI response

------------------------------------------------------------------------

# Design Principles

SignalScope AI follows three core principles:

1.  **Evidence First** -- Every insight should be traceable.
2.  **AI Second** -- AI structures evidence rather than inventing
    conclusions.
3.  **Human Judgement Always** -- Consultants remain accountable for
    recommendations.

------------------------------------------------------------------------

# Governance

The methodology is documented within the `docs/` directory, including
architecture decisions, project scope and design rationale.

------------------------------------------------------------------------

# Current Status

**Version 1**

Current capabilities include:

-   Buyer question library
-   AI response generation
-   Structured response analysis
-   Audit dataset generation
-   Executive report generation
-   End-to-end execution
-   Automated testing

------------------------------------------------------------------------

# Roadmap

Potential future enhancements include:

-   Support for additional AI providers
-   Dashboard visualisations
-   PDF report generation
-   Scheduled audits
-   Multi-brand comparison
-   Historical GEO trend analysis

------------------------------------------------------------------------

# Contributing

This project is currently maintained as a personal portfolio project.
Suggestions and feedback are welcome.

------------------------------------------------------------------------

# Author

**Rangoo Rajan**

Marketing Operations • Growth Marketing • AI Automation • MarTech

GitHub: https://github.com/rangoorajan-rgb
