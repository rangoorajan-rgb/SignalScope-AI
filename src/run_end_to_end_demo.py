"""End-to-end acceptance demo for SignalScope AI.

Proves the complete workflow for exactly one pending question, PA05:

    buyer_questions.csv
    -> Gemini answer generation
    -> structured response analysis
    -> safe append to audit_results.csv
    -> regenerate audit_report.md

This is a demonstration and acceptance script, not new product
functionality: every step reuses an existing, already-tested module. It
processes PA05 only and never touches any other question.
"""

from __future__ import annotations

import sys

from audit_config import AuditConfig, AuditConfigError, default_audit_config, parse_audit_arg
from audit_runner import AuditRunnerError, load_questions
from gemini_client import GeminiClientError, generate_response
from response_analyzer import ResponseAnalysisError, analyze_response
from run_single_audit import RunSingleAuditError, find_question
from run_structured_audit import (  # BRAND/KNOWN_COMPETITORS kept as backwards-compatible aliases
    BRAND,
    KNOWN_COMPETITORS,
    TARGET_ENGINE,
    build_structured_row,
)
from write_single_audit_result import (
    WriteAuditResultError,
    check_for_duplicate,
    load_existing_results,
    write_results_atomically,
)
from report_generator import generate_report

_DEFAULT_AUDIT_CONFIG = default_audit_config()

DEFAULT_QUESTION_FILE = _DEFAULT_AUDIT_CONFIG.questions_file
DEFAULT_RESULTS_FILE = _DEFAULT_AUDIT_CONFIG.results_file
DEFAULT_REPORT_FILE = _DEFAULT_AUDIT_CONFIG.audit_report_file
TARGET_QUESTION_ID = "PA05"


class ReportRegenerationFailed(Exception):
    """Raised when the audit row was written successfully but the report
    could not be regenerated afterwards. The CSV write is NOT rolled back:
    the caller must be told the row succeeded even though this failed."""

    def __init__(self, new_row: dict[str, str], cause: Exception) -> None:
        self.new_row = new_row
        self.cause = cause
        super().__init__(
            f"Audit row for {new_row['question_id']} was written successfully, "
            f"but report regeneration failed: {cause}"
        )


def run_end_to_end_demo(
    question_csv_path: str | None = None,
    results_csv_path: str | None = None,
    report_path: str | None = None,
    question_id: str = TARGET_QUESTION_ID,
    brand: str | None = None,
    known_competitors: list[str] | None = None,
    *,
    audit_config: AuditConfig | None = None,
) -> dict[str, str]:
    """Run the full PA05 demo workflow and return the new audit row.

    audit_config defaults to the default audit. Any path, brand, or
    known_competitors left as None is taken from it (an explicitly passed
    value always wins), and it is passed on to the report regeneration.
    With neither audit_config nor known_competitors given, the
    module-level KNOWN_COMPETITORS is used, as in v2.0.

    Order of operations, each a hard stop before anything irreversible:
      1. Load questions and locate question_id.
      2. Load existing results, validate schema, reject a duplicate
         (question_id, engine) row — before any API call is made.
      3. Generate the Gemini answer.
      4. Analyse it into structured fields.
      5. Append exactly one row to audit_results.csv (atomic write).
      6. Regenerate audit_report.md from the updated results.

    Raises AuditRunnerError, RunSingleAuditError, WriteAuditResultError,
    GeminiClientError, or ResponseAnalysisError if the failure happens
    before step 5 — in every one of those cases neither the CSV nor the
    report has been touched. Raises ReportRegenerationFailed if step 5
    succeeded but step 6 failed: the CSV has already been updated by
    that point, and the exception says so explicitly.
    """
    if known_competitors is None and audit_config is None:
        # v2.0 default: the module-level KNOWN_COMPETITORS list itself.
        known_competitors = KNOWN_COMPETITORS
    audit_config = audit_config or _DEFAULT_AUDIT_CONFIG
    if question_csv_path is None:
        question_csv_path = audit_config.questions_file
    if results_csv_path is None:
        results_csv_path = audit_config.results_file
    if report_path is None:
        report_path = audit_config.audit_report_file
    if brand is None:
        brand = audit_config.brand
    if known_competitors is None:
        known_competitors = list(audit_config.competitors)

    questions = load_questions(question_csv_path)
    question_row = find_question(questions, question_id)

    existing_rows = load_existing_results(results_csv_path)
    check_for_duplicate(existing_rows, question_id, TARGET_ENGINE)

    response_text = generate_response(question_row["question"])
    if not response_text or not response_text.strip():
        raise GeminiClientError("Gemini API returned an empty response.")

    analysis = analyze_response(response_text, brand, known_competitors)

    new_row = build_structured_row(question_row, response_text, analysis)

    # Nothing has been written to disk before this point, so any failure
    # above leaves both the CSV and the report completely unchanged.
    write_results_atomically(results_csv_path, existing_rows + [new_row])

    # The row is now safely on disk. A failure from here on must not be
    # swallowed or mistaken for "nothing happened" — it is reported as a
    # distinct, explicit partial-success condition.
    try:
        generate_report(question_csv_path, results_csv_path, report_path, audit_config=audit_config)
    except Exception as exc:
        raise ReportRegenerationFailed(new_row, exc) from exc

    return new_row


def _print_summary(
    new_row: dict[str, str], results_csv_path: str, report_path: str
) -> None:
    print("SignalScope AI - End-to-End Demo Complete")
    print("=" * 42)
    print(f"Question processed: {new_row['question_id']} ({new_row['funnel_stage']})")
    print(f"Question: {new_row['question']}")
    print(f"Engine: {new_row['engine']}")
    print(f"brand_cited: {new_row['brand_cited']}")
    print(f"brand_position: {new_row['brand_position'] or '(blank)'}")
    print(f"competitors_cited: {new_row['competitors_cited'] or '(none)'}")
    print(f"sources_cited: {new_row['sources_cited'] or '(none)'}")
    print(f"sentiment: {new_row['sentiment']}")
    print(f"answer_snippet: {new_row['answer_snippet']}")
    print()
    print(f"Audit results updated: {results_csv_path}")
    print(f"Report regenerated: {report_path}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        audit_config, argv = parse_audit_arg(argv)
    except AuditConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    paths = audit_config or _DEFAULT_AUDIT_CONFIG
    question_csv_path = argv[0] if len(argv) > 0 else paths.questions_file
    results_csv_path = argv[1] if len(argv) > 1 else paths.results_file
    report_path = argv[2] if len(argv) > 2 else paths.audit_report_file

    try:
        new_row = run_end_to_end_demo(
            question_csv_path, results_csv_path, report_path, audit_config=audit_config
        )
    except ReportRegenerationFailed as exc:
        print(f"Partial success: {exc}", file=sys.stderr)
        print(
            f"The audit row for {exc.new_row['question_id']} WAS written to "
            f"{results_csv_path}, but the report at {report_path} could not be "
            "regenerated. Re-run report_generator.py directly once the "
            "underlying issue is fixed.",
            file=sys.stderr,
        )
        return 1
    except (
        AuditRunnerError,
        RunSingleAuditError,
        WriteAuditResultError,
        GeminiClientError,
        ResponseAnalysisError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # e.g. an OS-level CSV-writing failure
        print(f"Error: unexpected failure: {exc}", file=sys.stderr)
        return 1

    _print_summary(new_row, results_csv_path, report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
