"""GEO findings analysis engine for SignalScope AI.

Aggregates the existing audit dataset (audit_results.csv) into a
structured list of business findings - observations only, never
recommendations. Each finding carries its own evidence and a confidence
level derived from how much of the dataset actually supports it, so every
finding stays traceable back to the underlying rows.

This module performs no new AI analysis of its own: all brand/competitor/
source/sentiment extraction already happened in response_analyzer.py.
This is a deterministic aggregation and presentation layer only, reusing
report_generator.py's existing computation helpers rather than
reimplementing them.

The returned list[Finding] is the primary artefact - GEO_FINDINGS.md is
rendered from it, not the other way around, so a future Recommendation
Engine can consume the structured findings directly instead of parsing
Markdown.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from audit_runner import AuditRunnerError, load_questions
from report_generator import (
    BRAND,
    CATEGORY,
    MARKET,
    ReportGeneratorError,
    compute_brand_visibility,
    compute_mention_frequency,
    compute_sentiment_summary,
    compute_stage_coverage,
    load_audit_rows,
)
from write_single_audit_result import WriteAuditResultError

DEFAULT_QUESTIONS_FILE = "audits/boots-uk-health-beauty/buyer_questions.csv"
DEFAULT_RESULTS_FILE = "audits/boots-uk-health-beauty/audit_results.csv"
DEFAULT_FINDINGS_REPORT_FILE = "reports/boots-uk-health-beauty/GEO_FINDINGS.md"

ALL_BUYER_JOURNEY_STAGES = [
    "Problem Awareness",
    "Solution Discovery",
    "Vendor Comparison",
    "Vendor Evaluation",
    "Purchase Decision",
]

HIGH_CONFIDENCE_THRESHOLD = 0.75
MEDIUM_CONFIDENCE_THRESHOLD = 0.40


@dataclass(frozen=True)
class Finding:
    """One structured GEO finding: an observation, its supporting
    evidence, and a confidence level. Never a recommendation."""

    title: str
    value: str
    evidence: str
    confidence: str


def _confidence_from_ratio(ratio: float) -> str:
    if ratio >= HIGH_CONFIDENCE_THRESHOLD:
        return "High"
    if ratio >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "Medium"
    return "Low"


def _safe_ratio(numerator: int, denominator: int) -> float:
    return (numerator / denominator) if denominator else 0.0


def _finding_overall_visibility(rows: list[dict[str, str]], total_question_count: int) -> Finding:
    visibility = compute_brand_visibility(rows)
    unique_questions = len({r["question_id"] for r in rows if r.get("question_id")})
    coverage_ratio = _safe_ratio(unique_questions, total_question_count)
    rate_text = f"{visibility['rate']:.1f}%" if visibility["rate"] is not None else "N/A"

    value = (
        f"{BRAND} was cited in {rate_text} of the {visibility['considered']} response(s) "
        f"with a recorded brand_cited value, across {unique_questions} of "
        f"{total_question_count} buyer questions in the library."
    )
    evidence = (
        f"brand_cited=Y in {visibility['y']} row(s), brand_cited=N in {visibility['n']} "
        f"row(s); {visibility['excluded']} row(s) excluded (brand_cited blank); "
        f"{unique_questions}/{total_question_count} questions covered."
    )
    return Finding("Overall AI Search Visibility", value, evidence, _confidence_from_ratio(coverage_ratio))


def _finding_brand_mention_frequency(rows: list[dict[str, str]]) -> Finding:
    visibility = compute_brand_visibility(rows)
    considered = visibility["considered"]

    value = (
        f"{BRAND} was explicitly mentioned in {visibility['y']} of {considered} analysed "
        f"response(s) with a recorded brand_cited value."
    )
    evidence = (
        f"brand_cited=Y count: {visibility['y']}; brand_cited=N count: {visibility['n']}; "
        f"total rows: {len(rows)}."
    )
    return Finding(
        "Brand Mention Frequency", value, evidence, _confidence_from_ratio(_safe_ratio(considered, len(rows)))
    )


def _finding_competitor_dominance(rows: list[dict[str, str]]) -> Finding:
    competitors = compute_mention_frequency(rows, "competitors_cited")
    total_rows = len(rows)

    if not competitors:
        return Finding(
            "Competitor Dominance",
            "No competitors were recorded in the available data.",
            "competitors_cited was blank in all rows.",
            "Low",
        )

    top_name, top_count = competitors[0]
    top_five = ", ".join(f"{name} ({count})" for name, count in competitors[:5])
    value = (
        f"{top_name} was the most frequently mentioned competitor, with {top_count} "
        f"mention(s) across the dataset."
    )
    evidence = f"Top mentioned competitors: {top_five}."
    return Finding(
        "Competitor Dominance", value, evidence, _confidence_from_ratio(_safe_ratio(top_count, total_rows))
    )


def _finding_authority_sources(rows: list[dict[str, str]]) -> Finding:
    sources = compute_mention_frequency(rows, "sources_cited")
    total_rows = len(rows)

    if not sources:
        return Finding(
            "Most Cited Authority Sources",
            "No explicit sources were recorded in the available data.",
            "sources_cited was blank in all rows.",
            "Low",
        )

    top_five = ", ".join(f"{name} ({count})" for name, count in sources[:5])
    rows_with_sources = sum(1 for r in rows if (r.get("sources_cited") or "").strip())
    value = (
        f"{len(sources)} distinct source(s) were explicitly cited across "
        f"{rows_with_sources} of {total_rows} row(s)."
    )
    evidence = f"Most cited sources: {top_five}."
    return Finding(
        "Most Cited Authority Sources",
        value,
        evidence,
        _confidence_from_ratio(_safe_ratio(rows_with_sources, total_rows)),
    )


def _finding_sentiment_summary(rows: list[dict[str, str]]) -> Finding:
    sentiment = compute_sentiment_summary(rows)
    considered = len(rows) - sentiment["excluded"]

    if considered == 0:
        return Finding(
            "Brand Sentiment Summary",
            "No sentiment data is available in the current dataset.",
            "sentiment was blank in all rows.",
            "Low",
        )

    dominant = max(
        (("Positive", sentiment["positive"]), ("Neutral", sentiment["neutral"]), ("Negative", sentiment["negative"])),
        key=lambda kv: kv[1],
    )
    value = (
        f"Sentiment toward {BRAND} was predominantly {dominant[0]} "
        f"({dominant[1]} of {considered} rated response(s)): {sentiment['positive']} Positive, "
        f"{sentiment['neutral']} Neutral, {sentiment['negative']} Negative."
    )
    evidence = (
        f"{considered} of {len(rows)} row(s) had a recorded sentiment value; "
        f"{sentiment['excluded']} excluded (blank)."
    )
    return Finding(
        "Brand Sentiment Summary", value, evidence, _confidence_from_ratio(_safe_ratio(considered, len(rows)))
    )


def _finding_content_coverage(rows: list[dict[str, str]]) -> Finding:
    stage_counts = compute_stage_coverage(rows)
    stages_covered = [s for s in ALL_BUYER_JOURNEY_STAGES if stage_counts.get(s, 0) > 0]
    stages_missing = [s for s in ALL_BUYER_JOURNEY_STAGES if stage_counts.get(s, 0) == 0]

    value = (
        f"{len(stages_covered)} of {len(ALL_BUYER_JOURNEY_STAGES)} buyer journey stages have "
        f"at least one recorded result."
    )
    if stages_missing:
        value += f" No results yet for: {', '.join(stages_missing)}."

    breakdown = ", ".join(f"{stage}: {stage_counts.get(stage, 0)}" for stage in ALL_BUYER_JOURNEY_STAGES)
    evidence = f"Rows per stage - {breakdown}."
    return Finding(
        "Content Coverage Observations",
        value,
        evidence,
        _confidence_from_ratio(_safe_ratio(len(stages_covered), len(ALL_BUYER_JOURNEY_STAGES))),
    )


def _finding_geo_maturity(rows: list[dict[str, str]], total_question_count: int) -> Finding:
    unique_questions = len({r["question_id"] for r in rows if r.get("question_id")})
    coverage_ratio = _safe_ratio(unique_questions, total_question_count)
    visibility = compute_brand_visibility(rows)
    visibility_rate = (visibility["rate"] or 0.0) / 100

    # Deterministic tier, driven only by measured coverage and visibility -
    # never by free-text AI judgement.
    if coverage_ratio >= HIGH_CONFIDENCE_THRESHOLD and visibility_rate >= 0.5:
        tier = "Established"
    elif coverage_ratio >= MEDIUM_CONFIDENCE_THRESHOLD:
        tier = "Developing"
    else:
        tier = "Early"

    value = (
        f"GEO maturity is assessed as '{tier}', based on {unique_questions}/{total_question_count} "
        f"questions completed ({coverage_ratio * 100:.0f}% library coverage) and a brand citation "
        f"rate of {visibility_rate * 100:.0f}%."
    )
    evidence = (
        f"Question library coverage: {unique_questions}/{total_question_count} "
        f"({coverage_ratio * 100:.0f}%). Brand citation rate: {visibility_rate * 100:.0f}% "
        f"({visibility['y']} of {visibility['considered']} rated rows)."
    )
    return Finding("Overall GEO Maturity Assessment", value, evidence, _confidence_from_ratio(coverage_ratio))


def compute_findings(rows: list[dict[str, str]], total_question_count: int) -> list[Finding]:
    """Build all seven structured GEO findings from already-loaded rows.

    Deterministic: the same rows and total_question_count always produce
    identical findings. Every finding is an observation with its evidence
    and a confidence level - this function never generates a
    recommendation.
    """
    return [
        _finding_overall_visibility(rows, total_question_count),
        _finding_brand_mention_frequency(rows),
        _finding_competitor_dominance(rows),
        _finding_authority_sources(rows),
        _finding_sentiment_summary(rows),
        _finding_content_coverage(rows),
        _finding_geo_maturity(rows, total_question_count),
    ]


def render_markdown(
    findings: list[Finding],
    total_rows: int,
    unique_questions: int,
    total_question_count: int,
    generated_at: date,
) -> str:
    """Render the Markdown GEO findings report purely from an already-
    computed list[Finding] - the structured findings are the source of
    truth, not this text."""
    lines: list[str] = []
    lines.append("# SignalScope AI GEO Findings Report — Boots UK Health & Beauty")
    lines.append("")

    lines.append("## Report Overview")
    lines.append("")
    lines.append(f"- Brand: {BRAND}")
    lines.append(f"- Market: {MARKET}")
    lines.append(f"- Category: {CATEGORY}")
    lines.append(f"- Total audit result rows analysed: {total_rows}")
    lines.append(f"- Unique questions represented: {unique_questions} of {total_question_count}")
    lines.append(f"- Report generation date: {generated_at.isoformat()}")
    lines.append("")
    lines.append(
        "This report presents analysis findings only. It does not contain "
        "recommendations; those remain the responsibility of the consultant "
        "reviewing this evidence."
    )
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    for index, finding in enumerate(findings, start=1):
        lines.append(f"### {index}. {finding.title}")
        lines.append("")
        lines.append(f"- **Finding:** {finding.value}")
        lines.append(f"- **Evidence:** {finding.evidence}")
        lines.append(f"- **Confidence:** {finding.confidence}")
        lines.append("")

    lines.append("## Scope Note")
    lines.append("")
    lines.append("- This report is analysis only; it contains no recommendations.")
    lines.append(
        f"- Findings are based on {total_rows} recorded row(s) covering {unique_questions} "
        f"of {total_question_count} buyer questions — a partial dataset."
    )
    lines.append(
        "- Confidence reflects how much of the relevant data currently supports each "
        "finding, not the strength of any underlying business conclusion."
    )
    lines.append("")

    return "\n".join(lines)


def generate_geo_findings(
    questions_csv_path: str = DEFAULT_QUESTIONS_FILE,
    results_csv_path: str = DEFAULT_RESULTS_FILE,
    report_path: str = DEFAULT_FINDINGS_REPORT_FILE,
    generated_at: date | None = None,
) -> tuple[list[Finding], str]:
    """Compute structured findings and render + write the Markdown report.

    Returns (findings, markdown_text). Raises AuditRunnerError for a
    missing/invalid/empty question file, WriteAuditResultError for a
    missing/schema-invalid results file, or ReportGeneratorError if the
    results file has no data rows (all via the reused report_generator
    loading helpers).
    """
    generated_at = generated_at or date.today()

    all_questions = load_questions(questions_csv_path)
    rows = load_audit_rows(results_csv_path)

    findings = compute_findings(rows, len(all_questions))
    unique_questions = len({r["question_id"] for r in rows if r.get("question_id")})
    markdown = render_markdown(findings, len(rows), unique_questions, len(all_questions), generated_at)

    out_path = Path(report_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    return findings, markdown


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    questions_csv_path = argv[0] if len(argv) > 0 else DEFAULT_QUESTIONS_FILE
    results_csv_path = argv[1] if len(argv) > 1 else DEFAULT_RESULTS_FILE
    report_path = argv[2] if len(argv) > 2 else DEFAULT_FINDINGS_REPORT_FILE

    try:
        findings, _ = generate_geo_findings(questions_csv_path, results_csv_path, report_path)
    except (AuditRunnerError, WriteAuditResultError, ReportGeneratorError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"GEO findings report written to: {report_path}")
    for finding in findings:
        print(f"- {finding.title}: {finding.confidence} confidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
