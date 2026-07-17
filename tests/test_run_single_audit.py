"""Tests for src/run_single_audit.py.

No real API calls are made: generate_response is mocked throughout.
"""

from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from audit_runner import AuditRunnerError  # noqa: E402
from gemini_client import GeminiClientError  # noqa: E402
import run_single_audit  # noqa: E402
from run_single_audit import (  # noqa: E402
    RunSingleAuditError,
    find_question,
    main,
    run_single_audit as run_single_audit_fn,
)

REAL_BOOTS_QUESTION_FILE = (
    REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
)

SAMPLE_ROWS = [
    {"question_id": "PA01", "buyer_journey_stage": "Problem Awareness", "question": "What are the challenges?"},
    {"question_id": "SD01", "buyer_journey_stage": "Solution Discovery", "question": "What are the options?"},
]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["question_id", "buyer_journey_stage", "question", "intent", "notes"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{"intent": "", "notes": ""}, **row})


class FindQuestionTests(unittest.TestCase):
    def test_finds_matching_question(self) -> None:
        row = find_question(SAMPLE_ROWS, "SD01")
        self.assertEqual(row["question"], "What are the options?")

    def test_raises_when_not_found(self) -> None:
        with self.assertRaises(RunSingleAuditError) as ctx:
            find_question(SAMPLE_ROWS, "PD08")
        self.assertIn("PD08", str(ctx.exception))


class RunSingleAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_single_audit.generate_response")
    def test_success_returns_question_row_and_response(self, mock_generate) -> None:
        mock_generate.return_value = "Mocked Gemini answer."
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(csv_path, SAMPLE_ROWS)

        question_row, response_text = run_single_audit_fn(str(csv_path), "PA01")

        self.assertEqual(question_row["question_id"], "PA01")
        self.assertEqual(response_text, "Mocked Gemini answer.")
        mock_generate.assert_called_once_with("What are the challenges?")

    def test_missing_csv_raises_audit_runner_error(self) -> None:
        missing_path = self.tmp_path / "does_not_exist.csv"
        with self.assertRaises(AuditRunnerError):
            run_single_audit_fn(str(missing_path), "PA01")

    def test_missing_question_id_raises(self) -> None:
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(csv_path, SAMPLE_ROWS)

        with self.assertRaises(RunSingleAuditError):
            run_single_audit_fn(str(csv_path), "PD08")

    @patch("run_single_audit.generate_response")
    def test_gemini_client_error_propagates(self, mock_generate) -> None:
        mock_generate.side_effect = GeminiClientError("GEMINI_API_KEY is not set.")
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(csv_path, SAMPLE_ROWS)

        with self.assertRaises(GeminiClientError):
            run_single_audit_fn(str(csv_path), "PA01")


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_single_audit.generate_response")
    def test_main_prints_expected_format_and_returns_0(self, mock_generate) -> None:
        mock_generate.return_value = "Mocked Gemini answer."
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(csv_path, SAMPLE_ROWS)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main([str(csv_path), "PA01"])
        output = buffer.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("Question ID: PA01", output)
        self.assertIn("Buyer Journey Stage: Problem Awareness", output)
        self.assertIn("Question: What are the challenges?", output)
        self.assertIn("Gemini Response:", output)
        self.assertIn("Mocked Gemini answer.", output)

    def test_main_missing_file_returns_1(self) -> None:
        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main(["does/not/exist.csv", "PA01"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr_buffer.getvalue())

    def test_main_question_id_not_found_returns_1(self) -> None:
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(csv_path, SAMPLE_ROWS)

        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main([str(csv_path), "PD08"])

        self.assertEqual(exit_code, 1)
        self.assertIn("PD08", stderr_buffer.getvalue())

    @patch("run_single_audit.generate_response")
    def test_main_gemini_error_returns_1(self, mock_generate) -> None:
        mock_generate.side_effect = GeminiClientError("GEMINI_API_KEY is not set.")
        csv_path = self.tmp_path / "buyer_questions.csv"
        write_csv(csv_path, SAMPLE_ROWS)

        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main([str(csv_path), "PA01"])

        self.assertEqual(exit_code, 1)
        self.assertIn("GEMINI_API_KEY", stderr_buffer.getvalue())


class RealBootsPA01Tests(unittest.TestCase):
    """Integration check against the real Boots question file (mocked Gemini call)."""

    @patch("run_single_audit.generate_response")
    def test_real_pa01_loaded_and_sent_to_gemini(self, mock_generate) -> None:
        self.assertTrue(
            REAL_BOOTS_QUESTION_FILE.is_file(),
            f"Expected fixture file at {REAL_BOOTS_QUESTION_FILE}",
        )
        mock_generate.return_value = "Mocked Gemini answer."

        question_row, response_text = run_single_audit_fn(str(REAL_BOOTS_QUESTION_FILE), "PA01")

        self.assertEqual(question_row["question_id"], "PA01")
        self.assertEqual(question_row["buyer_journey_stage"], "Problem Awareness")
        self.assertEqual(response_text, "Mocked Gemini answer.")
        mock_generate.assert_called_once_with(question_row["question"])


if __name__ == "__main__":
    unittest.main()
