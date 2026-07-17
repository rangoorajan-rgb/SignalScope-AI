"""Tests for src/write_single_audit_result.py.

No real API calls are made (generate_response is mocked throughout), and
the real audits/boots-uk-health-beauty/audit_results.csv is never written
to — every write test operates on a temp-directory copy.
"""

from __future__ import annotations

import csv
import io
import re
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
import write_single_audit_result as wsar  # noqa: E402
from write_single_audit_result import (  # noqa: E402
    RESULTS_SCHEMA,
    WriteAuditResultError,
    build_new_row,
    check_for_duplicate,
    load_existing_results,
    main,
    normalise_snippet,
    write_single_audit_result,
)

REAL_BOOTS_QUESTION_FILE = (
    REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
)

QUESTION_ROWS = [
    {
        "question_id": "PA01",
        "buyer_journey_stage": "Problem Awareness",
        "question": "What are the challenges?",
        "intent": "",
        "notes": "",
    },
    {
        "question_id": "SD01",
        "buyer_journey_stage": "Solution Discovery",
        "question": "What are the options?",
        "intent": "",
        "notes": "",
    },
]

EXISTING_RESULT_ROWS = [
    {
        "run_date": "2026-07-17",
        "question_id": "PA01",
        "question": "What are the most common challenges, really?",
        "funnel_stage": "Problem Awareness",
        "engine": "Perplexity",
        "brand_cited": "N",
        "brand_position": "",
        "competitors_cited": "Grocery chains; discounters",
        "sources_cited": "Mintel",
        "sentiment": "Neutral",
        "answer_snippet": "UK retailers are squeezed by cost sensitivity.",
    },
    {
        "run_date": "2026-07-17",
        "question_id": "PA08",
        "question": "What are the risks?",
        "funnel_stage": "Problem Awareness",
        "engine": "Perplexity",
        "brand_cited": "N",
        "brand_position": "",
        "competitors_cited": "Bodycare",
        "sources_cited": "Not captured",
        "sentiment": "Neutral",
        "answer_snippet": "Financial, operational, regulatory risks.",
    },
    {
        "run_date": "2026-07-17",
        "question_id": "SD04",
        "question": "Who are the leading companies?",
        "funnel_stage": "Solution Discovery",
        "engine": "Perplexity",
        "brand_cited": "Y",
        "brand_position": "1",
        "competitors_cited": "Superdrug; Tesco",
        "sources_cited": "Not captured",
        "sentiment": "Positive",
        "answer_snippet": "Boots and Superdrug lead the market.",
    },
    {
        "run_date": "2026-07-17",
        "question_id": "VE04",
        "question": "How reputable is Boots?",
        "funnel_stage": "Vendor Evaluation",
        "engine": "Perplexity",
        "brand_cited": "Y",
        "brand_position": "1",
        "competitors_cited": "Superdrug",
        "sources_cited": "Which?",
        "sentiment": "Positive",
        "answer_snippet": "Boots is the more established, heritage brand.",
    },
    {
        "run_date": "2026-07-17",
        "question_id": "PD08",
        "question": "Should I go with Boots?",
        "funnel_stage": "Purchase Decision",
        "engine": "Perplexity",
        "brand_cited": "Y",
        "brand_position": "1",
        "competitors_cited": "Superdrug; Amazon",
        "sources_cited": "Not captured",
        "sentiment": "Positive",
        "answer_snippet": "Boots is usually the best default fit.",
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


class NormaliseSnippetTests(unittest.TestCase):
    def test_collapses_newlines_and_extra_whitespace(self) -> None:
        text = "Line one.\nLine two.\n\n   Line three with  extra   spaces."
        result = normalise_snippet(text)
        self.assertNotIn("\n", result)
        self.assertEqual(
            result, "Line one. Line two. Line three with extra spaces."
        )

    def test_truncates_to_max_length(self) -> None:
        text = "x" * 900
        result = normalise_snippet(text, max_length=500)
        self.assertEqual(len(result), 500)

    def test_short_text_untouched_in_length(self) -> None:
        text = "Short answer."
        result = normalise_snippet(text)
        self.assertEqual(result, "Short answer.")
        self.assertLessEqual(len(result), 500)


class BuildNewRowTests(unittest.TestCase):
    def test_builds_expected_row(self) -> None:
        question_row = QUESTION_ROWS[0]
        row = build_new_row(question_row, "Here is a\nmulti-line answer.")

        self.assertEqual(set(row.keys()), set(RESULTS_SCHEMA))
        self.assertEqual(row["question_id"], "PA01")
        self.assertEqual(row["question"], "What are the challenges?")
        self.assertEqual(row["funnel_stage"], "Problem Awareness")
        self.assertEqual(row["engine"], "Gemini")
        self.assertEqual(row["brand_cited"], "")
        self.assertEqual(row["brand_position"], "")
        self.assertEqual(row["competitors_cited"], "")
        self.assertEqual(row["sources_cited"], "")
        self.assertEqual(row["sentiment"], "")
        self.assertNotIn("\n", row["answer_snippet"])
        self.assertRegex(row["run_date"], r"^\d{4}-\d{2}-\d{2}$")


class LoadExistingResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError) as ctx:
            load_existing_results(str(self.tmp_path / "missing.csv"))
        self.assertIn("not found", str(ctx.exception))

    def test_valid_schema_loads_rows(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, EXISTING_RESULT_ROWS)

        rows = load_existing_results(str(path))
        self.assertEqual(len(rows), 5)

    def test_empty_results_file_loads_zero_rows(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, [])

        rows = load_existing_results(str(path))
        self.assertEqual(rows, [])

    def test_missing_column_raises(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        bad_fieldnames = [c for c in RESULTS_SCHEMA if c != "sentiment"]
        write_results_csv(path, [], fieldnames=bad_fieldnames)

        with self.assertRaises(WriteAuditResultError) as ctx:
            load_existing_results(str(path))
        self.assertIn("schema", str(ctx.exception))

    def test_extra_column_raises(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        bad_fieldnames = RESULTS_SCHEMA + ["extra_column"]
        write_results_csv(path, [], fieldnames=bad_fieldnames)

        with self.assertRaises(WriteAuditResultError):
            load_existing_results(str(path))

    def test_reordered_columns_raises(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        bad_fieldnames = list(reversed(RESULTS_SCHEMA))
        write_results_csv(path, [], fieldnames=bad_fieldnames)

        with self.assertRaises(WriteAuditResultError):
            load_existing_results(str(path))


class CheckForDuplicateTests(unittest.TestCase):
    def test_no_duplicate_passes(self) -> None:
        check_for_duplicate(EXISTING_RESULT_ROWS, "PA01", "Gemini")  # should not raise

    def test_same_question_different_engine_passes(self) -> None:
        # PA01/Perplexity exists; PA01/Gemini must still be allowed.
        check_for_duplicate(EXISTING_RESULT_ROWS, "PA01", "Gemini")

    def test_exact_duplicate_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError) as ctx:
            check_for_duplicate(EXISTING_RESULT_ROWS, "PA01", "Perplexity")
        self.assertIn("PA01", str(ctx.exception))
        self.assertIn("Perplexity", str(ctx.exception))


class WriteSingleAuditResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        write_questions_csv(self.questions_path, QUESTION_ROWS)
        write_results_csv(self.results_path, EXISTING_RESULT_ROWS)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("write_single_audit_result.generate_response")
    def test_successful_append(self, mock_generate) -> None:
        mock_generate.return_value = "Mocked Gemini answer."

        new_row = write_single_audit_result(
            str(self.questions_path), str(self.results_path), "PA01"
        )

        self.assertEqual(new_row["question_id"], "PA01")
        self.assertEqual(new_row["engine"], "Gemini")
        self.assertEqual(new_row["answer_snippet"], "Mocked Gemini answer.")

        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 6)

    @patch("write_single_audit_result.generate_response")
    def test_existing_rows_preserved_unchanged(self, mock_generate) -> None:
        mock_generate.return_value = "Mocked Gemini answer."

        write_single_audit_result(str(self.questions_path), str(self.results_path), "PA01")

        rows_after = read_results_csv(self.results_path)
        original_rows_after = rows_after[:5]
        for original, after in zip(EXISTING_RESULT_ROWS, original_rows_after):
            self.assertEqual(original, after)

    @patch("write_single_audit_result.generate_response")
    def test_appended_row_has_expected_values(self, mock_generate) -> None:
        mock_generate.return_value = "Mocked Gemini answer."

        write_single_audit_result(str(self.questions_path), str(self.results_path), "PA01")

        rows_after = read_results_csv(self.results_path)
        new_row = rows_after[-1]
        self.assertEqual(new_row["question_id"], "PA01")
        self.assertEqual(new_row["funnel_stage"], "Problem Awareness")
        self.assertEqual(new_row["engine"], "Gemini")
        self.assertEqual(new_row["brand_cited"], "")
        self.assertEqual(new_row["brand_position"], "")
        self.assertEqual(new_row["competitors_cited"], "")
        self.assertEqual(new_row["sources_cited"], "")
        self.assertEqual(new_row["sentiment"], "")
        self.assertRegex(new_row["run_date"], r"^\d{4}-\d{2}-\d{2}$")

    @patch("write_single_audit_result.generate_response")
    def test_duplicate_gemini_row_rejected_and_file_untouched(self, mock_generate) -> None:
        # Pre-seed a Gemini/PA01 row so the next attempt is a duplicate.
        rows_with_gemini = EXISTING_RESULT_ROWS + [
            {**EXISTING_RESULT_ROWS[0], "engine": "Gemini", "answer_snippet": "Already here."}
        ]
        write_results_csv(self.results_path, rows_with_gemini)
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(WriteAuditResultError):
            write_single_audit_result(str(self.questions_path), str(self.results_path), "PA01")

        mock_generate.assert_not_called()
        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    def test_missing_question_file_raises_and_results_untouched(self) -> None:
        before_bytes = self.results_path.read_bytes()
        missing_questions = self.tmp_path / "does_not_exist.csv"

        with self.assertRaises(AuditRunnerError):
            write_single_audit_result(str(missing_questions), str(self.results_path), "PA01")

        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    def test_question_id_not_found_raises_and_results_untouched(self) -> None:
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(RunSingleAuditError):
            write_single_audit_result(str(self.questions_path), str(self.results_path), "PD08")

        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    def test_invalid_results_schema_raises_and_results_untouched(self) -> None:
        write_results_csv(self.results_path, [], fieldnames=RESULTS_SCHEMA[:-1])
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(WriteAuditResultError):
            write_single_audit_result(str(self.questions_path), str(self.results_path), "PA01")

        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    @patch("write_single_audit_result.generate_response")
    def test_gemini_failure_raises_and_results_untouched(self, mock_generate) -> None:
        mock_generate.side_effect = GeminiClientError("Gemini API call failed: simulated failure")
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(GeminiClientError):
            write_single_audit_result(str(self.questions_path), str(self.results_path), "PA01")

        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    @patch("write_single_audit_result.generate_response")
    def test_empty_gemini_response_raises_and_results_untouched(self, mock_generate) -> None:
        mock_generate.side_effect = GeminiClientError("Gemini API returned an empty response.")
        before_bytes = self.results_path.read_bytes()

        with self.assertRaises(GeminiClientError) as ctx:
            write_single_audit_result(str(self.questions_path), str(self.results_path), "PA01")

        self.assertIn("empty response", str(ctx.exception))
        self.assertEqual(self.results_path.read_bytes(), before_bytes)

    @patch("write_single_audit_result.generate_response")
    def test_answer_snippet_one_line_and_max_500_chars(self, mock_generate) -> None:
        long_multiline_answer = ("Paragraph one.\n\n" + "word " * 200 + "\nParagraph end.")
        mock_generate.return_value = long_multiline_answer

        write_single_audit_result(str(self.questions_path), str(self.results_path), "PA01")

        rows_after = read_results_csv(self.results_path)
        snippet = rows_after[-1]["answer_snippet"]
        self.assertNotIn("\n", snippet)
        self.assertLessEqual(len(snippet), 500)


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

    @patch("write_single_audit_result.generate_response")
    def test_main_success_returns_0(self, mock_generate) -> None:
        mock_generate.return_value = "Mocked Gemini answer."

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main([str(self.questions_path), str(self.results_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("PA01", buffer.getvalue())
        self.assertEqual(len(read_results_csv(self.results_path)), 6)

    def test_main_missing_questions_file_returns_1(self) -> None:
        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main(["does/not/exist.csv", str(self.results_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("Error:", stderr_buffer.getvalue())


class RealBootsIntegrationTests(unittest.TestCase):
    """Uses the real buyer_questions.csv (read-only) with a temp results file."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.results_path = self.tmp_path / "audit_results.csv"
        write_results_csv(self.results_path, EXISTING_RESULT_ROWS)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("write_single_audit_result.generate_response")
    def test_real_pa01_appends_correctly(self, mock_generate) -> None:
        self.assertTrue(REAL_BOOTS_QUESTION_FILE.is_file())
        mock_generate.return_value = "Mocked Gemini answer for real PA01."

        new_row = write_single_audit_result(
            str(REAL_BOOTS_QUESTION_FILE), str(self.results_path), "PA01"
        )

        self.assertEqual(new_row["question_id"], "PA01")
        self.assertEqual(new_row["funnel_stage"], "Problem Awareness")
        mock_generate.assert_called_once_with(new_row["question"])

        rows_after = read_results_csv(self.results_path)
        self.assertEqual(len(rows_after), 6)


if __name__ == "__main__":
    unittest.main()
