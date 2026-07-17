"""Tests for src/report_generator.py.

No API calls happen in this module at all. All write tests use temporary
files; the real audits/boots-uk-health-beauty/audit_results.csv is only
ever read, never written to.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from audit_runner import AuditRunnerError  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, WriteAuditResultError  # noqa: E402
import report_generator as rg  # noqa: E402
from report_generator import (  # noqa: E402
    ReportGeneratorError,
    compute_brand_position,
    compute_brand_visibility,
    compute_engine_coverage,
    compute_mention_frequency,
    compute_sentiment_summary,
    compute_stage_coverage,
    generate_report,
    generate_report_markdown,
    load_audit_rows,
)

REAL_QUESTIONS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
REAL_RESULTS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "audit_results.csv"

FIXED_DATE = date(2026, 7, 17)

# A deliberately varied fixture: blanks, valid/invalid positions, repeated
# and unicode competitors, mixed sentiments, some sources, some not.
SAMPLE_ROWS = [
    {
        "run_date": "2026-07-17", "question_id": "PA01", "question": "Q1?",
        "funnel_stage": "Problem Awareness", "engine": "Perplexity",
        "brand_cited": "N", "brand_position": "", "competitors_cited": "Grocery chains; Discounters",
        "sources_cited": "Mintel", "sentiment": "Neutral",
        "answer_snippet": "UK retailers are squeezed by cost sensitivity.",
    },
    {
        "run_date": "2026-07-17", "question_id": "SD04", "question": "Q2?",
        "funnel_stage": "Solution Discovery", "engine": "Perplexity",
        "brand_cited": "Y", "brand_position": "1", "competitors_cited": "Superdrug; Grocery chains",
        "sources_cited": "Mintel; Retail Economics", "sentiment": "Positive",
        "answer_snippet": "Boots and Superdrug lead the market.",
    },
    {
        "run_date": "2026-07-17", "question_id": "VE04", "question": "Q3?",
        "funnel_stage": "Vendor Evaluation", "engine": "Perplexity",
        "brand_cited": "Y", "brand_position": "1", "competitors_cited": "Superdrug",
        "sources_cited": "Which?", "sentiment": "Positive",
        "answer_snippet": "Boots is the more established, heritage brand.",
    },
    {
        "run_date": "2026-07-17", "question_id": "PA02", "question": "Q4?",
        "funnel_stage": "Problem Awareness", "engine": "Gemini",
        "brand_cited": "", "brand_position": "", "competitors_cited": "",
        "sources_cited": "", "sentiment": "",
        "answer_snippet": "Category-level answer with no structured analysis yet.",
    },
    {
        "run_date": "2026-07-17", "question_id": "PA04", "question": "Q5?",
        "funnel_stage": "Problem Awareness", "engine": "Gemini",
        "brand_cited": "N", "brand_position": "", "competitors_cited": "L'Oréal; Estée Lauder; Superdrug",
        "sources_cited": "", "sentiment": "Neutral",
        "answer_snippet": "Category-level discussion mentioning several unrelated brands.",
    },
    {
        "run_date": "2026-07-17", "question_id": "PD01", "question": "Q6?",
        "funnel_stage": "Purchase Decision", "engine": "Gemini",
        "brand_cited": "Y", "brand_position": "2", "competitors_cited": "Superdrug; Amazon",
        "sources_cited": "", "sentiment": "Negative",
        "answer_snippet": "Boots trails Superdrug in this specific comparison.",
    },
]


def write_results_csv(
    path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None
) -> None:
    fieldnames = fieldnames or RESULTS_SCHEMA
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class ComputeHelperTests(unittest.TestCase):
    def test_engine_coverage_counts(self) -> None:
        counts = compute_engine_coverage(SAMPLE_ROWS)
        self.assertEqual(counts["Perplexity"], 3)
        self.assertEqual(counts["Gemini"], 3)

    def test_stage_coverage_counts(self) -> None:
        counts = compute_stage_coverage(SAMPLE_ROWS)
        self.assertEqual(counts["Problem Awareness"], 3)
        self.assertEqual(counts["Solution Discovery"], 1)
        self.assertEqual(counts["Vendor Evaluation"], 1)
        self.assertEqual(counts["Purchase Decision"], 1)

    def test_brand_visibility_excludes_blanks(self) -> None:
        result = compute_brand_visibility(SAMPLE_ROWS)
        # 5 rows have Y/N (PA01=N, SD04=Y, VE04=Y, PA04=N, PD01=Y); PA02 is blank.
        self.assertEqual(result["y"], 3)
        self.assertEqual(result["n"], 2)
        self.assertEqual(result["considered"], 5)
        self.assertEqual(result["excluded"], 1)
        self.assertAlmostEqual(result["rate"], 60.0)

    def test_brand_position_numeric_only(self) -> None:
        result = compute_brand_position(SAMPLE_ROWS)
        # Valid positions: SD04=1, VE04=1, PD01=2 -> 3 values, avg=4/3, best=1
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["best"], 1)
        self.assertAlmostEqual(result["average"], (1 + 1 + 2) / 3)

    def test_brand_position_insufficient_data(self) -> None:
        rows = [dict(r, brand_position="") for r in SAMPLE_ROWS]
        result = compute_brand_position(rows)
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["average"])
        self.assertIsNone(result["best"])

    def test_sentiment_counts_exclude_blanks(self) -> None:
        result = compute_sentiment_summary(SAMPLE_ROWS)
        self.assertEqual(result["positive"], 2)
        self.assertEqual(result["neutral"], 2)
        self.assertEqual(result["negative"], 1)
        self.assertEqual(result["excluded"], 1)  # PA02 blank

    def test_competitor_frequency_dedup_and_sort(self) -> None:
        result = compute_mention_frequency(SAMPLE_ROWS, "competitors_cited")
        result_dict = dict(result)
        self.assertEqual(result_dict["Superdrug"], 4)  # SD04, VE04, PA04, PD01
        self.assertEqual(result_dict["Grocery chains"], 2)  # PA01, SD04
        self.assertEqual(result_dict["Amazon"], 1)
        self.assertEqual(result_dict["Discounters"], 1)
        # Sorted by frequency desc, then alpha: Superdrug(4) first.
        self.assertEqual(result[0], ("Superdrug", 4))

    def test_source_frequency_dedup_and_sort(self) -> None:
        result = compute_mention_frequency(SAMPLE_ROWS, "sources_cited")
        result_dict = dict(result)
        self.assertEqual(result_dict["Mintel"], 2)  # PA01, SD04
        self.assertEqual(result_dict["Retail Economics"], 1)
        self.assertEqual(result_dict["Which?"], 1)

    def test_no_sources_returns_empty(self) -> None:
        rows = [dict(r, sources_cited="") for r in SAMPLE_ROWS]
        result = compute_mention_frequency(rows, "sources_cited")
        self.assertEqual(result, [])


class GenerateReportMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.markdown = generate_report_markdown(SAMPLE_ROWS, FIXED_DATE, total_question_count=40)

    def test_title_present(self) -> None:
        self.assertIn("# SignalScope AI Audit Report — Boots UK Health & Beauty", self.markdown)

    def test_all_expected_headings_present(self) -> None:
        expected_headings = [
            "## Audit Overview",
            "## Executive Summary",
            "## Coverage by Engine",
            "## Coverage by Buyer Journey Stage",
            "## Brand Visibility",
            "## Brand Position",
            "## Sentiment Summary",
            "## Competitors Mentioned",
            "## Sources Mentioned",
            "## Question-Level Findings",
            "## Limitations",
            "## Next Step",
        ]
        for heading in expected_headings:
            self.assertIn(heading, self.markdown)

    def test_overview_fields(self) -> None:
        self.assertIn("- Brand: Boots", self.markdown)
        self.assertIn("- Market: United Kingdom", self.markdown)
        self.assertIn("- Category: Health & Beauty Retail", self.markdown)
        self.assertIn("- Total audit result rows: 6", self.markdown)
        self.assertIn("- Number of unique questions represented: 6", self.markdown)
        self.assertIn("- Report generation date: 2026-07-17", self.markdown)

    def test_does_not_claim_all_40_complete(self) -> None:
        self.assertNotIn("all 40 questions", self.markdown.lower())
        self.assertIn("Not all 40 buyer questions have Gemini results yet.", self.markdown)

    def test_engine_counts_in_text(self) -> None:
        self.assertIn("- Perplexity row count: 3", self.markdown)
        self.assertIn("- Gemini row count: 3", self.markdown)

    def test_findings_table_present_with_all_columns(self) -> None:
        self.assertIn(
            "| question_id | funnel_stage | engine | brand_cited | brand_position | "
            "sentiment | competitors_cited | answer_snippet |",
            self.markdown,
        )
        self.assertIn("PA04", self.markdown)
        self.assertIn("L'Oréal", self.markdown)  # unicode preserved

    def test_next_step_exact_text(self) -> None:
        self.assertIn(
            "Complete the remaining structured Gemini audit questions before producing "
            "a final comparative visibility score.",
            self.markdown,
        )

    def test_deterministic_output(self) -> None:
        first = generate_report_markdown(SAMPLE_ROWS, FIXED_DATE, total_question_count=40)
        second = generate_report_markdown(SAMPLE_ROWS, FIXED_DATE, total_question_count=40)
        self.assertEqual(first, second)

    def test_insufficient_position_data_message(self) -> None:
        rows = [dict(r, brand_position="") for r in SAMPLE_ROWS]
        markdown = generate_report_markdown(rows, FIXED_DATE, total_question_count=40)
        self.assertIn("Insufficient data", markdown)


class LoadAuditRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError):
            load_audit_rows(str(self.tmp_path / "missing.csv"))

    def test_empty_file_raises_report_generator_error(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, [])
        with self.assertRaises(ReportGeneratorError):
            load_audit_rows(str(path))

    def test_missing_column_raises(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, [], fieldnames=RESULTS_SCHEMA[:-1])
        with self.assertRaises(WriteAuditResultError):
            load_audit_rows(str(path))

    def test_reordered_columns_raises(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, [], fieldnames=list(reversed(RESULTS_SCHEMA)))
        with self.assertRaises(WriteAuditResultError):
            load_audit_rows(str(path))

    def test_additional_column_raises(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, [], fieldnames=RESULTS_SCHEMA + ["extra"])
        with self.assertRaises(WriteAuditResultError):
            load_audit_rows(str(path))

    def test_valid_rows_load(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, SAMPLE_ROWS)
        rows = load_audit_rows(str(path))
        self.assertEqual(len(rows), 6)


class GenerateReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        self.report_path = self.tmp_path / "reports" / "test-audit" / "audit_report.md"

        with self.questions_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["question_id", "buyer_journey_stage", "question", "intent", "notes"]
            )
            writer.writeheader()
            for qid in ["PA01", "SD04", "VE04", "PA02", "PA04", "PD01"]:
                writer.writerow({"question_id": qid, "buyer_journey_stage": "x", "question": "x", "intent": "", "notes": ""})

        write_results_csv(self.results_path, SAMPLE_ROWS)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_creates_report_directory_and_file(self) -> None:
        self.assertFalse(self.report_path.parent.exists())
        generate_report(
            str(self.questions_path), str(self.results_path), str(self.report_path), generated_at=FIXED_DATE
        )
        self.assertTrue(self.report_path.is_file())

    def test_report_written_as_utf8_with_unicode_intact(self) -> None:
        generate_report(
            str(self.questions_path), str(self.results_path), str(self.report_path), generated_at=FIXED_DATE
        )
        content = self.report_path.read_text(encoding="utf-8")
        self.assertIn("L'Oréal", content)
        self.assertIn("Estée Lauder", content)

    def test_total_question_count_from_real_library_size(self) -> None:
        markdown = generate_report(
            str(self.questions_path), str(self.results_path), str(self.report_path), generated_at=FIXED_DATE
        )
        # The temp questions file has 6 rows, not 40.
        self.assertIn("Not all 6 buyer questions have Gemini results yet.", markdown)

    def test_missing_questions_file_raises(self) -> None:
        with self.assertRaises(AuditRunnerError):
            generate_report(
                str(self.tmp_path / "missing.csv"), str(self.results_path), str(self.report_path)
            )


class RealBootsIntegrationTests(unittest.TestCase):
    """Reads the real question/results files (never writes to them) and
    writes the report to a temp path only."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.report_path = self.tmp_path / "audit_report.md"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_real_data_generates_report_without_altering_source_files(self) -> None:
        self.assertTrue(REAL_QUESTIONS_FILE.is_file())
        self.assertTrue(REAL_RESULTS_FILE.is_file())

        before_bytes = REAL_RESULTS_FILE.read_bytes()

        markdown = generate_report(
            str(REAL_QUESTIONS_FILE), str(REAL_RESULTS_FILE), str(self.report_path), generated_at=FIXED_DATE
        )

        self.assertEqual(REAL_RESULTS_FILE.read_bytes(), before_bytes)
        self.assertIn("# SignalScope AI Audit Report", markdown)
        self.assertIn("Boots", markdown)
        self.assertTrue(self.report_path.is_file())


if __name__ == "__main__":
    unittest.main()
