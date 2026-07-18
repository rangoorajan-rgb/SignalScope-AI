"""Tests for src/geo_findings_analyzer.py.

No API calls happen in this module at all. All write tests use temporary
files; the real audits/boots-uk-health-beauty/audit_results.csv is only
ever read, never written to.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from audit_runner import AuditRunnerError  # noqa: E402
from report_generator import ReportGeneratorError  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, WriteAuditResultError  # noqa: E402
from geo_findings_analyzer import (  # noqa: E402
    Finding,
    compute_findings,
    generate_geo_findings,
    render_markdown,
)

REAL_QUESTIONS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
REAL_RESULTS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "audit_results.csv"

FIXED_DATE = date(2026, 7, 17)

FORBIDDEN_RECOMMENDATION_WORDS = ["should", "recommend", "must ", "advise", "suggest"]

# Same fixture as test_report_generator.py's SAMPLE_ROWS (verified arithmetic reused).
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


class ComputeFindingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.findings = compute_findings(SAMPLE_ROWS, total_question_count=40)

    def test_returns_exactly_seven_findings(self) -> None:
        self.assertEqual(len(self.findings), 7)
        for f in self.findings:
            self.assertIsInstance(f, Finding)

    def test_finding_titles_in_order(self) -> None:
        expected_titles = [
            "Overall AI Search Visibility",
            "Brand Mention Frequency",
            "Competitor Dominance",
            "Most Cited Authority Sources",
            "Brand Sentiment Summary",
            "Content Coverage Observations",
            "Overall GEO Maturity Assessment",
        ]
        self.assertEqual([f.title for f in self.findings], expected_titles)

    def test_every_finding_has_all_four_fields_populated(self) -> None:
        for f in self.findings:
            d = asdict(f)
            self.assertEqual(set(d.keys()), {"title", "value", "evidence", "confidence"})
            for key, value in d.items():
                self.assertTrue(value, msg=f"{f.title}.{key} is empty")

    def test_confidence_values_are_valid(self) -> None:
        for f in self.findings:
            self.assertIn(f.confidence, {"High", "Medium", "Low"})

    def test_no_recommendation_language(self) -> None:
        for f in self.findings:
            text = (f.value + " " + f.evidence).lower()
            for word in FORBIDDEN_RECOMMENDATION_WORDS:
                self.assertNotIn(word, text, msg=f"'{word}' found in {f.title}")

    def test_overall_visibility_finding(self) -> None:
        f = self.findings[0]
        self.assertIn("60.0%", f.value)
        self.assertIn("5 response(s)", f.value)
        self.assertIn("6 of 40", f.value)
        self.assertEqual(f.confidence, "Low")  # 6/40 = 15% coverage

    def test_brand_mention_frequency_finding(self) -> None:
        f = self.findings[1]
        self.assertIn("3 of 5", f.value)
        self.assertEqual(f.confidence, "High")  # 5/6 considered = 83%

    def test_competitor_dominance_finding(self) -> None:
        f = self.findings[2]
        self.assertIn("Superdrug", f.value)
        self.assertIn("4 mention(s)", f.value)
        self.assertEqual(f.confidence, "Medium")  # 4/6 = 67%

    def test_authority_sources_finding(self) -> None:
        f = self.findings[3]
        self.assertIn("3 distinct source(s)", f.value)
        self.assertIn("Mintel", f.evidence)
        self.assertEqual(f.confidence, "Medium")  # 3/6 = 50%

    def test_sentiment_summary_finding(self) -> None:
        f = self.findings[4]
        self.assertIn("Positive", f.value)
        self.assertIn("2 of 5", f.value)
        self.assertEqual(f.confidence, "High")  # 5/6 = 83%

    def test_content_coverage_finding(self) -> None:
        f = self.findings[5]
        self.assertIn("4 of 5", f.value)
        self.assertIn("Vendor Comparison", f.value)  # the missing stage is named
        self.assertEqual(f.confidence, "High")  # 4/5 = 80%

    def test_geo_maturity_finding(self) -> None:
        f = self.findings[6]
        self.assertIn("Early", f.value)
        self.assertEqual(f.confidence, "Low")  # 6/40 = 15%

    def test_deterministic_output(self) -> None:
        first = compute_findings(SAMPLE_ROWS, total_question_count=40)
        second = compute_findings(SAMPLE_ROWS, total_question_count=40)
        self.assertEqual(first, second)

    def test_no_competitors_recorded(self) -> None:
        rows = [dict(r, competitors_cited="") for r in SAMPLE_ROWS]
        findings = compute_findings(rows, total_question_count=40)
        f = findings[2]
        self.assertIn("No competitors", f.value)
        self.assertEqual(f.confidence, "Low")

    def test_no_sources_recorded(self) -> None:
        rows = [dict(r, sources_cited="") for r in SAMPLE_ROWS]
        findings = compute_findings(rows, total_question_count=40)
        f = findings[3]
        self.assertIn("No explicit sources", f.value)
        self.assertEqual(f.confidence, "Low")

    def test_no_sentiment_recorded(self) -> None:
        rows = [dict(r, sentiment="") for r in SAMPLE_ROWS]
        findings = compute_findings(rows, total_question_count=40)
        f = findings[4]
        self.assertIn("No sentiment data", f.value)
        self.assertEqual(f.confidence, "Low")

    def test_established_maturity_tier_when_coverage_and_visibility_high(self) -> None:
        # 6 of 8 "library" questions covered (75%), visibility rate 60% (>=50%).
        findings = compute_findings(SAMPLE_ROWS, total_question_count=8)
        f = findings[6]
        self.assertIn("Established", f.value)


class RenderMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.findings = compute_findings(SAMPLE_ROWS, total_question_count=40)
        self.markdown = render_markdown(self.findings, total_rows=6, unique_questions=6, total_question_count=40, generated_at=FIXED_DATE)

    def test_title_present(self) -> None:
        self.assertIn("# SignalScope AI GEO Findings Report — Boots UK Health & Beauty", self.markdown)

    def test_all_headings_present(self) -> None:
        for heading in ["## Report Overview", "## Findings", "## Scope Note"]:
            self.assertIn(heading, self.markdown)

    def test_all_seven_findings_rendered(self) -> None:
        for finding in self.findings:
            self.assertIn(f"**Finding:** {finding.value}", self.markdown)
            self.assertIn(f"**Evidence:** {finding.evidence}", self.markdown)
            self.assertIn(f"**Confidence:** {finding.confidence}", self.markdown)

    def test_no_recommendations_language_in_rendered_output(self) -> None:
        # The scope note must explicitly say there are no recommendations.
        self.assertIn("no recommendations", self.markdown.lower())

    def test_deterministic_rendering(self) -> None:
        first = render_markdown(self.findings, 6, 6, 40, FIXED_DATE)
        second = render_markdown(self.findings, 6, 6, 40, FIXED_DATE)
        self.assertEqual(first, second)

    def test_generation_date_included(self) -> None:
        self.assertIn("2026-07-17", self.markdown)


class GenerateGeoFindingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        self.report_path = self.tmp_path / "reports" / "test-audit" / "GEO_FINDINGS.md"

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
        generate_geo_findings(
            str(self.questions_path), str(self.results_path), str(self.report_path), generated_at=FIXED_DATE
        )
        self.assertTrue(self.report_path.is_file())

    def test_returns_findings_and_markdown(self) -> None:
        findings, markdown = generate_geo_findings(
            str(self.questions_path), str(self.results_path), str(self.report_path), generated_at=FIXED_DATE
        )
        self.assertEqual(len(findings), 7)
        self.assertIn("# SignalScope AI GEO Findings Report", markdown)

    def test_report_written_as_utf8_with_unicode_intact(self) -> None:
        generate_geo_findings(
            str(self.questions_path), str(self.results_path), str(self.report_path), generated_at=FIXED_DATE
        )
        content = self.report_path.read_text(encoding="utf-8")
        # "Estée Lauder" is within the top-5 most-mentioned competitors shown
        # in evidence; "L'Oréal" (6th) is not, so it is not asserted here.
        self.assertIn("Estée Lauder", content)

    def test_missing_questions_file_raises(self) -> None:
        with self.assertRaises(AuditRunnerError):
            generate_geo_findings(str(self.tmp_path / "missing.csv"), str(self.results_path), str(self.report_path))

    def test_missing_results_file_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError):
            generate_geo_findings(str(self.questions_path), str(self.tmp_path / "missing.csv"), str(self.report_path))

    def test_empty_results_file_raises(self) -> None:
        write_results_csv(self.results_path, [])
        with self.assertRaises(ReportGeneratorError):
            generate_geo_findings(str(self.questions_path), str(self.results_path), str(self.report_path))

    def test_invalid_schema_raises(self) -> None:
        write_results_csv(self.results_path, [], fieldnames=RESULTS_SCHEMA[:-1])
        with self.assertRaises(WriteAuditResultError):
            generate_geo_findings(str(self.questions_path), str(self.results_path), str(self.report_path))


class RealBootsIntegrationTests(unittest.TestCase):
    """Reads the real question/results files (never writes to them) and
    writes the findings report to a temp path only."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.report_path = self.tmp_path / "GEO_FINDINGS.md"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_real_data_generates_findings_without_altering_source_files(self) -> None:
        self.assertTrue(REAL_QUESTIONS_FILE.is_file())
        self.assertTrue(REAL_RESULTS_FILE.is_file())

        before_bytes = REAL_RESULTS_FILE.read_bytes()

        findings, markdown = generate_geo_findings(
            str(REAL_QUESTIONS_FILE), str(REAL_RESULTS_FILE), str(self.report_path), generated_at=FIXED_DATE
        )

        self.assertEqual(REAL_RESULTS_FILE.read_bytes(), before_bytes)
        self.assertEqual(len(findings), 7)
        self.assertIn("Boots", markdown)
        self.assertTrue(self.report_path.is_file())


if __name__ == "__main__":
    unittest.main()
