"""Basic audit runner for SignalScope AI.

Loads a buyer question file for an audit instance, validates its shape, and
prints each question in a human-readable format. This is the first working
layer of the runner: it loads and displays questions only. It does not query
any AI platform, score anything, or produce a report.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REQUIRED_COLUMNS = ["question_id", "buyer_journey_stage", "question"]

DEFAULT_QUESTION_FILE = "audits/boots-uk-health-beauty/buyer_questions.csv"


class AuditRunnerError(Exception):
    """Raised when a buyer question file cannot be loaded or is invalid."""


def load_questions(csv_path: str) -> list[dict[str, str]]:
    """Load and validate buyer questions from a buyer_questions.csv file.

    Returns the question rows as a list of dicts, in file order.

    Raises AuditRunnerError if the file is missing, is missing one or more
    required columns, or contains no question rows.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise AuditRunnerError(f"Buyer question file not found: {csv_path}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise AuditRunnerError(
                "Buyer question file is missing required column(s): "
                + ", ".join(missing)
            )
        rows = list(reader)

    if not rows:
        raise AuditRunnerError(f"Buyer question file has no question rows: {csv_path}")

    return rows


def print_questions(rows: list[dict[str, str]]) -> None:
    """Print each question, then the total number of questions loaded."""
    for row in rows:
        print(f"[{row['question_id']}] {row['buyer_journey_stage']}")
        print(row["question"])
        print()
    print(f"Total questions loaded: {len(rows)}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    csv_path = argv[0] if argv else DEFAULT_QUESTION_FILE

    try:
        rows = load_questions(csv_path)
    except AuditRunnerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print_questions(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
