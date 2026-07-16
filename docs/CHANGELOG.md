# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this
project will adhere to [Semantic Versioning](https://semver.org/) once a first
functional release exists.

## [0.2] — 2026-07-16

### Added

- [AUDIT_SPECIFICATION.md](AUDIT_SPECIFICATION.md): the consulting specification for
  Build 1 of the SignalScope AI audit, covering business rationale, audit objective,
  scope, target markets, buyer personas, competitor selection, the buyer journey
  framework, methodology, the four-dimensional scoring framework (Visibility,
  Prominence, Authority, Sentiment), human validation, governance, limitations,
  planned outputs and success criteria.

No implementation, code, prompts, or numeric scoring formulae were added in this
version — see the specification's own notes on decisions deferred to Build 1.

## [0.1] — 2026-07-16

### Added

- Initial project foundation: repository structure and directories (`docs/`, `data/`,
  `prompts/`, `src/`, `tests/`).
- Core project documentation: [README.md](../README.md),
  [PROJECT_SCOPE.md](PROJECT_SCOPE.md), [METHODOLOGY.md](METHODOLOGY.md),
  [DATA_DICTIONARY.md](DATA_DICTIONARY.md).
- Project governance record:
  [ADR-001-Project-Principles.md](decisions/ADR-001-Project-Principles.md).
- Sprint tracking: [CURRENT_SPRINT.md](../CURRENT_SPRINT.md), covering Sprint 0.
- `.gitignore` with illustrative Python-oriented entries as a starting-point
  placeholder only; no language decision has been made (see the "Technology Roadmap"
  section of [README.md](../README.md)).

No application logic, data, prompts or dependencies were added in this version.
