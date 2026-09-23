"""First integration between the Audit Runner and Gemini.

Loads an audit's buyer question library, finds a single named question, sends
its natural-language question text to Gemini, and prints the response. This
is a single-question integration only: it does not process the full
question set, save any output to a file, or perform brand detection,
sentiment analysis, or scoring.
"""

from __future__ import annotations

import sys
from pathlib import Path

from audit_config import AuditConfig, AuditConfigError, default_audit_config, parse_audit_arg
from audit_runner import AuditRunnerError, load_questions
from gemini_client import GeminiClientError, generate_response

_DEFAULT_AUDIT_CONFIG = default_audit_config()

DEFAULT_QUESTION_FILE = _DEFAULT_AUDIT_CONFIG.questions_file
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
    csv_path: str | None = None,
    question_id: str = TARGET_QUESTION_ID,
    *,
    audit_config: AuditConfig | None = None,
) -> tuple[dict[str, str], str]:
    """Load one question and get Gemini's response to it.

    Returns (question_row, gemini_response_text). csv_path defaults to the
    question file of audit_config (default: the default audit).

    Raises AuditRunnerError if the question file is missing or invalid,
    RunSingleAuditError if question_id is not found, or GeminiClientError
    for a missing API key, an API failure, or an empty response.
    """
    if csv_path is None:
        csv_path = (audit_config or _DEFAULT_AUDIT_CONFIG).questions_file
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
    try:
        audit_config, argv = parse_audit_arg(argv)
    except AuditConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    paths = audit_config or _DEFAULT_AUDIT_CONFIG
    csv_path = argv[0] if argv else paths.questions_file
    question_id = argv[1] if len(argv) > 1 else TARGET_QUESTION_ID

    try:
        question_row, response_text = run_single_audit(csv_path, question_id, audit_config=audit_config)
    except (AuditRunnerError, RunSingleAuditError, GeminiClientError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print_result(question_row, response_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
