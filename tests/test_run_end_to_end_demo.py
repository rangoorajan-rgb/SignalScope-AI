"""Tests for src/run_end_to_end_demo.py.

No real API calls are made (generate_response and analyze_response are
mocked throughout), and all file operations use temporary paths. The real
Boots audit files are never modified.
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
from run_single_audit import RunSingleAuditError  # noqa: E402
from response_analyzer import ResponseAnalysisError  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, WriteAuditResultError  # noqa: E402
from run_end_to_end_demo import (  # noqa: E402
    ReportRegenerationFailed,
    main,
    run_end_to_end_demo,
)

REAL_QUESTIONS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"

QUESTION_ROWS = [
    {"question_id": "PA01", "buyer_journey_stage": "Problem Awareness", "question": "Q1?", "intent": "", "notes": ""},
    {
        "question_id": "PA05", "buyer_journey_stage": "Problem Awareness",
        "question": "What happens if a business ignores the category?", "intent": "", "notes": "",
    },
    {"question_id": "PA06", "buyer_journey_stage": "Problem Awareness", "question": "Q6?", "intent": "", "notes": ""},
]

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

ANALYSIS_RESULT = {
    "brand_cited": "Y",
    "brand_position": 2,
    "competitors_cited": ["Superdrug", "Amazon"],
    "sources_cited": ["Mintel"],
    "sentiment": "Positive",
}


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


class RunEndToEndDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        self.report_path = self.tmp_path / "reports" / "audit_report.md"
        write_questions_csv(self.questions_path, QUESTION_ROWS)
        write_results_csv(self.results_path, EXISTING_RESULT_ROWS)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_successful_complete_workflow(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Boots is a strong player, ahead of Superdrug and Amazon."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        new_row = run_end_to_end_demo(
            str(self.questions_path), str(self.results_path), str(self.report_path)
        )

        self.assertEqual(new_row["question_id"], "PA05")
        self.assertEqual(new_row["engine"], "Gemini")
        self.assertEqual(new_row["brand_cited"], "Y")
        self.assertEqual(new_row["brand_position"], "2")
        self.assertEqual(new_row["competitors_cited"], "Superdrug; Amazon")
        self.assertEqual(new_row["sources_cited"], "Mintel")
        self.assertEqual(new_row["sentiment"], "Positive")

        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 3)  # 2 existing + 1 new
        self.assertTrue(self.report_path.is_file())

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_correct_pa05_selected(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        mock_generate.assert_called_once_with("What happens if a business ignores the category?")

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_existing_rows_preserved(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        rows_after = read_results_csv(self.results_path)
        for original, after in zip(EXISTING_RESULT_ROWS, rows_after[:2]):
            self.assertEqual(original, after)

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_report_regenerated_reflects_new_row(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        content = self.report_path.read_text(encoding="utf-8")
        self.assertIn("PA05", content)
        self.assertIn("Total audit result rows: 3", content)

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_duplicate_pa05_blocked_before_api_call(self, mock_generate, mock_analyze) -> None:
        rows_with_pa05 = EXISTING_RESULT_ROWS + [
            {**EXISTING_RESULT_ROWS[1], "question_id": "PA05", "question": "x"}
        ]
        write_results_csv(self.results_path, rows_with_pa05)
        before_csv_bytes = self.results_path.read_bytes()

        with self.assertRaises(WriteAuditResultError):
            run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        mock_generate.assert_not_called()
        mock_analyze.assert_not_called()
        self.assertEqual(self.results_path.read_bytes(), before_csv_bytes)
        self.assertFalse(self.report_path.exists())

    def test_missing_pa05_raises(self) -> None:
        write_questions_csv(self.questions_path, QUESTION_ROWS[:1])  # only PA01
        with self.assertRaises(RunSingleAuditError):
            run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_generation_failure_leaves_files_unchanged(self, mock_generate, mock_analyze) -> None:
        mock_generate.side_effect = GeminiClientError("Gemini API call failed: 503 UNAVAILABLE.")
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(GeminiClientError):
            run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        mock_analyze.assert_not_called()
        self.assertEqual(self.results_path.read_bytes(), before_bytes)
        self.assertFalse(self.report_path.exists())

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_analysis_failure_leaves_files_unchanged(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.side_effect = ResponseAnalysisError("Gemini analysis returned malformed JSON.")
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(ResponseAnalysisError):
            run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        self.assertEqual(self.results_path.read_bytes(), before_bytes)
        self.assertFalse(self.report_path.exists())

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_csv_writing_failure_prevents_report_generation(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        with patch("run_end_to_end_demo.write_results_atomically", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        self.assertFalse(self.report_path.exists())

    @patch("run_end_to_end_demo.generate_report")
    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_report_generation_failure_reported_clearly(
        self, mock_generate, mock_analyze, mock_generate_report
    ) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)
        mock_generate_report.side_effect = RuntimeError("disk full while writing report")

        with self.assertRaises(ReportRegenerationFailed) as ctx:
            run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        self.assertEqual(ctx.exception.new_row["question_id"], "PA05")
        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 3)  # the CSV row WAS written despite the report failure

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_answer_snippet_one_line_and_max_500_chars(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Paragraph one.\n\n" + ("word " * 200) + "\nEnd."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        new_row = run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        self.assertNotIn("\n", new_row["answer_snippet"])
        self.assertLessEqual(len(new_row["answer_snippet"]), 500)

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_no_unexpected_question_processed(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        run_end_to_end_demo(str(self.questions_path), str(self.results_path), str(self.report_path))

        rows_after = read_results_csv(self.results_path)
        question_ids = {r["question_id"] for r in rows_after}
        self.assertEqual(question_ids, {"PA01", "PA05"})
        self.assertNotIn("PA06", question_ids)


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        self.report_path = self.tmp_path / "audit_report.md"
        write_questions_csv(self.questions_path, QUESTION_ROWS)
        write_results_csv(self.results_path, EXISTING_RESULT_ROWS)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_main_success_returns_0(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main([str(self.questions_path), str(self.results_path), str(self.report_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("PA05", buffer.getvalue())

    def test_main_duplicate_returns_nonzero_with_clear_message(self) -> None:
        rows_with_pa05 = EXISTING_RESULT_ROWS + [
            {**EXISTING_RESULT_ROWS[1], "question_id": "PA05", "question": "x"}
        ]
        write_results_csv(self.results_path, rows_with_pa05)

        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main([str(self.questions_path), str(self.results_path), str(self.report_path)])

        self.assertNotEqual(exit_code, 0)
        self.assertIn("PA05", stderr_buffer.getvalue())

    @patch("run_end_to_end_demo.generate_report")
    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_main_report_failure_reports_partial_success(
        self, mock_generate, mock_analyze, mock_generate_report
    ) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)
        mock_generate_report.side_effect = RuntimeError("boom")

        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main([str(self.questions_path), str(self.results_path), str(self.report_path)])

        self.assertNotEqual(exit_code, 0)
        stderr_text = stderr_buffer.getvalue()
        self.assertIn("PA05", stderr_text)
        self.assertIn("report", stderr_text.lower())


class RealBootsIntegrationTests(unittest.TestCase):
    """Uses the real buyer_questions.csv (read-only) with temp results/report paths."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.results_path = self.tmp_path / "audit_results.csv"
        self.report_path = self.tmp_path / "audit_report.md"
        write_results_csv(self.results_path, [])

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_real_pa05_found_and_processed(self, mock_generate, mock_analyze) -> None:
        self.assertTrue(REAL_QUESTIONS_FILE.is_file())
        mock_generate.return_value = "Answer text."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        new_row = run_end_to_end_demo(str(REAL_QUESTIONS_FILE), str(self.results_path), str(self.report_path))

        self.assertEqual(new_row["question_id"], "PA05")
        self.assertEqual(new_row["funnel_stage"], "Problem Awareness")


if __name__ == "__main__":
    unittest.main()
