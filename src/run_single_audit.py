"""First integration between the Audit Runner and Gemini.

Loads the Boots buyer question library, finds a single named question, sends
its natural-language question text to Gemini, and prints the response. This
is a single-question integration only: it does not process the full
question set, save any output to a file, or perform brand detection,
sentiment analysis, or scoring.
"""

from __future__ import annotations

import sys
from pathlib import Path

from audit_runner import AuditRunnerError, load_questions
from gemini_client import GeminiClientError, generate_response

DEFAULT_QUESTION_FILE = "audits/boots-uk-health-beauty/buyer_questions.csv"
TARGET_QUESTION_ID = "PA01"


class RunSingleAuditError(Exception):
    """Raised for problems specific to running a single audit question."""


def find_question(rows: list[dict[str, str]], question_id: str) -> dict[str, str]:
    """Return the row matching question_id, or raise RunSingleAuditError."""
    for row in rows:
        if row["question_id"] == question_id:
            return row
    raise RunSingleAuditError(f"Question ID not found: {question_id}")


def run_single_audit(
    csv_path: str = DEFAULT_QUESTION_FILE,
    question_id: str = TARGET_QUESTION_ID,
) -> tuple[dict[str, str], str]:
    """Load one question and get Gemini's response to it.

    Returns (question_row, gemini_response_text).

    Raises AuditRunnerError if the question file is missing or invalid,
    RunSingleAuditError if question_id is not found, or GeminiClientError
    for a missing API key, an API failure, or an empty response.
    """
    rows = load_questions(csv_path)
    question_row = find_question(rows, question_id)
    response_text = generate_response(question_row["question"])
    return question_row, response_text


def print_result(question_row: dict[str, str], response_text: str) -> None:
    print(f"Question ID: {question_row['question_id']}")
    print(f"Buyer Journey Stage: {question_row['buyer_journey_stage']}")
    print(f"Question: {question_row['question']}")
    print()
    print("Gemini Response:")
    print(response_text)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    csv_path = argv[0] if argv else DEFAULT_QUESTION_FILE
    question_id = argv[1] if len(argv) > 1 else TARGET_QUESTION_ID

    try:
        question_row, response_text = run_single_audit(csv_path, question_id)
    except (AuditRunnerError, RunSingleAuditError, GeminiClientError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print_result(question_row, response_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
