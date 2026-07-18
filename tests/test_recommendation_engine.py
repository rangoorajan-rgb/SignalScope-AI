"""Tests for src/recommendation_engine.py.

No real API calls are made: generate_response is mocked throughout. All
write tests use temporary files; the real audit dataset is only ever
read, never written to.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from audit_runner import AuditRunnerError  # noqa: E402
from gemini_client import GeminiClientError  # noqa: E402
from geo_findings_analyzer import Finding, compute_findings  # noqa: E402
from report_generator import ReportGeneratorError  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, WriteAuditResultError, load_existing_results  # noqa: E402
import recommendation_engine as re_module  # noqa: E402
from recommendation_engine import (  # noqa: E402
    Recommendation,
    RecommendationEngineError,
    _compute_priority,
    generate_geo_recommendations,
    generate_recommendations,
    render_markdown,
)

REAL_QUESTIONS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"
REAL_RESULTS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "audit_results.csv"

FIXED_DATE = date(2026, 7, 18)

SAMPLE_FINDINGS = [
    Finding(
        title="Overall AI Search Visibility",
        value="Boots was cited in 42.9% of the 7 response(s) with a recorded brand_cited value.",
        evidence="brand_cited=Y in 3 row(s), brand_cited=N in 4 row(s); 3 excluded.",
        confidence="Low",
    ),
    Finding(
        title="Competitor Dominance",
        value="Morrisons was the most frequently mentioned competitor, with 3 mention(s).",
        evidence="Top mentioned competitors: Morrisons (3), Sainsbury's (3), Superdrug (3).",
        confidence="Medium",
    ),
    Finding(
        title="Brand Sentiment Summary",
        value="Sentiment toward Boots was predominantly Neutral.",
        evidence="7 of 10 row(s) had a recorded sentiment value; 3 excluded.",
        confidence="High",
    ),
]

KNOWN_TITLES = {f.title for f in SAMPLE_FINDINGS}


def canned_recommendation(**overrides) -> dict:
    payload = {
        "title": "Increase Direct Brand Citations",
        "problem_addressed": "Boots is cited in fewer than half of analysed responses.",
        "recommendation_rationale": (
            "Low visibility confidence combined with a citation rate under 50% indicates AI "
            "systems rarely name Boots directly in this dataset."
        ),
        "recommended_action": "Complete the remaining audit questions to build a fuller evidence base.",
        "potential_impact": "High",
        "indicative_effort": "Low",
        "success_metric": "Increase brand citation rate in subsequent audit runs.",
        "source_findings": ["Overall AI Search Visibility"],
    }
    payload.update(overrides)
    return payload


def write_results_csv(
    path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None
) -> None:
    import csv

    fieldnames = fieldnames or RESULTS_SCHEMA
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class ComputePriorityTests(unittest.TestCase):
    def test_high_high_low_is_p1(self) -> None:
        self.assertEqual(_compute_priority("High", "High", "Low"), "P1")  # 3+3-1=5

    def test_high_high_high_is_p2(self) -> None:
        self.assertEqual(_compute_priority("High", "High", "High"), "P2")  # 3+3-3=3

    def test_low_low_high_is_p3(self) -> None:
        self.assertEqual(_compute_priority("Low", "Low", "High"), "P3")  # 1+1-3=-1

    def test_medium_medium_medium_is_p2(self) -> None:
        self.assertEqual(_compute_priority("Medium", "Medium", "Medium"), "P2")  # 2+2-2=2

    def test_high_low_low_is_p2(self) -> None:
        self.assertEqual(_compute_priority("High", "Low", "Low"), "P2")  # 3+1-1=3

    def test_low_high_low_is_p2(self) -> None:
        self.assertEqual(_compute_priority("Low", "High", "Low"), "P2")  # 1+3-1=3

    def test_boundary_composite_four_is_p1(self) -> None:
        self.assertEqual(_compute_priority("High", "Medium", "Low"), "P1")  # 3+2-1=4

    def test_boundary_composite_two_is_p2(self) -> None:
        self.assertEqual(_compute_priority("Medium", "Low", "Low"), "P2")  # 2+1-1=2

    def test_boundary_composite_one_is_p3(self) -> None:
        self.assertEqual(_compute_priority("Low", "Medium", "Medium"), "P3")  # 1+2-2=1


class GenerateRecommendationsTests(unittest.TestCase):
    def test_empty_findings_list_raises_without_api_call(self) -> None:
        with patch("recommendation_engine.generate_response") as mock_generate:
            with self.assertRaises(RecommendationEngineError):
                generate_recommendations([])
            mock_generate.assert_not_called()

    @patch("recommendation_engine.generate_response")
    def test_successful_generation(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps([canned_recommendation()])

        recommendations = generate_recommendations(SAMPLE_FINDINGS)

        self.assertEqual(len(recommendations), 1)
        r = recommendations[0]
        self.assertIsInstance(r, Recommendation)
        self.assertEqual(r.title, "Increase Direct Brand Citations")
        self.assertEqual(r.potential_impact, "High")
        self.assertEqual(r.indicative_effort, "Low")
        self.assertEqual(r.source_findings, ["Overall AI Search Visibility"])

    @patch("recommendation_engine.generate_response")
    def test_confidence_derived_as_min_of_cited_findings(self, mock_generate) -> None:
        # Cites a Low-confidence and a High-confidence finding -> result must be Low.
        mock_generate.return_value = json.dumps(
            [canned_recommendation(source_findings=["Overall AI Search Visibility", "Brand Sentiment Summary"])]
        )

        r = generate_recommendations(SAMPLE_FINDINGS)[0]

        self.assertEqual(r.confidence, "Low")

    @patch("recommendation_engine.generate_response")
    def test_confidence_medium_when_citing_medium_and_high(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps(
            [canned_recommendation(source_findings=["Competitor Dominance", "Brand Sentiment Summary"])]
        )

        r = generate_recommendations(SAMPLE_FINDINGS)[0]

        self.assertEqual(r.confidence, "Medium")

    @patch("recommendation_engine.generate_response")
    def test_supporting_evidence_is_verbatim_from_finding_not_gemini(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps([canned_recommendation()])

        r = generate_recommendations(SAMPLE_FINDINGS)[0]

        expected_evidence = SAMPLE_FINDINGS[0].evidence
        self.assertIn(expected_evidence, r.supporting_evidence)
        self.assertIn("Overall AI Search Visibility", r.supporting_evidence)

    @patch("recommendation_engine.generate_response")
    def test_priority_computed_and_not_taken_from_gemini(self, mock_generate) -> None:
        # source finding confidence=Low; impact=High, effort=Low -> 3+1-1=3 -> P2
        mock_generate.return_value = json.dumps([canned_recommendation()])

        r = generate_recommendations(SAMPLE_FINDINGS)[0]

        self.assertEqual(r.priority, "P2")

    @patch("recommendation_engine.generate_response")
    def test_recommendations_sorted_p1_first(self, mock_generate) -> None:
        low_priority = canned_recommendation(
            title="Low priority item",
            potential_impact="Low",
            indicative_effort="High",
            source_findings=["Overall AI Search Visibility"],  # Low confidence -> 1+1-3=-1 -> P3
        )
        high_priority = canned_recommendation(
            title="High priority item",
            potential_impact="High",
            indicative_effort="Low",
            source_findings=["Brand Sentiment Summary"],  # High confidence -> 3+3-1=5 -> P1
        )
        mock_generate.return_value = json.dumps([low_priority, high_priority])

        recommendations = generate_recommendations(SAMPLE_FINDINGS)

        self.assertEqual([r.priority for r in recommendations], ["P1", "P3"])
        self.assertEqual(recommendations[0].title, "High priority item")

    @patch("recommendation_engine.generate_response")
    def test_malformed_json_raises(self, mock_generate) -> None:
        mock_generate.return_value = "{not valid json,,,"
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_non_array_json_raises(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps(canned_recommendation())  # a dict, not a list
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_empty_array_raises(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps([])
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_missing_field_raises(self, mock_generate) -> None:
        payload = canned_recommendation()
        del payload["recommendation_rationale"]
        mock_generate.return_value = json.dumps([payload])
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_unexpected_field_raises(self, mock_generate) -> None:
        payload = canned_recommendation(extra_field="surprise")
        mock_generate.return_value = json.dumps([payload])
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_invalid_potential_impact_raises(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps([canned_recommendation(potential_impact="Massive")])
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_invalid_indicative_effort_raises(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps([canned_recommendation(indicative_effort="None")])
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_unknown_source_finding_raises(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps(
            [canned_recommendation(source_findings=["A Finding That Does Not Exist"])]
        )
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_empty_source_findings_raises(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps([canned_recommendation(source_findings=[])])
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_gemini_call_failure_wrapped(self, mock_generate) -> None:
        mock_generate.side_effect = GeminiClientError("Gemini API call failed: 503 UNAVAILABLE.")
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_empty_response_raises(self, mock_generate) -> None:
        mock_generate.return_value = "   "
        with self.assertRaises(RecommendationEngineError):
            generate_recommendations(SAMPLE_FINDINGS)

    @patch("recommendation_engine.generate_response")
    def test_prompt_contains_only_findings_and_brand_context(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps([canned_recommendation()])

        generate_recommendations(SAMPLE_FINDINGS)

        prompt = mock_generate.call_args.args[0]
        self.assertIn("Overall AI Search Visibility", prompt)
        self.assertIn("Boots", prompt)
        self.assertIn("United Kingdom", prompt)
        self.assertIn("Health & Beauty Retail", prompt)


class RenderMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        with patch("recommendation_engine.generate_response") as mock_generate:
            mock_generate.return_value = json.dumps([canned_recommendation()])
            self.recommendations = generate_recommendations(SAMPLE_FINDINGS)
        self.markdown = render_markdown(self.recommendations, total_findings=3, generated_at=FIXED_DATE)

    def test_title_present(self) -> None:
        self.assertIn("# SignalScope AI GEO Recommendations Report — Boots UK Health & Beauty", self.markdown)

    def test_all_required_sections_present(self) -> None:
        for heading in [
            "## Report Overview",
            "## Executive Summary",
            "## Prioritised Recommendations",
            "## Detailed Recommendations",
            "## Implementation Note",
        ]:
            self.assertIn(heading, self.markdown)

    def test_detailed_section_has_all_labelled_fields(self) -> None:
        for label in [
            "**Problem Addressed:**",
            "**Supporting Evidence:**",
            "**Recommendation Rationale:**",
            "**Recommended Action:**",
            "**Potential Impact:**",
            "**Indicative Effort:**",
            "**Confidence:**",
            "**Success Metric:**",
            "**Source Finding(s):**",
        ]:
            self.assertIn(label, self.markdown)

    def test_priority_table_present(self) -> None:
        self.assertIn("| Priority | Title | Potential Impact | Indicative Effort | Confidence |", self.markdown)

    def test_implementation_note_states_human_action_required(self) -> None:
        lowered = self.markdown.lower()
        self.assertIn("must implement", lowered)
        self.assertIn("re-audit", lowered)

    def test_deterministic_rendering(self) -> None:
        first = render_markdown(self.recommendations, 3, FIXED_DATE)
        second = render_markdown(self.recommendations, 3, FIXED_DATE)
        self.assertEqual(first, second)


class GenerateGeoRecommendationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.questions_path = self.tmp_path / "buyer_questions.csv"
        self.results_path = self.tmp_path / "audit_results.csv"
        self.report_path = self.tmp_path / "reports" / "GEO_RECOMMENDATIONS.md"

        import csv

        with self.questions_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["question_id", "buyer_journey_stage", "question", "intent", "notes"]
            )
            writer.writeheader()
            for qid in ["PA01", "SD04", "VE04"]:
                writer.writerow({"question_id": qid, "buyer_journey_stage": "x", "question": "x", "intent": "", "notes": ""})

        sample_rows = [
            {
                "run_date": "2026-07-17", "question_id": "PA01", "question": "Q1?",
                "funnel_stage": "Problem Awareness", "engine": "Perplexity",
                "brand_cited": "N", "brand_position": "", "competitors_cited": "Superdrug",
                "sources_cited": "Mintel", "sentiment": "Neutral", "answer_snippet": "x",
            },
        ]
        write_results_csv(self.results_path, sample_rows)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("recommendation_engine.generate_response")
    def test_creates_report_and_returns_recommendations(self, mock_generate) -> None:
        mock_generate.return_value = json.dumps(
            [canned_recommendation(source_findings=["Overall AI Search Visibility"])]
        )

        recommendations, markdown = generate_geo_recommendations(
            str(self.questions_path), str(self.results_path), str(self.report_path), generated_at=FIXED_DATE
        )

        self.assertTrue(self.report_path.is_file())
        self.assertGreaterEqual(len(recommendations), 1)
        self.assertIn("# SignalScope AI GEO Recommendations Report", markdown)

    def test_missing_questions_file_raises(self) -> None:
        with self.assertRaises(AuditRunnerError):
            generate_geo_recommendations(str(self.tmp_path / "missing.csv"), str(self.results_path), str(self.report_path))

    def test_missing_results_file_raises(self) -> None:
        with self.assertRaises(WriteAuditResultError):
            generate_geo_recommendations(str(self.questions_path), str(self.tmp_path / "missing.csv"), str(self.report_path))

    def test_empty_results_file_raises(self) -> None:
        write_results_csv(self.results_path, [])
        with self.assertRaises(ReportGeneratorError):
            generate_geo_recommendations(str(self.questions_path), str(self.results_path), str(self.report_path))


class RealDataIntegrationTests(unittest.TestCase):
    """Uses the real audit dataset (read-only) to compute real findings,
    with Gemini mocked, and writes the report to a temp path only."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.report_path = self.tmp_path / "GEO_RECOMMENDATIONS.md"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("recommendation_engine.generate_response")
    def test_real_findings_produce_valid_recommendations(self, mock_generate) -> None:
        self.assertTrue(REAL_RESULTS_FILE.is_file())
        rows = load_existing_results(str(REAL_RESULTS_FILE))
        real_findings = compute_findings(rows, 40)
        real_title = real_findings[0].title

        before_bytes = REAL_RESULTS_FILE.read_bytes()
        mock_generate.return_value = json.dumps([canned_recommendation(source_findings=[real_title])])

        recommendations = generate_recommendations(real_findings)

        self.assertEqual(REAL_RESULTS_FILE.read_bytes(), before_bytes)
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0].source_findings, [real_title])


if __name__ == "__main__":
    unittest.main()
