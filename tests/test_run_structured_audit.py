"""Tests for src/run_structured_audit.py.

No real API calls are made (generate_response and analyze_response are
mocked throughout), and the real audits/boots-uk-health-beauty/
audit_results.csv is never written to.
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
from run_structured_audit import (  # noqa: E402
    BRAND,
    KNOWN_COMPETITORS,
    main,
    run_structured_audit,
)

REAL_BOOTS_QUESTION_FILE = (
    REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
)

QUESTION_ROWS = [
    {"question_id": "PA01", "buyer_journey_stage": "Problem Awareness", "question": "Q1?", "intent": "", "notes": ""},
    {"question_id": "PA04", "buyer_journey_stage": "Problem Awareness", "question": "Is category worth investing in?", "intent": "", "notes": ""},
    {"question_id": "PA05", "buyer_journey_stage": "Problem Awareness", "question": "Q5?", "intent": "", "notes": ""},
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


class RunStructuredAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        write_questions_csv(self.questions_path, QUESTION_ROWS)
        write_results_csv(self.results_path, EXISTING_RESULT_ROWS)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_successful_pa04_append(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Boots is a great option, better than Superdrug and Amazon."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        new_row = run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

        self.assertEqual(new_row["question_id"], "PA04")
        self.assertEqual(new_row["engine"], "Gemini")
        self.assertEqual(new_row["brand_cited"], "Y")
        self.assertEqual(new_row["brand_position"], "2")
        self.assertEqual(new_row["competitors_cited"], "Superdrug; Amazon")
        self.assertEqual(new_row["sources_cited"], "Mintel")
        self.assertEqual(new_row["sentiment"], "Positive")

        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 3)

        mock_analyze.assert_called_once_with(mock_generate.return_value, BRAND, KNOWN_COMPETITORS)

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_blank_brand_position_and_empty_lists_stored_blank(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Some answer."
        mock_analyze.return_value = {
            "brand_cited": "N", "brand_position": "", "competitors_cited": [],
            "sources_cited": [], "sentiment": "Neutral",
        }

        new_row = run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

        self.assertEqual(new_row["brand_position"], "")
        self.assertEqual(new_row["competitors_cited"], "")
        self.assertEqual(new_row["sources_cited"], "")

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_existing_rows_preserved(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

        rows_after = read_results_csv(self.results_path)
        for original, after in zip(EXISTING_RESULT_ROWS, rows_after[:2]):
            self.assertEqual(original, after)

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_duplicate_pa04_rejected_and_file_untouched(self, mock_generate, mock_analyze) -> None:
        rows_with_pa04 = EXISTING_RESULT_ROWS + [
            {**EXISTING_RESULT_ROWS[1], "question_id": "PA04", "question": "Is category worth investing in?"}
        ]
        write_results_csv(self.results_path, rows_with_pa04)
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(WriteAuditResultError):
            run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

        mock_generate.assert_not_called()
        mock_analyze.assert_not_called()
        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_generation_failure_raises_and_no_row_written(self, mock_generate, mock_analyze) -> None:
        mock_generate.side_effect = GeminiClientError("Gemini API call failed: 503 UNAVAILABLE.")
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(GeminiClientError):
            run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

        mock_analyze.assert_not_called()
        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_analysis_failure_raises_and_no_row_written(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Some answer."
        mock_analyze.side_effect = ResponseAnalysisError("Gemini analysis returned malformed JSON.")
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(ResponseAnalysisError):
            run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_empty_generated_answer_raises(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = ""
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(GeminiClientError):
            run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

        mock_analyze.assert_not_called()
        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_answer_snippet_normalised_and_capped(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Line one.\n\n" + ("word " * 200) + "\nEnd."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        new_row = run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

        self.assertNotIn("\n", new_row["answer_snippet"])
        self.assertLessEqual(len(new_row["answer_snippet"]), 500)

    def test_missing_questions_file_raises(self) -> None:
        with self.assertRaises(AuditRunnerError):
            run_structured_audit(str(self.tmp_path / "missing.csv"), str(self.results_path), "PA04")

    def test_missing_results_file_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError):
            run_structured_audit(str(self.questions_path), str(self.tmp_path / "missing.csv"), "PA04")

    def test_invalid_results_schema_raises(self) -> None:
        write_results_csv(self.results_path, [], fieldnames=RESULTS_SCHEMA[:-1])
        with self.assertRaises(WriteAuditResultError):
            run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")

    def test_pa04_not_found_raises(self) -> None:
        write_questions_csv(self.questions_path, QUESTION_ROWS[:1])  # only PA01
        with self.assertRaises(RunSingleAuditError):
            run_structured_audit(str(self.questions_path), str(self.results_path), "PA04")


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

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_main_success_returns_0(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main([str(self.questions_path), str(self.results_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("PA04", buffer.getvalue())

    def test_main_missing_file_returns_1(self) -> None:
        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main(["does/not/exist.csv", str(self.results_path)])
        self.assertEqual(exit_code, 1)


class RealBootsIntegrationTests(unittest.TestCase):
    """Uses the real buyer_questions.csv (read-only) with a temp results file."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.results_path = self.tmp_path / "audit_results.csv"
        write_results_csv(self.results_path, [])

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_real_pa04_found_and_processed(self, mock_generate, mock_analyze) -> None:
        self.assertTrue(REAL_BOOTS_QUESTION_FILE.is_file())
        mock_generate.return_value = "Answer text."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        new_row = run_structured_audit(str(REAL_BOOTS_QUESTION_FILE), str(self.results_path), "PA04")

        self.assertEqual(new_row["question_id"], "PA04")
        self.assertEqual(new_row["funnel_stage"], "Problem Awareness")
        self.assertIn("Health & Beauty Retail", new_row["question"])


if __name__ == "__main__":
    unittest.main()
