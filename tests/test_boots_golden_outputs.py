"""Golden-master regression tests for the v2.0 Boots outputs.

Regenerates the deterministic Boots reports with the existing production
code, into temporary locations only, and compares them against the
committed reports under reports/boots-uk-health-beauty/. Those committed
reports are never written to.

GEO_RECOMMENDATIONS.md is produced by Gemini and cannot be reproduced
byte-for-byte, so its renderer is pinned instead against fixed canned
Recommendation objects. No test here calls Gemini or needs network access.

Line endings: git stores the reports with LF, but a checkout may convert
them to CRLF (core.autocrlf), and Path.write_text writes the platform's
line separator. Comparisons therefore normalise line terminators only -
every other byte must match exactly.
"""

from __future__ import annotations

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

from geo_findings_analyzer import generate_geo_findings  # noqa: E402
from measurement_engine import generate_geo_progress  # noqa: E402
from recommendation_engine import Recommendation, render_markdown as render_recommendations  # noqa: E402
from report_generator import generate_report  # noqa: E402

AUDIT_DIR = REPO_ROOT / "audits" / "boots-uk-health-beauty"
REPORTS_DIR = REPO_ROOT / "reports" / "boots-uk-health-beauty"
QUESTIONS_FILE = AUDIT_DIR / "buyer_questions.csv"
RESULTS_FILE = AUDIT_DIR / "audit_results.csv"

REFERENCE_DATE = date(2026, 7, 18)


def normalised_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


class _GoldenTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.protected = {
            p: p.read_bytes() for p in [QUESTIONS_FILE, RESULTS_FILE, *sorted(REPORTS_DIR.glob("*.md"))]
        }

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        for path, before in self.protected.items():
            self.assertEqual(path.read_bytes(), before, f"Protected file was modified: {path}")

    def assert_matches_committed(self, generated: Path, name: str) -> None:
        reference = REPORTS_DIR / name
        self.assertTrue(reference.is_file(), f"Committed reference report missing: {reference}")
        generated_bytes = normalised_bytes(generated)
        self.assertNotIn(b"\r", generated_bytes)
        self.assertEqual(generated_bytes, normalised_bytes(reference), f"{name} differs from the committed v2.0 report")


class BootsDeterministicReportGoldenTests(_GoldenTestCase):
    def test_audit_report_matches_committed(self) -> None:
        out = self.tmp_path / "audit_report.md"
        generate_report(str(QUESTIONS_FILE), str(RESULTS_FILE), str(out), generated_at=REFERENCE_DATE)
        self.assert_matches_committed(out, "audit_report.md")

    def test_geo_findings_matches_committed(self) -> None:
        out = self.tmp_path / "GEO_FINDINGS.md"
        generate_geo_findings(str(QUESTIONS_FILE), str(RESULTS_FILE), str(out), generated_at=REFERENCE_DATE)
        self.assert_matches_committed(out, "GEO_FINDINGS.md")

    def test_geo_progress_matches_committed(self) -> None:
        # The committed GEO_PROGRESS.md is a structural validation run:
        # the same dataset used as both baseline and follow-up.
        out = self.tmp_path / "GEO_PROGRESS.md"
        generate_geo_progress(
            str(RESULTS_FILE),
            str(RESULTS_FILE),
            str(QUESTIONS_FILE),
            str(out),
            generated_at=REFERENCE_DATE,
            is_validation_run=True,
        )
        self.assert_matches_committed(out, "GEO_PROGRESS.md")

    def test_returned_markdown_matches_written_file(self) -> None:
        out = self.tmp_path / "audit_report.md"
        markdown = generate_report(str(QUESTIONS_FILE), str(RESULTS_FILE), str(out), generated_at=REFERENCE_DATE)
        self.assertEqual(markdown.encode("utf-8"), normalised_bytes(out))

    def test_no_gemini_call_is_made(self) -> None:
        with patch("gemini_client.genai.Client", side_effect=AssertionError("Gemini must not be called")):
            generate_report(
                str(QUESTIONS_FILE), str(RESULTS_FILE), str(self.tmp_path / "a.md"), generated_at=REFERENCE_DATE
            )
            generate_geo_findings(
                str(QUESTIONS_FILE), str(RESULTS_FILE), str(self.tmp_path / "f.md"), generated_at=REFERENCE_DATE
            )
            generate_geo_progress(
                str(RESULTS_FILE),
                str(RESULTS_FILE),
                str(QUESTIONS_FILE),
                str(self.tmp_path / "p.md"),
                generated_at=REFERENCE_DATE,
                is_validation_run=True,
            )


CANNED_RECOMMENDATIONS = [
    Recommendation(
        title="Increase Direct Brand Citations",
        problem_addressed="Boots is cited in fewer than half of analysed responses.",
        supporting_evidence="[Overall AI Search Visibility] brand_cited=Y in 3 row(s), brand_cited=N in 4 row(s).",
        recommendation_rationale="Low citation rate indicates AI systems rarely name Boots directly.",
        recommended_action="Publish authoritative category content that names Boots explicitly.",
        potential_impact="High",
        indicative_effort="Low",
        confidence="High",
        priority="P1",
        success_metric="Brand citation rate in the next audit.",
        source_findings=["Overall AI Search Visibility"],
    ),
    Recommendation(
        title="Strengthen Authority Sources",
        problem_addressed="Few responses cite explicit sources.",
        supporting_evidence="[Most Cited Authority Sources] 2 distinct source(s) were explicitly cited.",
        recommendation_rationale="Authority sources shape AI answers.",
        recommended_action="Secure coverage in the sources AI systems already cite.",
        potential_impact="Medium",
        indicative_effort="Medium",
        confidence="Medium",
        priority="P2",
        success_metric="Source coverage rate in the next audit.",
        source_findings=["Most Cited Authority Sources"],
    ),
    Recommendation(
        title="Broaden Funnel Coverage",
        problem_addressed="Two funnel stages have no results.",
        supporting_evidence=(
            "[Content Coverage Observations] 3 of 5 stages covered. | "
            "[Overall GEO Maturity Assessment] Early."
        ),
        recommendation_rationale="Missing stages limit the evidence base.",
        recommended_action="Complete the remaining audit questions.",
        potential_impact="Low",
        indicative_effort="High",
        confidence="Low",
        priority="P3",
        success_metric="Funnel stages covered in the next audit.",
        source_findings=["Content Coverage Observations", "Overall GEO Maturity Assessment"],
    ),
]

# Snapshot of the v2.0 renderer's exact output for CANNED_RECOMMENDATIONS.
EXPECTED_RECOMMENDATIONS_MARKDOWN = """\
# SignalScope AI GEO Recommendations Report — Boots UK Health & Beauty

## Report Overview

- Brand: Boots
- Market: United Kingdom
- Category: Health & Beauty Retail
- Findings analysed: 7
- Recommendations generated: 3
- Report generation date: 2026-07-18

## Executive Summary

This report translates 7 structured GEO finding(s) into 3 prioritised recommendation(s): 1 P1, 1 P2, 1 P3. \
Each recommendation is traceable to the specific finding(s) it is based on, and its confidence reflects the \
confidence of the weakest finding it relies on.

## Prioritised Recommendations

| Priority | Title | Potential Impact | Indicative Effort | Confidence |
|---|---|---|---|---|
| P1 | Increase Direct Brand Citations | High | Low | High |
| P2 | Strengthen Authority Sources | Medium | Medium | Medium |
| P3 | Broaden Funnel Coverage | Low | High | Low |

## Detailed Recommendations

### 1. [P1] Increase Direct Brand Citations

- **Problem Addressed:** Boots is cited in fewer than half of analysed responses.
- **Supporting Evidence:** [Overall AI Search Visibility] brand_cited=Y in 3 row(s), brand_cited=N in 4 row(s).
- **Recommendation Rationale:** Low citation rate indicates AI systems rarely name Boots directly.
- **Recommended Action:** Publish authoritative category content that names Boots explicitly.
- **Potential Impact:** High
- **Indicative Effort:** Low
- **Confidence:** High
- **Success Metric:** Brand citation rate in the next audit.
- **Source Finding(s):** Overall AI Search Visibility

### 2. [P2] Strengthen Authority Sources

- **Problem Addressed:** Few responses cite explicit sources.
- **Supporting Evidence:** [Most Cited Authority Sources] 2 distinct source(s) were explicitly cited.
- **Recommendation Rationale:** Authority sources shape AI answers.
- **Recommended Action:** Secure coverage in the sources AI systems already cite.
- **Potential Impact:** Medium
- **Indicative Effort:** Medium
- **Confidence:** Medium
- **Success Metric:** Source coverage rate in the next audit.
- **Source Finding(s):** Most Cited Authority Sources

### 3. [P3] Broaden Funnel Coverage

- **Problem Addressed:** Two funnel stages have no results.
- **Supporting Evidence:** [Content Coverage Observations] 3 of 5 stages covered. | \
[Overall GEO Maturity Assessment] Early.
- **Recommendation Rationale:** Missing stages limit the evidence base.
- **Recommended Action:** Complete the remaining audit questions.
- **Potential Impact:** Low
- **Indicative Effort:** High
- **Confidence:** Low
- **Success Metric:** Funnel stages covered in the next audit.
- **Source Finding(s):** Content Coverage Observations, Overall GEO Maturity Assessment

## Implementation Note

These are recommendations only. The brand or its consultant must implement the actions above before any \
re-audit can measure whether AI search visibility has changed. SignalScope AI does not implement changes, \
publish content, or edit any website on the brand's behalf.
"""


class BootsRecommendationsRendererGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        with patch("gemini_client.genai.Client", side_effect=AssertionError("Gemini must not be called")):
            self.markdown = render_recommendations(
                CANNED_RECOMMENDATIONS, total_findings=7, generated_at=REFERENCE_DATE
            )

    def test_renderer_output_matches_v20_snapshot(self) -> None:
        self.assertEqual(self.markdown, EXPECTED_RECOMMENDATIONS_MARKDOWN)

    def test_static_sections_match_committed_report(self) -> None:
        # The committed report's Gemini-authored content varies, but the
        # renderer's fixed scaffolding must be identical to it.
        committed_lines = (REPORTS_DIR / "GEO_RECOMMENDATIONS.md").read_text(encoding="utf-8").splitlines()
        rendered_lines = self.markdown.splitlines()
        static_lines = [
            "# SignalScope AI GEO Recommendations Report — Boots UK Health & Beauty",
            "## Report Overview",
            "- Brand: Boots",
            "- Market: United Kingdom",
            "- Category: Health & Beauty Retail",
            "## Executive Summary",
            "## Prioritised Recommendations",
            "| Priority | Title | Potential Impact | Indicative Effort | Confidence |",
            "|---|---|---|---|---|",
            "## Detailed Recommendations",
            "## Implementation Note",
            rendered_lines[-1],  # the full Implementation Note paragraph
        ]
        for line in static_lines:
            self.assertIn(line, rendered_lines)
            self.assertIn(line, committed_lines)
        self.assertEqual(committed_lines[0], rendered_lines[0])


if __name__ == "__main__":
    unittest.main()
