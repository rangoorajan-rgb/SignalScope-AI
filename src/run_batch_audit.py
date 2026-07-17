"""Batch Gemini audit runner for SignalScope AI.

Processes every buyer question that does not yet have a Gemini row in
audit_results.csv, sending each remaining question's text to Gemini one at
a time and appending one new row per success immediately. Questions that
already have a Gemini row are skipped, so the script can be safely re-run
to continue where it left off without creating duplicates.

This does not extract brand mentions, competitors, sources, or sentiment,
and does not perform any scoring — those remain future work.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field

from audit_runner import AuditRunnerError, load_questions
from gemini_client import GeminiClientError, generate_response
from write_single_audit_result import (
    WriteAuditResultError,
    build_new_row,
    check_for_duplicate,
    load_existing_results,
    write_results_atomically,
)

DEFAULT_QUESTION_FILE = "audits/boots-uk-health-beauty/buyer_questions.csv"
DEFAULT_RESULTS_FILE = "audits/boots-uk-health-beauty/audit_results.csv"
TARGET_ENGINE = "Gemini"

# Only these HTTP status codes are treated as temporary/retryable. Anything
# else (auth errors, invalid requests, missing API key, empty response,
# etc.) is treated as permanent and is not retried.
RETRYABLE_STATUS_CODES = {"429", "500", "502", "503", "504"}
RETRYABLE_CODE_PATTERN = re.compile(r"\b(" + "|".join(RETRYABLE_STATUS_CODES) + r")\b")

MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = [10, 30]  # delay after attempt 1, then after attempt 2
DEFAULT_REQUEST_DELAY_SECONDS = 5.0


def is_retryable_error(exc: Exception) -> bool:
    """Return True if exc's message contains a retryable HTTP status code."""
    return bool(RETRYABLE_CODE_PATTERN.search(str(exc)))


def generate_with_retry(
    prompt: str,
    question_id: str,
    max_attempts: int = MAX_ATTEMPTS,
    retry_delays: list[float] = RETRY_DELAYS_SECONDS,
    sleep_fn=time.sleep,
) -> str:
    """Call generate_response with retry-on-temporary-error behaviour.

    Retries only when the error looks like a temporary one (429/500/502/
    503/504), up to max_attempts total, waiting retry_delays[i] seconds
    between attempts. Raises the GeminiClientError immediately, with no
    retry, for any other (permanent) error. Raises the last error if all
    attempts are exhausted.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return generate_response(prompt)
        except GeminiClientError as exc:
            if not is_retryable_error(exc) or attempt >= max_attempts:
                raise
            delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
            print(
                f"  [{question_id}] temporary error on attempt {attempt}/{max_attempts}, "
                f"retrying in {delay}s: {exc}"
            )
            sleep_fn(delay)
    raise AssertionError("unreachable")  # pragma: no cover


@dataclass
class BatchResult:
    completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def run_batch_audit(
    question_csv_path: str = DEFAULT_QUESTION_FILE,
    results_csv_path: str = DEFAULT_RESULTS_FILE,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    limit: int | None = None,
    sleep_fn=time.sleep,
) -> BatchResult:
    """Process pending questions (up to `limit`, or all of them) through Gemini.

    Returns a BatchResult with the question_ids completed, skipped (already
    had a Gemini row before this run), and failed (with their error) during
    this run.

    Raises AuditRunnerError or WriteAuditResultError if the question file
    or results file cannot be loaded or fails schema validation — a hard
    stop before any question is processed. Per-question Gemini failures are
    caught, logged, and skipped rather than raised.
    """
    all_questions = load_questions(question_csv_path)
    existing_rows = load_existing_results(results_csv_path)

    completed_ids = {
        row["question_id"] for row in existing_rows if row.get("engine") == TARGET_ENGINE
    }
    pending_count = sum(1 for q in all_questions if q["question_id"] not in completed_ids)

    print(f"Total questions: {len(all_questions)}")
    print(f"Already completed (Gemini): {len(completed_ids)}")
    print(f"Remaining: {pending_count}")
    print()

    to_process_total = pending_count if limit is None else min(limit, pending_count)

    result = BatchResult()
    rows = list(existing_rows)
    pending_seen = 0

    for question_row in all_questions:
        question_id = question_row["question_id"]

        if question_id in completed_ids:
            print(f"{question_id}: SKIPPED (already has a Gemini row)")
            result.skipped.append(question_id)
            continue

        if pending_seen >= to_process_total:
            break

        pending_seen += 1
        print(f"[{pending_seen}/{to_process_total}] {question_id}: processing...")

        try:
            response_text = generate_with_retry(
                question_row["question"], question_id, sleep_fn=sleep_fn
            )
        except GeminiClientError as exc:
            print(f"[{pending_seen}/{to_process_total}] {question_id}: FAILED - {exc}")
            result.failed.append((question_id, str(exc)))
        else:
            check_for_duplicate(rows, question_id, TARGET_ENGINE)
            new_row = build_new_row(question_row, response_text)
            rows.append(new_row)
            write_results_atomically(results_csv_path, rows)
            result.completed.append(question_id)
            print(f"[{pending_seen}/{to_process_total}] {question_id}: SUCCESS")

        if pending_seen < to_process_total:
            sleep_fn(request_delay_seconds)

    print()
    print(f"Completed: {len(result.completed)}")
    print(f"Skipped: {len(result.skipped)}")
    print(f"Failed: {len(result.failed)}")

    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch Gemini audit runner for SignalScope AI.")
    parser.add_argument("--questions", default=DEFAULT_QUESTION_FILE, help="Path to buyer_questions.csv")
    parser.add_argument("--results", default=DEFAULT_RESULTS_FILE, help="Path to audit_results.csv")
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help="Seconds to wait between successful requests (default: 5)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of pending questions to process this run (default: all remaining)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)

    try:
        run_batch_audit(
            question_csv_path=args.questions,
            results_csv_path=args.results,
            request_delay_seconds=args.delay,
            limit=args.limit,
        )
    except (AuditRunnerError, WriteAuditResultError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
