"""Multi-client configuration tests for SignalScope AI.

Proves that an AuditConfig for a completely fictional client flows through
the core workflow - report, findings, recommendations, measurement,
structured audit and end-to-end demo - with no Boots value leaking into
that client's output, and that the default (no-config) behaviour is still
the Boots audit.

No second client is created under the real audits/ folder: every file is
written to a temporary directory. Gemini is mocked throughout, and the
Gemini SDK client is additionally blocked so that no test can make a real
API call.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import measurement_engine  # noqa: E402
import recommendation_engine  # noqa: E402
import report_generator  # noqa: E402
import run_structured_audit as structured_audit_module  # noqa: E402
from audit_config import AuditConfig, default_audit_config, load_audit_config  # noqa: E402
from audit_runner import load_questions  # noqa: E402
from geo_findings_analyzer import compute_findings, generate_geo_findings  # noqa: E402
from geo_findings_analyzer import render_markdown as render_findings  # noqa: E402
from measurement_engine import generate_geo_progress  # noqa: E402
from recommendation_engine import (  # noqa: E402
    _build_recommendations_prompt,
    generate_geo_recommendations,
)
from report_generator import generate_report, generate_report_markdown, load_audit_rows  # noqa: E402
from run_end_to_end_demo import run_end_to_end_demo  # noqa: E402
from run_structured_audit import run_structured_audit  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA  # noqa: E402

FIXED_DATE = date(2026, 7, 18)

LUMORA = AuditConfig(
    slug="lumora-veloria-tea",
    brand="Lumora",
    company_name="Lumora Tea Co.",
    report_subject="Lumora Tea Co. Specialty Tea",
    market="Republic of Veloria",
    category="Specialty Tea Retail",
    competitors=("Brewvale", "Kettleworth", "Steepwise"),
    question_library="Veloria Tea GEO Library",
)

# Values from the default (Boots) audit that must never appear in the
# fictional client's output. None of these appear in the test data below.
BOOTS_LEAK_MARKERS = [
    "Boots",
    "Boots UK",
    "Superdrug",
    "Amazon",
    "Holland & Barrett",
    "United Kingdom",
    "Health & Beauty",
    "boots-uk-health-beauty",
]

QUESTION_ROWS = [
    {"question_id": "PA04", "buyer_journey_stage": "Problem Awareness",
     "question": "Is Specialty Tea Retail really worth investing in?", "intent": "", "notes": ""},
    {"question_id": "PA05", "buyer_journey_stage": "Problem Awareness",
     "question": "What happens if a business in Republic of Veloria ignores Specialty Tea Retail?",
     "intent": "", "notes": ""},
    {"question_id": "SD01", "buyer_journey_stage": "Solution Discovery",
     "question": "What are the best Specialty Tea Retail options in Republic of Veloria?", "intent": "", "notes": ""},
    {"question_id": "VC01", "buyer_journey_stage": "Vendor Comparison",
     "question": "How does Lumora compare to Brewvale?", "intent": "", "notes": ""},
]


def _row(question_id, stage, brand_cited, position, competitors, sources, sentiment, engine="Gemini"):
    return {
        "run_date": "2026-07-18", "question_id": question_id, "question": f"{question_id}?",
        "funnel_stage": stage, "engine": engine, "brand_cited": brand_cited, "brand_position": position,
        "competitors_cited": competitors, "sources_cited": sources, "sentiment": sentiment,
        "answer_snippet": f"Lumora answer for {question_id}.",
    }


BASELINE_ROWS = [
    _row("SD01", "Solution Discovery", "Y", "2", "Brewvale; Kettleworth", "Veloria Tea Review", "Neutral"),
    _row("VC01", "Vendor Comparison", "N", "", "Brewvale", "", "Neutral"),
]

FOLLOWUP_ROWS = [
    _row("SD01", "Solution Discovery", "Y", "1", "Brewvale", "Veloria Tea Review", "Positive"),
    _row("VC01", "Vendor Comparison", "Y", "1", "Steepwise", "Leaf Journal", "Positive"),
    _row("PA04", "Problem Awareness", "Y", "1", "Kettleworth", "Leaf Journal", "Positive"),
]

ANALYSIS_RESULT = {
    "brand_cited": "Y",
    "brand_position": 1,
    "competitors_cited": ["Brewvale", "Steepwise"],
    "sources_cited": ["Leaf Journal"],
    "sentiment": "Positive",
}


def canned_recommendations_json() -> str:
    return json.dumps([
        {
            "title": "Grow Lumora Citations",
            "problem_addressed": "Lumora is not cited in every response.",
            "recommendation_rationale": "Visibility is below full coverage.",
            "recommended_action": "Publish category guides that name Lumora.",
            "potential_impact": "High",
            "indicative_effort": "Low",
            "success_metric": "Lumora citation rate in the next audit.",
            "source_findings": ["Overall AI Search Visibility"],
        }
    ])


def write_questions_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["question_id", "buyer_journey_stage", "question", "intent", "notes"])
        writer.writeheader()
        writer.writerows(rows)


def write_results_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULTS_SCHEMA)
        writer.writeheader()
        writer.writerows(rows)


class _FictionalClientTestCase(unittest.TestCase):
    """Temp workspace with Lumora question/results files; Gemini SDK blocked;
    the real Boots audit and reports verified unchanged afterwards."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        self.followup_path = self.tmp_path / "followup_results.csv"
        write_questions_csv(self.questions_path, QUESTION_ROWS)
        write_results_csv(self.results_path, BASELINE_ROWS)
        write_results_csv(self.followup_path, FOLLOWUP_ROWS)

        sdk_guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini call attempted"))
        sdk_guard.start()
        self.addCleanup(sdk_guard.stop)

        boots_files = [
            *sorted((REPO_ROOT / "audits" / "boots-uk-health-beauty").iterdir()),
            *sorted((REPO_ROOT / "reports" / "boots-uk-health-beauty").iterdir()),
        ]
        self._boots_snapshot = {p: p.read_bytes() for p in boots_files}
        self.addCleanup(self._assert_boots_untouched)

    def _assert_boots_untouched(self) -> None:
        for path, before in self._boots_snapshot.items():
            self.assertEqual(path.read_bytes(), before, f"Boots file was modified: {path}")

    def assert_no_boots_leak(self, text: str) -> None:
        for marker in BOOTS_LEAK_MARKERS:
            self.assertNotIn(marker, text, f"Boots value {marker!r} leaked into fictional client output")

    def assert_lumora_overview(self, markdown: str, title_prefix: str) -> None:
        self.assertEqual(markdown.splitlines()[0], f"{title_prefix} — Lumora Tea Co. Specialty Tea")
        self.assertIn("- Brand: Lumora", markdown)
        self.assertIn("- Market: Republic of Veloria", markdown)
        self.assertIn("- Category: Specialty Tea Retail", markdown)


class ReportGeneratorMultiClientTests(_FictionalClientTestCase):
    def test_markdown_uses_fictional_config(self) -> None:
        markdown = generate_report_markdown(BASELINE_ROWS, FIXED_DATE, 4, audit_config=LUMORA)
        self.assert_lumora_overview(markdown, "# SignalScope AI Audit Report")
        self.assertIn("- Y (Lumora cited): 1", markdown)
        self.assertIn("- N (Lumora not cited): 1", markdown)
        self.assert_no_boots_leak(markdown)

    def test_compute_overview_uses_fictional_config(self) -> None:
        overview = report_generator.compute_overview(BASELINE_ROWS, FIXED_DATE, audit_config=LUMORA)
        self.assertEqual(
            (overview["brand"], overview["market"], overview["category"]),
            ("Lumora", "Republic of Veloria", "Specialty Tea Retail"),
        )

    def test_generate_report_writes_fictional_report(self) -> None:
        out = self.tmp_path / "audit_report.md"
        markdown = generate_report(
            str(self.questions_path), str(self.results_path), str(out), FIXED_DATE, audit_config=LUMORA
        )
        self.assertEqual(out.read_text(encoding="utf-8"), markdown)
        self.assert_lumora_overview(markdown, "# SignalScope AI Audit Report")
        self.assert_no_boots_leak(markdown)

    def test_calculations_identical_regardless_of_config(self) -> None:
        # Only client-specific labels may differ between configs, never the numbers.
        boots_md = generate_report_markdown(BASELINE_ROWS, FIXED_DATE, 4)
        lumora_md = generate_report_markdown(BASELINE_ROWS, FIXED_DATE, 4, audit_config=LUMORA)
        cfg = default_audit_config()
        normalised = (
            boots_md.replace(cfg.report_subject, LUMORA.report_subject)
            .replace(f"- Market: {cfg.market}", f"- Market: {LUMORA.market}")
            .replace(f"- Category: {cfg.category}", f"- Category: {LUMORA.category}")
            .replace(f"- Brand: {cfg.brand}", f"- Brand: {LUMORA.brand}")
            .replace(f"({cfg.brand} ", f"({LUMORA.brand} ")
        )
        self.assertEqual(normalised, lumora_md)


class GeoFindingsMultiClientTests(_FictionalClientTestCase):
    def test_finding_text_uses_fictional_brand(self) -> None:
        findings = compute_findings(BASELINE_ROWS, 4, audit_config=LUMORA)
        by_title = {f.title: f for f in findings}
        self.assertTrue(by_title["Overall AI Search Visibility"].value.startswith("Lumora was cited in"))
        self.assertTrue(by_title["Brand Mention Frequency"].value.startswith("Lumora was explicitly mentioned"))
        self.assertTrue(by_title["Brand Sentiment Summary"].value.startswith("Sentiment toward Lumora"))
        for f in findings:
            self.assert_no_boots_leak(f.value + f.evidence)

    def test_confidence_and_evidence_unchanged_by_config(self) -> None:
        default_findings = compute_findings(BASELINE_ROWS, 4)
        lumora_findings = compute_findings(BASELINE_ROWS, 4, audit_config=LUMORA)
        self.assertEqual([f.title for f in default_findings], [f.title for f in lumora_findings])
        self.assertEqual([f.confidence for f in default_findings], [f.confidence for f in lumora_findings])
        self.assertEqual([f.evidence for f in default_findings], [f.evidence for f in lumora_findings])

    def test_render_uses_fictional_header(self) -> None:
        findings = compute_findings(BASELINE_ROWS, 4, audit_config=LUMORA)
        markdown = render_findings(findings, 2, 2, 4, FIXED_DATE, audit_config=LUMORA)
        self.assert_lumora_overview(markdown, "# SignalScope AI GEO Findings Report")
        self.assert_no_boots_leak(markdown)

    def test_generate_geo_findings_end_to_end(self) -> None:
        out = self.tmp_path / "GEO_FINDINGS.md"
        findings, markdown = generate_geo_findings(
            str(self.questions_path), str(self.results_path), str(out), FIXED_DATE, audit_config=LUMORA
        )
        self.assertEqual(len(findings), 7)
        self.assertIn("Lumora was cited in", markdown)
        self.assert_lumora_overview(markdown, "# SignalScope AI GEO Findings Report")
        self.assert_no_boots_leak(markdown)
        self.assert_no_boots_leak(out.read_text(encoding="utf-8"))


class RecommendationsMultiClientTests(_FictionalClientTestCase):
    @patch("recommendation_engine.generate_response")
    def test_prompt_and_report_use_fictional_config(self, mock_generate) -> None:
        mock_generate.return_value = canned_recommendations_json()
        out = self.tmp_path / "GEO_RECOMMENDATIONS.md"

        recommendations, markdown = generate_geo_recommendations(
            str(self.questions_path), str(self.results_path), str(out), FIXED_DATE, audit_config=LUMORA
        )

        mock_generate.assert_called_once()
        prompt = mock_generate.call_args.args[0]
        self.assertIn("Brand: Lumora\nMarket: Republic of Veloria\nCategory: Specialty Tea Retail", prompt)
        self.assertIn("Observation: Lumora was cited in", prompt)
        self.assert_no_boots_leak(prompt)

        self.assertEqual(len(recommendations), 1)
        self.assert_lumora_overview(markdown, "# SignalScope AI GEO Recommendations Report")
        self.assert_no_boots_leak(markdown)
        self.assertEqual(out.read_text(encoding="utf-8"), markdown)

    @patch("recommendation_engine.generate_recommendations", wraps=recommendation_engine.generate_recommendations)
    @patch("recommendation_engine.generate_response")
    def test_config_passed_to_generate_recommendations(self, mock_generate, spy) -> None:
        mock_generate.return_value = canned_recommendations_json()
        generate_geo_recommendations(
            str(self.questions_path), str(self.results_path), str(self.tmp_path / "r.md"), FIXED_DATE,
            audit_config=LUMORA,
        )
        args = spy.call_args.args
        self.assertEqual(args[1:], ("Lumora", "Republic of Veloria", "Specialty Tea Retail"))


class MeasurementMultiClientTests(_FictionalClientTestCase):
    @patch("measurement_engine.compare_audits", wraps=measurement_engine.compare_audits)
    def test_generate_geo_progress_passes_config_to_compare_audits(self, spy) -> None:
        out = self.tmp_path / "GEO_PROGRESS.md"
        progress, markdown = generate_geo_progress(
            str(self.results_path), str(self.followup_path), str(self.questions_path), str(out),
            FIXED_DATE, audit_config=LUMORA,
        )

        kwargs = spy.call_args.kwargs
        self.assertEqual(
            (kwargs["brand"], kwargs["market"], kwargs["category"]),
            ("Lumora", "Republic of Veloria", "Specialty Tea Retail"),
        )
        self.assertEqual((progress.brand, progress.market, progress.category), ("Lumora", "Republic of Veloria", "Specialty Tea Retail"))
        self.assert_lumora_overview(markdown, "# SignalScope AI GEO Progress Report")
        self.assert_no_boots_leak(markdown)
        self.assertEqual(out.read_text(encoding="utf-8"), markdown)

    def test_metrics_unchanged_by_config(self) -> None:
        default_progress, _ = generate_geo_progress(
            str(self.results_path), str(self.followup_path), str(self.questions_path),
            str(self.tmp_path / "a.md"), FIXED_DATE,
        )
        lumora_progress, _ = generate_geo_progress(
            str(self.results_path), str(self.followup_path), str(self.questions_path),
            str(self.tmp_path / "b.md"), FIXED_DATE, audit_config=LUMORA,
        )
        self.assertEqual(default_progress.metrics, lumora_progress.metrics)
        self.assertEqual(default_progress.overall_assessment, lumora_progress.overall_assessment)


class StructuredAuditMultiClientTests(_FictionalClientTestCase):
    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_analyze_response_receives_fictional_brand_and_ordered_competitors(
        self, mock_generate, mock_analyze
    ) -> None:
        mock_generate.return_value = "Lumora leads, ahead of Brewvale and Steepwise."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        new_row = run_structured_audit(str(self.questions_path), str(self.results_path), audit_config=LUMORA)

        mock_analyze.assert_called_once_with(
            mock_generate.return_value, "Lumora", ["Brewvale", "Kettleworth", "Steepwise"]
        )
        competitors_arg = mock_analyze.call_args.args[2]
        self.assertIsInstance(competitors_arg, list)
        self.assertEqual(new_row["question_id"], "PA04")
        self.assertEqual(new_row["competitors_cited"], "Brewvale; Steepwise")
        self.assert_no_boots_leak(json.dumps(new_row))

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_explicit_brand_and_competitors_override_config(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        run_structured_audit(
            str(self.questions_path), str(self.results_path),
            brand="Override", known_competitors=["Only One"], audit_config=LUMORA,
        )

        mock_analyze.assert_called_once_with("Answer.", "Override", ["Only One"])

    def test_module_aliases_still_default_audit(self) -> None:
        self.assertEqual(structured_audit_module.BRAND, default_audit_config().brand)
        self.assertEqual(structured_audit_module.KNOWN_COMPETITORS, list(default_audit_config().competitors))


class EndToEndMultiClientTests(_FictionalClientTestCase):
    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_config_reaches_analysis_and_report(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Lumora is a well-regarded tea retailer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)
        report_path = self.tmp_path / "reports" / "audit_report.md"

        new_row = run_end_to_end_demo(
            str(self.questions_path), str(self.results_path), str(report_path), audit_config=LUMORA
        )

        mock_analyze.assert_called_once_with(
            mock_generate.return_value, "Lumora", ["Brewvale", "Kettleworth", "Steepwise"]
        )
        self.assertEqual(new_row["question_id"], "PA05")
        report = report_path.read_text(encoding="utf-8")
        self.assert_lumora_overview(report, "# SignalScope AI Audit Report")
        self.assertIn("- Y (Lumora cited):", report)
        self.assert_no_boots_leak(report)

    @patch("run_end_to_end_demo.analyze_response")
    @patch("run_end_to_end_demo.generate_response")
    def test_default_paths_come_from_config_not_boots(self, mock_generate, mock_analyze) -> None:
        # With no explicit paths, a non-default config must read and write
        # only its own audits/<slug>/ and reports/<slug>/ files. Run from a
        # temp working directory so the relative config paths land there.
        workspace = self.tmp_path / "workspace"
        write_questions_csv(workspace / LUMORA.questions_file, QUESTION_ROWS)
        write_results_csv(workspace / LUMORA.results_file, BASELINE_ROWS)
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)

        original_cwd = os.getcwd()
        os.chdir(workspace)
        self.addCleanup(os.chdir, original_cwd)

        run_end_to_end_demo(audit_config=LUMORA)

        report = (workspace / LUMORA.audit_report_file).read_text(encoding="utf-8")
        self.assert_lumora_overview(report, "# SignalScope AI Audit Report")
        self.assertEqual(len(load_audit_rows(str(workspace / LUMORA.results_file))), 3)
        self.assertFalse((workspace / "reports" / "boots-uk-health-beauty").exists())
        self.assertFalse((workspace / "audits" / "boots-uk-health-beauty").exists())

    def test_full_workflow_with_fictional_config(self) -> None:
        """Audit -> report -> findings -> recommendations -> measurement,
        all for the fictional client, with every output leak-free."""
        reports_dir = self.tmp_path / "reports"
        with patch("run_end_to_end_demo.generate_response", return_value="Lumora answer."), patch(
            "run_end_to_end_demo.analyze_response", return_value=dict(ANALYSIS_RESULT)
        ):
            run_end_to_end_demo(
                str(self.questions_path), str(self.results_path), str(reports_dir / "audit_report.md"),
                audit_config=LUMORA,
            )

        generate_geo_findings(
            str(self.questions_path), str(self.results_path), str(reports_dir / "GEO_FINDINGS.md"),
            FIXED_DATE, audit_config=LUMORA,
        )
        with patch("recommendation_engine.generate_response", return_value=canned_recommendations_json()) as mock_rec:
            generate_geo_recommendations(
                str(self.questions_path), str(self.results_path), str(reports_dir / "GEO_RECOMMENDATIONS.md"),
                FIXED_DATE, audit_config=LUMORA,
            )
        self.assert_no_boots_leak(mock_rec.call_args.args[0])
        generate_geo_progress(
            str(self.results_path), str(self.followup_path), str(self.questions_path),
            str(reports_dir / "GEO_PROGRESS.md"), FIXED_DATE, audit_config=LUMORA,
        )

        for name in ["audit_report.md", "GEO_FINDINGS.md", "GEO_RECOMMENDATIONS.md", "GEO_PROGRESS.md"]:
            text = (reports_dir / name).read_text(encoding="utf-8")
            self.assertIn("Lumora Tea Co. Specialty Tea", text.splitlines()[0], name)
            self.assert_no_boots_leak(text)


class DefaultBehaviourIsBootsTests(_FictionalClientTestCase):
    """No-config calls must still produce the v2.0 Boots behaviour, and a
    fictional run must not alter any module-level default."""

    def test_default_config_is_boots(self) -> None:
        self.assertEqual(default_audit_config(), load_audit_config("boots-uk-health-beauty"))

    def test_module_constants_equal_v20_values(self) -> None:
        self.assertEqual(
            (report_generator.BRAND, report_generator.MARKET, report_generator.CATEGORY),
            ("Boots", "United Kingdom", "Health & Beauty Retail"),
        )
        self.assertEqual(structured_audit_module.KNOWN_COMPETITORS, ["Superdrug", "Amazon", "Holland & Barrett"])

    @patch("recommendation_engine.generate_response")
    def test_boots_recommendation_prompt_identical_to_v20(self, mock_generate) -> None:
        # v2.0 built this prompt from findings computed with the Boots BRAND
        # and the literal Boots brand/market/category.
        mock_generate.return_value = canned_recommendations_json()
        questions = str(REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv")
        results = str(REPO_ROOT / "audits" / "boots-uk-health-beauty" / "audit_results.csv")

        generate_geo_recommendations(questions, results, str(self.tmp_path / "r.md"), FIXED_DATE)

        expected = _build_recommendations_prompt(
            compute_findings(load_audit_rows(results), len(load_questions(questions))),
            "Boots",
            "United Kingdom",
            "Health & Beauty Retail",
        )
        self.assertEqual(mock_generate.call_args.args[0], expected)
        self.assertIn("Observation: Boots was cited in", expected)

    @patch("run_structured_audit.analyze_response")
    @patch("run_structured_audit.generate_response")
    def test_no_config_structured_audit_uses_boots(self, mock_generate, mock_analyze) -> None:
        mock_generate.return_value = "Answer."
        mock_analyze.return_value = dict(ANALYSIS_RESULT)
        run_structured_audit(str(self.questions_path), str(self.results_path))
        mock_analyze.assert_called_once_with("Answer.", "Boots", ["Superdrug", "Amazon", "Holland & Barrett"])

    def test_fictional_run_does_not_mutate_defaults(self) -> None:
        before = default_audit_config()
        generate_report_markdown(BASELINE_ROWS, FIXED_DATE, 4, audit_config=LUMORA)
        compute_findings(BASELINE_ROWS, 4, audit_config=LUMORA)
        self.assertIs(default_audit_config(), before)
        self.assertEqual(report_generator.BRAND, "Boots")
        default_md = generate_report_markdown(BASELINE_ROWS, FIXED_DATE, 4)
        self.assertIn("— Boots UK Health & Beauty", default_md.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
