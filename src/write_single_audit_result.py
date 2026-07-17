"""Write a single Gemini audit result into audit_results.csv.

Runs one named question through Gemini and appends exactly one new row to
the existing audit_results.csv, preserving every row already present. This
is a single-question integration only: it does not process the rest of the
question set, extract brand/competitor/source/sentiment information, or
perform any scoring.
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

from audit_runner import AuditRunnerError, load_questions
from gemini_client import GeminiClientError, generate_response
from run_single_audit import RunSingleAuditError, find_question

DEFAULT_QUESTION_FILE = "audits/boots-uk-health-beauty/buyer_questions.csv"
DEFAULT_RESULTS_FILE = "audits/boots-uk-health-beauty/audit_results.csv"
TARGET_QUESTION_ID = "PA01"
TARGET_ENGINE = "Gemini"
MAX_SNIPPET_LENGTH = 500

RESULTS_SCHEMA = [
    "run_date",
    "question_id",
    "question",
    "funnel_stage",
    "engine",
    "brand_cited",
    "brand_position",
    "competitors_cited",
    "sources_cited",
    "sentiment",
    "answer_snippet",
]


class WriteAuditResultError(Exception):
    """Raised for problems specific to writing a single audit result row."""


def load_existing_results(results_path: str) -> list[dict[str, str]]:
    """Load and validate the existing audit_results.csv schema.

    Returns the existing rows (an empty list if the file has a header but
    no data rows yet). Raises WriteAuditResultError if the file is missing
    or its column schema does not match the expected 11 columns, in order,
    exactly.
    """
    path = Path(results_path)
    if not path.is_file():
        raise WriteAuditResultError(f"Audit results file not found: {results_path}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        if fieldnames != RESULTS_SCHEMA:
            raise WriteAuditResultError(
                "Audit results file schema does not match the expected "
                f"11-column schema.\nExpected: {RESULTS_SCHEMA}\nFound:    {fieldnames}"
            )
        rows = list(reader)

    return rows


def check_for_duplicate(
    rows: list[dict[str, str]], question_id: str, engine: str
) -> None:
    """Raise WriteAuditResultError if a row already exists for this
    question_id and engine combination."""
    for row in rows:
        if row.get("question_id") == question_id and row.get("engine") == engine:
            raise WriteAuditResultError(
                f"A row already exists for question_id={question_id} and "
                f"engine={engine}. Refusing to write a duplicate."
            )


def normalise_snippet(text: str, max_length: int = MAX_SNIPPET_LENGTH) -> str:
    """Collapse whitespace/newlines to single spaces and truncate to max_length."""
    single_line = " ".join(text.split())
    return single_line[:max_length]


def build_new_row(question_row: dict[str, str], response_text: str) -> dict[str, str]:
    return {
        "run_date": date.today().isoformat(),
        "question_id": question_row["question_id"],
        "question": question_row["question"],
        "funnel_stage": question_row["buyer_journey_stage"],
        "engine": TARGET_ENGINE,
        "brand_cited": "",
        "brand_position": "",
        "competitors_cited": "",
        "sources_cited": "",
        "sentiment": "",
        "answer_snippet": normalise_snippet(response_text),
    }


def write_results_atomically(results_path: str, rows: list[dict[str, str]]) -> None:
    """Write rows to results_path via a temp file, then atomically replace it."""
    path = Path(results_path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.stem + "_", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULTS_SCHEMA)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        os.replace(tmp_name, str(path))
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def write_single_audit_result(
    question_csv_path: str = DEFAULT_QUESTION_FILE,
    results_csv_path: str = DEFAULT_RESULTS_FILE,
    question_id: str = TARGET_QUESTION_ID,
) -> dict[str, str]:
    """Run question_id through Gemini and append one row to results_csv_path.

    Returns the new row that was written. Existing rows are loaded and
    schema-validated, and a duplicate (question_id, engine) row is rejected,
    *before* Gemini is called, so a rejected or invalid run never spends an
    API call and never touches the results file.

    Raises AuditRunnerError, RunSingleAuditError, WriteAuditResultError, or
    GeminiClientError for the various failure modes.
    """
    questions = load_questions(question_csv_path)
    question_row = find_question(questions, question_id)

    existing_rows = load_existing_results(results_csv_path)
    check_for_duplicate(existing_rows, question_id, TARGET_ENGINE)

    response_text = generate_response(question_row["question"])

    new_row = build_new_row(question_row, response_text)
    write_results_atomically(results_csv_path, existing_rows + [new_row])
    return new_row


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    question_csv_path = argv[0] if len(argv) > 0 else DEFAULT_QUESTION_FILE
    results_csv_path = argv[1] if len(argv) > 1 else DEFAULT_RESULTS_FILE

    try:
        new_row = write_single_audit_result(question_csv_path, results_csv_path)
    except (
        AuditRunnerError,
        RunSingleAuditError,
        GeminiClientError,
        WriteAuditResultError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote new row: question_id={new_row['question_id']} engine={new_row['engine']}")
    print(f"run_date: {new_row['run_date']}")
    print(f"answer_snippet: {new_row['answer_snippet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
