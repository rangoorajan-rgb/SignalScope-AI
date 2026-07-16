# Current Sprint

## Sprint 1 — Audit Specification

**Status:** In progress

**Objective:** Define the consulting specification for Build 1 of the SignalScope AI
audit — what an audit assesses, for whom, and against what criteria — independent of
any implementation technology.

### Scope of this sprint

- Write [docs/AUDIT_SPECIFICATION.md](docs/AUDIT_SPECIFICATION.md), covering the
  business rationale, audit objective, scope, target markets, buyer personas,
  competitor selection, buyer journey framework, methodology, the four-dimensional
  scoring framework (Visibility, Prominence, Authority, Sentiment), human validation,
  governance, limitations, planned outputs and success criteria.

### Explicitly out of scope for this sprint

- Any implementation detail, code, or API documentation.
- Any Python files or notebooks.
- Precise numeric scoring formulae or thresholds (flagged within the specification as
  a Build 1 implementation decision, not fixed here).
- Any real or sample client data or audit results.

### Definition of done

- `docs/AUDIT_SPECIFICATION.md` exists and covers all required sections.
- No functionality or technical implementation is claimed to exist beyond what has
  actually been written.
- Nothing in this sprint has been committed to version control; that remains a
  separate, explicit action for the project owner.

### Next sprint (provisional)

Not yet planned. Sprint 2 will be scoped once the audit specification in Sprint 1 has
been reviewed and agreed.

---

## Sprint 0 — Project Foundation

**Status:** Complete

**Objective:** Establish the professional project foundation for SignalScope AI before
any application logic, data pipelines or AI integrations are built.

### Scope of this sprint

- Create the top-level repository structure (`docs/`, `data/`, `prompts/`, `src/`,
  `tests/`).
- Write foundational documentation:
  - [README.md](README.md)
  - [docs/PROJECT_SCOPE.md](docs/PROJECT_SCOPE.md)
  - [docs/METHODOLOGY.md](docs/METHODOLOGY.md)
  - [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)
  - [docs/CHANGELOG.md](docs/CHANGELOG.md)
  - [docs/decisions/ADR-001-Project-Principles.md](docs/decisions/ADR-001-Project-Principles.md)
- Establish a starter `.gitignore`, using common Python patterns as an illustrative
  placeholder only — no language decision has been made (see the "Technology Roadmap"
  section of [README.md](README.md)).
- Record engineering principles as an Architecture Decision Record.

### Explicitly out of scope for this sprint

- Any application or workflow logic.
- Any package installation or dependency management.
- Any Python files or notebooks.
- Any AI prompt design or scoring implementation.
- Any real or sample client data.

### Definition of done

- All files and folders listed above exist and are populated with accurate,
  non-speculative content.
- No functionality is claimed to exist beyond what has actually been created.
- Nothing in this sprint has been committed to version control; that remains a
  separate, explicit action for the project owner.
