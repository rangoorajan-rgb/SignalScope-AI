"""Tests for src/dashboard_data.py.

No Streamlit dependency needed to run these - this module is plain
Python. All write-adjacent behaviour is read-only; the real audit
dataset is only ever read, never written to.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from write_single_audit_result import RESULTS_SCHEMA, WriteAuditResultError  # noqa: E402
from dashboard_data import (  # noqa: E402
    DashboardSummary,
    build_dashboard_summary,
    list_report_files,
    load_dashboard_rows,
    most_recent_run_date,
    read_markdown_report,
    report_display_title,
)

REAL_RESULTS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "audit_results.csv"
REAL_REPORT_DIR = REPO_ROOT / "reports" / "boots-uk-health-beauty"

SAMPLE_ROWS = [
    {
        "run_date": "2026-07-17", "question_id": "PA01", "question": "Q1?",
        "funnel_stage": "Problem Awareness", "engine": "Perplexity",
        "brand_cited": "Y", "brand_position": "1", "competitors_cited": "Superdrug",
        "sources_cited": "Mintel", "sentiment": "Positive", "answer_snippet": "x",
    },
    {
        "run_date": "2026-07-17", "question_id": "PA02", "question": "Q2?",
        "funnel_stage": "Problem Awareness", "engine": "Gemini",
        "brand_cited": "N", "brand_position": "", "competitors_cited": "",
        "sources_cited": "", "sentiment": "Neutral", "answer_snippet": "x",
    },
    {
        "run_date": "2026-07-17", "question_id": "PA03", "question": "Q3?",
        "funnel_stage": "Problem Awareness", "engine": "Gemini",
        "brand_cited": "", "brand_position": "", "competitors_cited": "",
        "sources_cited": "", "sentiment": "", "answer_snippet": "x",
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


class BuildDashboardSummaryTests(unittest.TestCase):
    def test_counts_real_yn_values_not_true_false(self) -> None:
        # Regression test for the original bug: brand_cited uses "Y"/"N",
        # not "true"/"yes"/"1".
        summary = build_dashboard_summary(SAMPLE_ROWS)

        self.assertIsInstance(summary, DashboardSummary)
        self.assertEqual(summary.total_rows, 3)
        self.assertEqual(summary.brand_mentions, 1)  # only PA01 is "Y"

    def test_citation_rate_excludes_blank_rows(self) -> None:
        summary = build_dashboard_summary(SAMPLE_ROWS)
        # considered = PA01(Y) + PA02(N) = 2; PA03 blank excluded.
        self.assertAlmostEqual(summary.brand_citation_rate, 50.0)

    def test_rows_with_competitors_and_sources(self) -> None:
        summary = build_dashboard_summary(SAMPLE_ROWS)
        self.assertEqual(summary.rows_with_competitors, 1)  # only PA01
        self.assertEqual(summary.rows_with_sources, 1)  # only PA01

    def test_empty_rows_produce_zeroed_summary(self) -> None:
        summary = build_dashboard_summary([])
        self.assertEqual(summary.total_rows, 0)
        self.assertEqual(summary.brand_mentions, 0)
        self.assertIsNone(summary.brand_citation_rate)
        self.assertEqual(summary.rows_with_competitors, 0)
        self.assertEqual(summary.rows_with_sources, 0)


class MostRecentRunDateTests(unittest.TestCase):
    def test_returns_latest_iso_date(self) -> None:
        rows = [
            {"run_date": "2026-07-10"},
            {"run_date": "2026-07-18"},
            {"run_date": "2026-07-15"},
        ]
        self.assertEqual(most_recent_run_date(rows), "2026-07-18")

    def test_ignores_blank_run_dates(self) -> None:
        rows = [{"run_date": ""}, {"run_date": "2026-07-12"}, {"run_date": None}]
        self.assertEqual(most_recent_run_date(rows), "2026-07-12")

    def test_empty_rows_returns_none(self) -> None:
        self.assertIsNone(most_recent_run_date([]))

    def test_all_blank_run_dates_returns_none(self) -> None:
        self.assertIsNone(most_recent_run_date([{"run_date": ""}, {"run_date": ""}]))


class LoadDashboardRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_missing_file_returns_empty_list(self) -> None:
        rows = load_dashboard_rows(self.tmp_path / "does_not_exist.csv")
        self.assertEqual(rows, [])

    def test_empty_but_valid_csv_returns_empty_list(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, [])
        rows = load_dashboard_rows(path)
        self.assertEqual(rows, [])

    def test_valid_file_returns_rows(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, SAMPLE_ROWS)
        rows = load_dashboard_rows(path)
        self.assertEqual(len(rows), 3)

    def test_invalid_schema_still_raises(self) -> None:
        path = self.tmp_path / "audit_results.csv"
        write_results_csv(path, [], fieldnames=RESULTS_SCHEMA[:-1])
        with self.assertRaises(WriteAuditResultError):
            load_dashboard_rows(path)


class ReportDisplayTitleTests(unittest.TestCase):
    def test_known_geo_report_preserves_acronym(self) -> None:
        self.assertEqual(report_display_title("GEO_FINDINGS.md"), "GEO Findings")
        self.assertEqual(report_display_title("GEO_RECOMMENDATIONS.md"), "GEO Recommendations")
        self.assertEqual(report_display_title("GEO_PROGRESS.md"), "GEO Progress")

    def test_known_audit_report_title(self) -> None:
        self.assertEqual(report_display_title("audit_report.md"), "Audit Report")

    def test_unknown_file_falls_back_to_title_case(self) -> None:
        self.assertEqual(report_display_title("some_other_report.md"), "Some Other Report")


class ListReportFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_missing_directory_returns_empty_list(self) -> None:
        self.assertEqual(list_report_files(self.tmp_path / "does_not_exist"), [])

    def test_lists_only_markdown_files_sorted(self) -> None:
        (self.tmp_path / "b_report.md").write_text("b", encoding="utf-8")
        (self.tmp_path / "a_report.md").write_text("a", encoding="utf-8")
        (self.tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

        files = list_report_files(self.tmp_path)

        self.assertEqual([f.name for f in files], ["a_report.md", "b_report.md"])


class ReadMarkdownReportTests(unittest.TestCase):
    def test_missing_file_returns_placeholder(self) -> None:
        result = read_markdown_report("/does/not/exist.md")
        self.assertEqual(result, "Report not available.")

    def test_existing_file_returns_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_text("# Hello", encoding="utf-8")
            self.assertEqual(read_markdown_report(path), "# Hello")


class RealDataIntegrationTests(unittest.TestCase):
    """Reads the real audit dataset and report directory - never writes
    to them."""

    def test_real_audit_results_load_and_summarise(self) -> None:
        self.assertTrue(REAL_RESULTS_FILE.is_file())
        before_bytes = REAL_RESULTS_FILE.read_bytes()

        rows = load_dashboard_rows(REAL_RESULTS_FILE)
        summary = build_dashboard_summary(rows)

        self.assertEqual(REAL_RESULTS_FILE.read_bytes(), before_bytes)
        self.assertGreater(summary.total_rows, 0)
        self.assertGreaterEqual(summary.brand_mentions, 0)

    def test_real_report_directory_lists_expected_files(self) -> None:
        files = list_report_files(REAL_REPORT_DIR)
        names = {f.name for f in files}
        self.assertIn("audit_report.md", names)
        self.assertIn("GEO_FINDINGS.md", names)
        self.assertIn("GEO_RECOMMENDATIONS.md", names)
        self.assertIn("GEO_PROGRESS.md", names)


if __name__ == "__main__":
    unittest.main()
