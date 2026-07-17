"""Tests for src/run_batch_audit.py.

No real API calls are made (generate_response is mocked throughout), no
real sleeping happens (sleep_fn is a no-op recorder), and the real
audits/boots-uk-health-beauty/audit_results.csv is never written to.
"""

from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from audit_runner import AuditRunnerError  # noqa: E402
from gemini_client import GeminiClientError  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, WriteAuditResultError  # noqa: E402
import run_batch_audit as rba  # noqa: E402
from run_batch_audit import (  # noqa: E402
    is_retryable_error,
    generate_with_retry,
    run_batch_audit,
    parse_args,
    main,
)

REAL_BOOTS_QUESTION_FILE = (
    REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
)

QUESTION_ROWS = [
    {"question_id": "PA01", "buyer_journey_stage": "Problem Awareness", "question": "Q1?", "intent": "", "notes": ""},
    {"question_id": "PA02", "buyer_journey_stage": "Problem Awareness", "question": "Q2?", "intent": "", "notes": ""},
    {"question_id": "PA03", "buyer_journey_stage": "Problem Awareness", "question": "Q3?", "intent": "", "notes": ""},
    {"question_id": "PA04", "buyer_journey_stage": "Problem Awareness", "question": "Q4?", "intent": "", "notes": ""},
    {"question_id": "PA05", "buyer_journey_stage": "Problem Awareness", "question": "Q5?", "intent": "", "notes": ""},
]

# PA01 already has both a manual Perplexity row and a Gemini row (simulating
# the post-Sprint-8 state); PA02-PA05 are pending.
EXISTING_RESULT_ROWS = [
    {
        "run_date": "2026-07-17", "question_id": "PA01", "question": "Q1?",
        "funnel_stage": "Problem Awareness", "engine": "Perplexity",
        "brand_cited": "N", "brand_position": "", "competitors_cited": "Grocery chains",
        "sources_cited": "Mintel", "sentiment": "Neutral",
        "answer_snippet": "UK retailers are squeezed by cost sensitivity.",
    },
    {
        "run_date": "2026-07-17", "question_id": "PA01", "question": "Q1?",
        "funnel_stage": "Problem Awareness", "engine": "Gemini",
        "brand_cited": "", "brand_position": "", "competitors_cited": "",
        "sources_cited": "", "sentiment": "",
        "answer_snippet": "Already completed by an earlier Gemini run.",
    },
]


def write_questions_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["question_id", "buyer_journey_stage", "question", "intent", "notes"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_results_csv(
    path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None
) -> None:
    fieldnames = fieldnames or RESULTS_SCHEMA
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_results_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


class RecordingSleep:
    """A no-op sleep_fn that records the delays it was called with."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class IsRetryableErrorTests(unittest.TestCase):
    def test_retryable_codes_detected(self) -> None:
        for code in ("429", "500", "502", "503", "504"):
            exc = GeminiClientError(f"Gemini API call failed: {code} SOME_STATUS. {{...}}")
            self.assertTrue(is_retryable_error(exc), msg=f"code {code} should be retryable")

    def test_non_retryable_errors(self) -> None:
        non_retryable = [
            GeminiClientError("Gemini API call failed: 400 INVALID_ARGUMENT. {...}"),
            GeminiClientError("Gemini API call failed: 401 UNAUTHENTICATED. {...}"),
            GeminiClientError("GEMINI_API_KEY is not set. Create a .env file..."),
            GeminiClientError("Gemini API returned an empty response."),
        ]
        for exc in non_retryable:
            self.assertFalse(is_retryable_error(exc), msg=f"should not be retryable: {exc}")

    def test_does_not_false_positive_on_embedded_digits(self) -> None:
        # "1500" contains "500" as a substring but not as a whole number.
        exc = GeminiClientError("Gemini API call failed: request took 1500ms")
        self.assertFalse(is_retryable_error(exc))


class GenerateWithRetryTests(unittest.TestCase):
    @patch("run_batch_audit.generate_response")
    def test_success_first_attempt_no_sleep(self, mock_generate) -> None:
        mock_generate.return_value = "OK"
        sleep = RecordingSleep()

        result = generate_with_retry("prompt", "PA02", sleep_fn=sleep)

        self.assertEqual(result, "OK")
        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(sleep.calls, [])

    @patch("run_batch_audit.generate_response")
    def test_temporary_error_then_success(self, mock_generate) -> None:
        mock_generate.side_effect = [
            GeminiClientError("Gemini API call failed: 503 UNAVAILABLE. {...}"),
            "Recovered answer.",
        ]
        sleep = RecordingSleep()

        result = generate_with_retry("prompt", "PA02", sleep_fn=sleep)

        self.assertEqual(result, "Recovered answer.")
        self.assertEqual(mock_generate.call_count, 2)
        self.assertEqual(sleep.calls, [10])

    @patch("run_batch_audit.generate_response")
    def test_temporary_error_exhausts_retries(self, mock_generate) -> None:
        error = GeminiClientError("Gemini API call failed: 503 UNAVAILABLE. {...}")
        mock_generate.side_effect = [error, error, error]
        sleep = RecordingSleep()

        with self.assertRaises(GeminiClientError):
            generate_with_retry("prompt", "PA02", sleep_fn=sleep)

        self.assertEqual(mock_generate.call_count, 3)
        self.assertEqual(sleep.calls, [10, 30])

    @patch("run_batch_audit.generate_response")
    def test_permanent_error_not_retried(self, mock_generate) -> None:
        mock_generate.side_effect = GeminiClientError(
            "Gemini API call failed: 400 INVALID_ARGUMENT. {...}"
        )
        sleep = RecordingSleep()

        with self.assertRaises(GeminiClientError):
            generate_with_retry("prompt", "PA02", sleep_fn=sleep)

        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(sleep.calls, [])


class RunBatchAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        write_questions_csv(self.questions_path, QUESTION_ROWS)
        write_results_csv(self.results_path, EXISTING_RESULT_ROWS)
        self.sleep = RecordingSleep()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_batch_audit.generate_response")
    def test_processes_multiple_pending_questions(self, mock_generate) -> None:
        mock_generate.side_effect = lambda prompt: f"Answer to {prompt}"

        result = run_batch_audit(
            str(self.questions_path), str(self.results_path), sleep_fn=self.sleep
        )

        self.assertEqual(result.completed, ["PA02", "PA03", "PA04", "PA05"])
        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 6)  # 2 existing + 4 new

    @patch("run_batch_audit.generate_response")
    def test_skips_existing_gemini_row(self, mock_generate) -> None:
        mock_generate.side_effect = lambda prompt: f"Answer to {prompt}"

        result = run_batch_audit(
            str(self.questions_path), str(self.results_path), sleep_fn=self.sleep
        )

        self.assertEqual(result.skipped, ["PA01"])
        called_prompts = [c.args[0] for c in mock_generate.call_args_list]
        self.assertNotIn("Q1?", called_prompts)

    @patch("run_batch_audit.generate_response")
    def test_no_duplicates_on_rerun(self, mock_generate) -> None:
        mock_generate.side_effect = lambda prompt: f"Answer to {prompt}"

        first_result = run_batch_audit(
            str(self.questions_path), str(self.results_path), sleep_fn=self.sleep
        )
        self.assertEqual(len(first_result.completed), 4)

        mock_generate.reset_mock()
        second_result = run_batch_audit(
            str(self.questions_path), str(self.results_path), sleep_fn=self.sleep
        )

        self.assertEqual(second_result.completed, [])
        self.assertEqual(set(second_result.skipped), {"PA01", "PA02", "PA03", "PA04", "PA05"})
        mock_generate.assert_not_called()

        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 6)  # still only 6, not 10

    @patch("run_batch_audit.generate_response")
    def test_existing_rows_preserved_unchanged(self, mock_generate) -> None:
        mock_generate.side_effect = lambda prompt: f"Answer to {prompt}"

        run_batch_audit(str(self.questions_path), str(self.results_path), sleep_fn=self.sleep)

        rows_after = read_results_csv(self.results_path)
        for original, after in zip(EXISTING_RESULT_ROWS, rows_after[:2]):
            self.assertEqual(original, after)

    @patch("run_batch_audit.generate_response")
    def test_temporary_error_then_success_within_batch(self, mock_generate) -> None:
        mock_generate.side_effect = [
            GeminiClientError("Gemini API call failed: 503 UNAVAILABLE. {...}"),
            "Recovered answer for PA02.",
        ]

        result = run_batch_audit(
            str(self.questions_path), str(self.results_path), limit=1, sleep_fn=self.sleep
        )

        self.assertEqual(result.completed, ["PA02"])
        self.assertEqual(result.failed, [])
        self.assertIn(10, self.sleep.calls)  # the retry delay happened

    @patch("run_batch_audit.generate_response")
    def test_temporary_error_exhausts_retries_within_batch(self, mock_generate) -> None:
        error = GeminiClientError("Gemini API call failed: 503 UNAVAILABLE. {...}")
        mock_generate.side_effect = [error, error, error]

        result = run_batch_audit(
            str(self.questions_path), str(self.results_path), limit=1, sleep_fn=self.sleep
        )

        self.assertEqual(result.completed, [])
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0][0], "PA02")
        self.assertEqual(self.sleep.calls, [10, 30])

        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 2)  # unchanged: no row written for a failure

    @patch("run_batch_audit.generate_response")
    def test_permanent_error_no_retry_within_batch(self, mock_generate) -> None:
        mock_generate.side_effect = GeminiClientError(
            "Gemini API call failed: 400 INVALID_ARGUMENT. {...}"
        )

        result = run_batch_audit(
            str(self.questions_path), str(self.results_path), limit=1, sleep_fn=self.sleep
        )

        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(result.failed[0][0], "PA02")

    @patch("run_batch_audit.generate_response")
    def test_one_failed_question_does_not_stop_later_questions(self, mock_generate) -> None:
        def side_effect(prompt: str) -> str:
            if prompt == "Q2?":
                raise GeminiClientError("Gemini API call failed: 400 INVALID_ARGUMENT. {...}")
            return f"Answer to {prompt}"

        mock_generate.side_effect = side_effect

        result = run_batch_audit(
            str(self.questions_path), str(self.results_path), sleep_fn=self.sleep
        )

        self.assertEqual(result.completed, ["PA03", "PA04", "PA05"])
        self.assertEqual([qid for qid, _ in result.failed], ["PA02"])

        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 5)  # 2 existing + 3 successful

    @patch("run_batch_audit.generate_response")
    def test_answer_normalisation_and_500_char_limit(self, mock_generate) -> None:
        long_multiline_answer = "Paragraph one.\n\n" + ("word " * 200) + "\nEnd."
        mock_generate.return_value = long_multiline_answer

        run_batch_audit(
            str(self.questions_path), str(self.results_path), limit=1, sleep_fn=self.sleep
        )

        rows_after = read_results_csv(self.results_path)
        new_row = rows_after[-1]
        self.assertNotIn("\n", new_row["answer_snippet"])
        self.assertLessEqual(len(new_row["answer_snippet"]), 500)

    @patch("run_batch_audit.generate_response")
    def test_configurable_request_delay(self, mock_generate) -> None:
        mock_generate.side_effect = lambda prompt: f"Answer to {prompt}"

        run_batch_audit(
            str(self.questions_path),
            str(self.results_path),
            request_delay_seconds=7,
            limit=2,
            sleep_fn=self.sleep,
        )

        # Delay happens between successes, not after the very last one in this batch.
        self.assertEqual(self.sleep.calls, [7])

    @patch("run_batch_audit.generate_response")
    def test_limit_processes_only_n_pending(self, mock_generate) -> None:
        mock_generate.side_effect = lambda prompt: f"Answer to {prompt}"

        result = run_batch_audit(
            str(self.questions_path), str(self.results_path), limit=2, sleep_fn=self.sleep
        )

        self.assertEqual(result.completed, ["PA02", "PA03"])
        self.assertEqual(mock_generate.call_count, 2)
        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 4)  # 2 existing + 2 new

    def test_missing_questions_file_raises(self) -> None:
        with self.assertRaises(AuditRunnerError):
            run_batch_audit(
                str(self.tmp_path / "missing.csv"), str(self.results_path), sleep_fn=self.sleep
            )

    def test_missing_results_file_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError):
            run_batch_audit(
                str(self.questions_path), str(self.tmp_path / "missing.csv"), sleep_fn=self.sleep
            )

    def test_invalid_results_schema_raises_and_nothing_called(self) -> None:
        write_results_csv(self.results_path, [], fieldnames=RESULTS_SCHEMA[:-1])

        with patch("run_batch_audit.generate_response") as mock_generate:
            with self.assertRaises(WriteAuditResultError):
                run_batch_audit(
                    str(self.questions_path), str(self.results_path), sleep_fn=self.sleep
                )
            mock_generate.assert_not_called()


class ParseArgsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        args = parse_args([])
        self.assertEqual(args.delay, 5.0)
        self.assertIsNone(args.limit)

    def test_custom_delay_and_limit(self) -> None:
        args = parse_args(["--delay", "10", "--limit", "2"])
        self.assertEqual(args.delay, 10.0)
        self.assertEqual(args.limit, 2)


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        write_questions_csv(self.questions_path, QUESTION_ROWS)
        write_results_csv(self.results_path, EXISTING_RESULT_ROWS)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_batch_audit.time.sleep")
    @patch("run_batch_audit.generate_response")
    def test_main_success_returns_0(self, mock_generate, mock_sleep) -> None:
        mock_generate.side_effect = lambda prompt: f"Answer to {prompt}"

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(
                [
                    "--questions", str(self.questions_path),
                    "--results", str(self.results_path),
                    "--limit", "1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("PA02", buffer.getvalue())

    def test_main_missing_file_returns_1(self) -> None:
        exit_code = main(["--questions", "does/not/exist.csv", "--results", str(self.results_path)])
        self.assertEqual(exit_code, 1)


class RealBootsIntegrationTests(unittest.TestCase):
    """Uses the real buyer_questions.csv (read-only) with a synthetic results file."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.results_path = self.tmp_path / "audit_results.csv"
        # Simulate PA01 already completed via Gemini, nothing else done.
        write_results_csv(
            self.results_path,
            [
                {
                    "run_date": "2026-07-17", "question_id": "PA01", "question": "real q",
                    "funnel_stage": "Problem Awareness", "engine": "Gemini",
                    "brand_cited": "", "brand_position": "", "competitors_cited": "",
                    "sources_cited": "", "sentiment": "", "answer_snippet": "done already",
                }
            ],
        )
        self.sleep = RecordingSleep()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_batch_audit.generate_response")
    def test_pilot_of_two_skips_pa01_and_picks_next_two(self, mock_generate) -> None:
        self.assertTrue(REAL_BOOTS_QUESTION_FILE.is_file())
        mock_generate.side_effect = lambda prompt: f"Mocked answer: {prompt[:20]}"

        result = run_batch_audit(
            str(REAL_BOOTS_QUESTION_FILE),
            str(self.results_path),
            limit=2,
            sleep_fn=self.sleep,
        )

        self.assertIn("PA01", result.skipped)
        self.assertNotIn("PA01", result.completed)
        self.assertEqual(len(result.completed), 2)
        self.assertEqual(result.completed, ["PA02", "PA03"])

        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 3)  # 1 existing + 2 new


if __name__ == "__main__":
    unittest.main()
