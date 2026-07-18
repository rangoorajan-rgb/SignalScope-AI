"""Tests for src/measurement_engine.py.

Fully deterministic, no API calls at all. All write tests use temporary
files; the real audit dataset is only ever read, never written to.
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
from report_generator import ReportGeneratorError  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, WriteAuditResultError, load_existing_results  # noqa: E402
from geo_findings_analyzer import compute_findings  # noqa: E402
from measurement_engine import (  # noqa: E402
    DECLINED,
    IMPROVED,
    INFORMATIONAL,
    NO_CHANGE,
    MeasurementEngineError,
    Progress,
    _metric_authority_sources,
    compare_audits,
    generate_geo_progress,
    render_markdown,
)

REAL_QUESTIONS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
REAL_RESULTS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "audit_results.csv"

FIXED_DATE = date(2026, 7, 18)


def _row(question_id, funnel_stage, brand_cited, brand_position, competitors_cited, sources_cited, sentiment):
    return {
        "run_date": "2026-07-17",
        "question_id": question_id,
        "question": f"Question for {question_id}?",
        "funnel_stage": funnel_stage,
        "engine": "Gemini",
        "brand_cited": brand_cited,
        "brand_position": brand_position,
        "competitors_cited": competitors_cited,
        "sources_cited": sources_cited,
        "sentiment": sentiment,
        "answer_snippet": "x",
    }


# Baseline: 5 rows, all Problem Awareness, weaker visibility/sentiment/sources.
BASELINE_ROWS = [
    _row("PA01", "Problem Awareness", "Y", "1", "Superdrug", "Mintel", "Positive"),
    _row("PA02", "Problem Awareness", "N", "", "Superdrug; Amazon", "", "Neutral"),
    _row("PA03", "Problem Awareness", "N", "", "", "", "Neutral"),
    _row("PA04", "Problem Awareness", "", "", "", "", ""),
    _row("PA05", "Problem Awareness", "", "", "", "", ""),
]

# Follow-up: 8 rows, covers all 5 stages, stronger visibility/sentiment/sources.
FOLLOWUP_ROWS = [
    _row("PA01", "Problem Awareness", "Y", "1", "Superdrug", "Mintel", "Positive"),
    _row("PA02", "Problem Awareness", "Y", "2", "Amazon", "Mintel", "Positive"),
    _row("PA03", "Problem Awareness", "N", "", "", "", "Neutral"),
    _row("SD01", "Solution Discovery", "Y", "1", "Superdrug", "Retail Economics", "Positive"),
    _row("VC01", "Vendor Comparison", "Y", "1", "", "", "Positive"),
    _row("VE01", "Vendor Evaluation", "Y", "1", "", "Which?", "Neutral"),
    _row("PD01", "Purchase Decision", "N", "", "Amazon", "", "Negative"),
    _row("PA04", "Problem Awareness", "", "", "", "", ""),
]

# All fields blank except question_id/funnel_stage - forces "insufficient data".
INSUFFICIENT_ROWS = [
    _row("PA01", "Problem Awareness", "", "", "", "", ""),
    _row("PA02", "Problem Awareness", "", "", "", "", ""),
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


class CompareAuditsImprovedTests(unittest.TestCase):
    """Baseline (weaker) vs Follow-up (stronger), total_question_count=40."""

    def setUp(self) -> None:
        self.progress = compare_audits(BASELINE_ROWS, FOLLOWUP_ROWS, total_question_count=40, generated_at=FIXED_DATE)
        self.metrics = {m.metric_name: m for m in self.progress.metrics}

    def test_returns_seven_metrics(self) -> None:
        self.assertEqual(len(self.progress.metrics), 7)

    def test_row_and_question_counts(self) -> None:
        self.assertEqual(self.progress.baseline_row_count, 5)
        self.assertEqual(self.progress.followup_row_count, 8)
        self.assertEqual(self.progress.baseline_unique_questions, 5)
        self.assertEqual(self.progress.followup_unique_questions, 8)

    def test_brand_visibility(self) -> None:
        m = self.metrics["Brand Visibility"]
        self.assertEqual(m.before, "33.3%")
        self.assertEqual(m.after, "71.4%")
        self.assertEqual(m.difference, "+38.1pp")
        self.assertEqual(m.direction, IMPROVED)

    def test_brand_mention_frequency(self) -> None:
        m = self.metrics["Brand Mention Frequency"]
        self.assertEqual(m.before, "1")
        self.assertEqual(m.after, "5")
        self.assertEqual(m.difference, "+4")
        self.assertEqual(m.direction, IMPROVED)

    def test_competitor_mention_change_is_informational(self) -> None:
        m = self.metrics["Competitor Mention Change"]
        self.assertEqual(m.before, "3")
        self.assertEqual(m.after, "4")
        self.assertEqual(m.difference, "+1")
        self.assertEqual(m.direction, INFORMATIONAL)

    def test_sentiment_change(self) -> None:
        m = self.metrics["Sentiment Change (Positive Rate)"]
        self.assertEqual(m.before, "33.3%")
        self.assertEqual(m.after, "57.1%")
        self.assertEqual(m.difference, "+23.8pp")
        self.assertEqual(m.direction, IMPROVED)

    def test_authority_source_change(self) -> None:
        m = self.metrics["Authority Source Change"]
        self.assertEqual(m.before, "20.0%")
        self.assertEqual(m.after, "50.0%")
        self.assertEqual(m.difference, "+30.0pp")
        self.assertEqual(m.direction, IMPROVED)

    def test_funnel_stage_coverage(self) -> None:
        m = self.metrics["Funnel Stage Coverage"]
        self.assertEqual(m.before, "1 of 5")
        self.assertEqual(m.after, "5 of 5")
        self.assertEqual(m.difference, "+4")
        self.assertEqual(m.direction, IMPROVED)

    def test_geo_maturity_no_change_at_low_denominator(self) -> None:
        # With total_question_count=40, both 5/40 and 8/40 stay under the
        # 0.40 "Developing" threshold, so both remain "Early".
        m = self.metrics["Overall GEO Maturity"]
        self.assertEqual(m.before, "Early")
        self.assertEqual(m.after, "Early")
        self.assertEqual(m.direction, NO_CHANGE)

    def test_overall_assessment_tallies_correctly(self) -> None:
        # 6 directionally-evaluated metrics: 5 Improved + 1 No Change (maturity); 1 Informational.
        self.assertIn("5 improved", self.progress.overall_assessment)
        self.assertIn("0 declined", self.progress.overall_assessment)
        self.assertIn("1 showed no change", self.progress.overall_assessment)
        self.assertIn("1 metric(s) are reported as informational", self.progress.overall_assessment)


class CompareAuditsDeclinedTests(unittest.TestCase):
    """Same fixtures, reversed: Follow-up rows as baseline, Baseline rows as follow-up."""

    def setUp(self) -> None:
        self.progress = compare_audits(FOLLOWUP_ROWS, BASELINE_ROWS, total_question_count=40, generated_at=FIXED_DATE)
        self.metrics = {m.metric_name: m for m in self.progress.metrics}

    def test_brand_visibility_declined(self) -> None:
        m = self.metrics["Brand Visibility"]
        self.assertEqual(m.before, "71.4%")
        self.assertEqual(m.after, "33.3%")
        self.assertEqual(m.direction, DECLINED)

    def test_funnel_stage_coverage_declined(self) -> None:
        m = self.metrics["Funnel Stage Coverage"]
        self.assertEqual(m.before, "5 of 5")
        self.assertEqual(m.after, "1 of 5")
        self.assertEqual(m.direction, DECLINED)

    def test_competitor_mention_change_still_informational_regardless_of_direction(self) -> None:
        m = self.metrics["Competitor Mention Change"]
        self.assertEqual(m.direction, INFORMATIONAL)


class CompareAuditsNoChangeTests(unittest.TestCase):
    def test_identical_datasets_show_no_change_everywhere(self) -> None:
        progress = compare_audits(BASELINE_ROWS, BASELINE_ROWS, total_question_count=40, generated_at=FIXED_DATE)
        for m in progress.metrics:
            if m.metric_name == "Competitor Mention Change":
                self.assertEqual(m.direction, INFORMATIONAL)
            else:
                self.assertEqual(m.direction, NO_CHANGE, msg=m.metric_name)
            self.assertEqual(m.before, m.after)


class GeoMaturityTierTransitionTests(unittest.TestCase):
    def test_developing_to_established_transition(self) -> None:
        # total_question_count=10: baseline 5/10=0.5 -> Developing (needs >=0.75 AND
        # visibility>=50% for Established; baseline visibility is only 33.3%).
        # follow-up 8/10=0.8 (>=0.75) with visibility 71.4% (>=50%) -> Established.
        progress = compare_audits(BASELINE_ROWS, FOLLOWUP_ROWS, total_question_count=10, generated_at=FIXED_DATE)
        m = {mc.metric_name: mc for mc in progress.metrics}["Overall GEO Maturity"]
        self.assertEqual(m.before, "Developing")
        self.assertEqual(m.after, "Established")
        self.assertEqual(m.difference, "Developing -> Established")
        self.assertEqual(m.direction, IMPROVED)


class InsufficientDataTests(unittest.TestCase):
    def test_visibility_and_sentiment_report_na_not_a_false_direction(self) -> None:
        progress = compare_audits(INSUFFICIENT_ROWS, INSUFFICIENT_ROWS, total_question_count=40, generated_at=FIXED_DATE)
        metrics = {m.metric_name: m for m in progress.metrics}

        visibility = metrics["Brand Visibility"]
        self.assertIn("N/A", visibility.before)
        self.assertIn("N/A", visibility.after)
        self.assertEqual(visibility.direction, NO_CHANGE)

        sentiment = metrics["Sentiment Change (Positive Rate)"]
        self.assertIn("N/A", sentiment.before)
        self.assertEqual(sentiment.direction, NO_CHANGE)

    def test_authority_source_metric_handles_empty_rows_directly(self) -> None:
        # compare_audits() itself rejects empty datasets, so exercise the
        # internal function's own N/A guard directly for full coverage.
        result = _metric_authority_sources([], [])
        self.assertIn("N/A", result.before)
        self.assertEqual(result.direction, NO_CHANGE)


class CompareAuditsErrorTests(unittest.TestCase):
    def test_empty_baseline_raises(self) -> None:
        with self.assertRaises(MeasurementEngineError):
            compare_audits([], FOLLOWUP_ROWS, total_question_count=40)

    def test_empty_followup_raises(self) -> None:
        with self.assertRaises(MeasurementEngineError):
            compare_audits(BASELINE_ROWS, [], total_question_count=40)


class DeterminismTests(unittest.TestCase):
    def test_compare_audits_deterministic(self) -> None:
        first = compare_audits(BASELINE_ROWS, FOLLOWUP_ROWS, total_question_count=40, generated_at=FIXED_DATE)
        second = compare_audits(BASELINE_ROWS, FOLLOWUP_ROWS, total_question_count=40, generated_at=FIXED_DATE)
        self.assertEqual(first, second)

    def test_render_markdown_deterministic(self) -> None:
        progress = compare_audits(BASELINE_ROWS, FOLLOWUP_ROWS, total_question_count=40, generated_at=FIXED_DATE)
        first = render_markdown(progress)
        second = render_markdown(progress)
        self.assertEqual(first, second)


class RenderMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.progress = compare_audits(BASELINE_ROWS, FOLLOWUP_ROWS, total_question_count=40, generated_at=FIXED_DATE)
        self.markdown = render_markdown(self.progress)
        self.validation_markdown = render_markdown(self.progress, is_validation_run=True)

    def test_title_present(self) -> None:
        self.assertIn("# SignalScope AI GEO Progress Report — Boots UK Health & Beauty", self.markdown)

    def test_all_required_sections_present(self) -> None:
        for heading in [
            "## Report Overview",
            "## Executive Summary",
            "## KPI Comparison Table",
            "## Improvement Summary",
            "## Detailed Metrics",
            "## Overall Assessment",
            "## Notes",
        ]:
            self.assertIn(heading, self.markdown)

    def test_kpi_table_lists_all_metrics(self) -> None:
        for m in self.progress.metrics:
            self.assertIn(m.metric_name, self.markdown)

    def test_notes_state_not_guaranteed_outcomes(self) -> None:
        lowered = self.markdown.lower()
        self.assertIn("not guaranteed business outcomes", lowered)

    def test_validation_run_label_present_only_when_flagged(self) -> None:
        self.assertNotIn("Structural validation run", self.markdown)
        self.assertIn("Structural validation run", self.validation_markdown)
        self.assertIn("requires a real", self.validation_markdown.lower() and self.validation_markdown)


class GenerateGeoProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.baseline_path = self.tmp_path / "baseline_results.csv"
        self.followup_path = self.tmp_path / "followup_results.csv"
        self.report_path = self.tmp_path / "reports" / "GEO_PROGRESS.md"

        with self.questions_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["question_id", "buyer_journey_stage", "question", "intent", "notes"]
            )
            writer.writeheader()
            for qid in ["PA01", "PA02", "PA03", "PA04", "PA05", "SD01", "VC01", "VE01", "PD01"]:
                writer.writerow({"question_id": qid, "buyer_journey_stage": "x", "question": "x", "intent": "", "notes": ""})

        write_results_csv(self.baseline_path, BASELINE_ROWS)
        write_results_csv(self.followup_path, FOLLOWUP_ROWS)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_creates_report_and_returns_progress(self) -> None:
        progress, markdown = generate_geo_progress(
            str(self.baseline_path), str(self.followup_path), str(self.questions_path), str(self.report_path),
            generated_at=FIXED_DATE,
        )
        self.assertTrue(self.report_path.is_file())
        self.assertIsInstance(progress, Progress)
        self.assertIn("# SignalScope AI GEO Progress Report", markdown)

    def test_missing_questions_file_raises(self) -> None:
        with self.assertRaises(AuditRunnerError):
            generate_geo_progress(str(self.baseline_path), str(self.followup_path), str(self.tmp_path / "missing.csv"), str(self.report_path))

    def test_missing_baseline_file_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError):
            generate_geo_progress(str(self.tmp_path / "missing.csv"), str(self.followup_path), str(self.questions_path), str(self.report_path))

    def test_missing_followup_file_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError):
            generate_geo_progress(str(self.baseline_path), str(self.tmp_path / "missing.csv"), str(self.questions_path), str(self.report_path))

    def test_empty_baseline_file_raises(self) -> None:
        write_results_csv(self.baseline_path, [])
        with self.assertRaises(ReportGeneratorError):
            generate_geo_progress(str(self.baseline_path), str(self.followup_path), str(self.questions_path), str(self.report_path))


class RealDataIntegrationTests(unittest.TestCase):
    """Uses the real audit dataset (read-only) as both baseline and
    follow-up - the same self-comparison validation pattern used for the
    live run - and writes the report to a temp path only."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.report_path = self.tmp_path / "GEO_PROGRESS.md"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_self_comparison_on_real_data_shows_no_change(self) -> None:
        self.assertTrue(REAL_RESULTS_FILE.is_file())
        before_bytes = REAL_RESULTS_FILE.read_bytes()

        progress, markdown = generate_geo_progress(
            str(REAL_RESULTS_FILE), str(REAL_RESULTS_FILE),
            str(REAL_QUESTIONS_FILE), str(self.report_path),
            generated_at=FIXED_DATE, is_validation_run=True,
        )

        self.assertEqual(REAL_RESULTS_FILE.read_bytes(), before_bytes)
        for m in progress.metrics:
            if m.metric_name != "Competitor Mention Change":
                self.assertEqual(m.direction, NO_CHANGE, msg=m.metric_name)
        self.assertIn("Structural validation run", markdown)

    def test_real_findings_still_computable_after_progress_run(self) -> None:
        # Confirms the Insights Engine (Sprint 13) still works untouched.
        rows = load_existing_results(str(REAL_RESULTS_FILE))
        findings = compute_findings(rows, 40)
        self.assertEqual(len(findings), 7)


if __name__ == "__main__":
    unittest.main()
