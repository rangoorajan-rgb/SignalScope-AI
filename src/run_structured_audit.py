"""Run a structured Gemini audit for a single question (PA04 pilot).

Generates a full Gemini answer for one named question, analyses it via
response_analyzer.analyze_response() to extract structured fields (brand
citation, position, competitors, sources, sentiment), and appends exactly
one new row to audit_results.csv. This is a controlled, single-question
pilot: it does not touch the batch runner, and it does not process any
other question.
"""

from __future__ import annotations

import sys
from datetime import date

from audit_runner import AuditRunnerError, load_questions
from gemini_client import GeminiClientError, generate_response
from response_analyzer import ResponseAnalysisError, analyze_response
from run_single_audit import RunSingleAuditError, find_question
from write_single_audit_result import (
    WriteAuditResultError,
    check_for_duplicate,
    load_existing_results,
    normalise_snippet,
    write_results_atomically,
)

DEFAULT_QUESTION_FILE = "audits/boots-uk-health-beauty/buyer_questions.csv"
DEFAULT_RESULTS_FILE = "audits/boots-uk-health-beauty/audit_results.csv"
TARGET_QUESTION_ID = "PA04"
TARGET_ENGINE = "Gemini"

BRAND = "Boots"
KNOWN_COMPETITORS = ["Superdrug", "Amazon", "Holland & Barrett"]


def build_structured_row(
    question_row: dict[str, str], response_text: str, analysis: dict
) -> dict[str, str]:
    brand_position = analysis["brand_position"]
    return {
        "run_date": date.today().isoformat(),
        "question_id": question_row["question_id"],
        "question": question_row["question"],
        "funnel_stage": question_row["buyer_journey_stage"],
        "engine": TARGET_ENGINE,
        "brand_cited": analysis["brand_cited"],
        "brand_position": "" if brand_position == "" else str(brand_position),
        "competitors_cited": "; ".join(analysis["competitors_cited"]),
        "sources_cited": "; ".join(analysis["sources_cited"]),
        "sentiment": analysis["sentiment"],
        "answer_snippet": normalise_snippet(response_text),
    }


def run_structured_audit(
    question_csv_path: str = DEFAULT_QUESTION_FILE,
    results_csv_path: str = DEFAULT_RESULTS_FILE,
    question_id: str = TARGET_QUESTION_ID,
    brand: str = BRAND,
    known_competitors: list[str] | None = None,
) -> dict[str, str]:
    """Generate and structurally analyse one question's Gemini answer, then
    append exactly one row to results_csv_path.

    Returns the new row that was written. Existing rows are loaded and
    schema-validated, and a duplicate (question_id, engine) row is
    rejected, *before* Gemini is called, so a rejected or invalid run
    never spends an API call and never touches the results file.

    Raises AuditRunnerError, RunSingleAuditError, WriteAuditResultError,
    GeminiClientError, or ResponseAnalysisError for the various failure
    modes.
    """
    known_competitors = KNOWN_COMPETITORS if known_competitors is None else known_competitors

    questions = load_questions(question_csv_path)
    question_row = find_question(questions, question_id)

    existing_rows = load_existing_results(results_csv_path)
    check_for_duplicate(existing_rows, question_id, TARGET_ENGINE)

    response_text = generate_response(question_row["question"])
    if not response_text or not response_text.strip():
        raise GeminiClientError("Gemini API returned an empty response.")

    analysis = analyze_response(response_text, brand, known_competitors)

    new_row = build_structured_row(question_row, response_text, analysis)
    write_results_atomically(results_csv_path, existing_rows + [new_row])
    return new_row


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    question_csv_path = argv[0] if len(argv) > 0 else DEFAULT_QUESTION_FILE
    results_csv_path = argv[1] if len(argv) > 1 else DEFAULT_RESULTS_FILE

    try:
        new_row = run_structured_audit(question_csv_path, results_csv_path)
    except (
        AuditRunnerError,
        RunSingleAuditError,
        GeminiClientError,
        WriteAuditResultError,
        ResponseAnalysisError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # e.g. an OS-level CSV-writing failure
        print(f"Error: unexpected failure writing audit result: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote structured row: question_id={new_row['question_id']} engine={new_row['engine']}")
    print(f"brand_cited={new_row['brand_cited']}  brand_position={new_row['brand_position']!r}")
    print(f"competitors_cited={new_row['competitors_cited']!r}")
    print(f"sources_cited={new_row['sources_cited']!r}")
    print(f"sentiment={new_row['sentiment']}")
    print(f"answer_snippet={new_row['answer_snippet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
