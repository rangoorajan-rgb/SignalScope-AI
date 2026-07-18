"""GEO measurement engine for SignalScope AI.

Compares two audit datasets - a baseline and a follow-up - to measure
whether AI search visibility has changed. The company performs the
implementation of any recommendations; this engine only measures the
resulting difference between two audit snapshots.

Fully deterministic - no Gemini call. This is a factual comparison of
already-computed metrics, reusing report_generator.py's and
geo_findings_analyzer.py's existing aggregation helpers for each dataset
independently, then diffing the results. Neither the Audit Engine, the
Insights Engine (geo_findings_analyzer.py), nor the Recommendation Engine
is modified.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from audit_runner import AuditRunnerError, load_questions
from geo_findings_analyzer import (
    ALL_BUYER_JOURNEY_STAGES,
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
)
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
DEFAULT_PROGRESS_REPORT_FILE = "reports/boots-uk-health-beauty/GEO_PROGRESS.md"

IMPROVED = "Improved"
DECLINED = "Declined"
NO_CHANGE = "No Change"
INFORMATIONAL = "Informational"

MATURITY_TIERS = ["Early", "Developing", "Established"]


class MeasurementEngineError(Exception):
    """Raised for problems generating a GEO progress comparison."""


@dataclass(frozen=True)
class MetricComparison:
    """One before/after metric comparison. direction is one of Improved,
    Declined, No Change, or Informational (for metrics with no inherent
    good/bad direction - see Competitor Mention Change)."""

    metric_name: str
    before: str
    after: str
    difference: str
    direction: str


@dataclass(frozen=True)
class Progress:
    """The structured result of comparing a baseline audit dataset against
    a follow-up one. This is the primary artefact; GEO_PROGRESS.md is
    rendered from it, never the other way around."""

    brand: str
    market: str
    category: str
    baseline_row_count: int
    followup_row_count: int
    baseline_unique_questions: int
    followup_unique_questions: int
    metrics: list[MetricComparison]
    overall_assessment: str
    generated_at: date


def _direction_higher_is_better(before: float, after: float) -> str:
    if after > before:
        return IMPROVED
    if after < before:
        return DECLINED
    return NO_CHANGE


def _format_rate_or_na(rate: float | None) -> str:
    return f"{rate:.1f}%" if rate is not None else "N/A (no data)"


def _metric_brand_visibility(
    baseline_rows: list[dict[str, str]], followup_rows: list[dict[str, str]]
) -> MetricComparison:
    before_rate = compute_brand_visibility(baseline_rows)["rate"]
    after_rate = compute_brand_visibility(followup_rows)["rate"]

    if before_rate is None or after_rate is None:
        return MetricComparison(
            "Brand Visibility",
            _format_rate_or_na(before_rate),
            _format_rate_or_na(after_rate),
            "N/A (insufficient data)",
            NO_CHANGE,
        )

    diff = after_rate - before_rate
    return MetricComparison(
        "Brand Visibility",
        f"{before_rate:.1f}%",
        f"{after_rate:.1f}%",
        f"{diff:+.1f}pp",
        _direction_higher_is_better(before_rate, after_rate),
    )


def _metric_brand_mention_frequency(
    baseline_rows: list[dict[str, str]], followup_rows: list[dict[str, str]]
) -> MetricComparison:
    before_count = compute_brand_visibility(baseline_rows)["y"]
    after_count = compute_brand_visibility(followup_rows)["y"]
    diff = after_count - before_count
    return MetricComparison(
        "Brand Mention Frequency",
        str(before_count),
        str(after_count),
        f"{diff:+d}",
        _direction_higher_is_better(before_count, after_count),
    )


def _metric_competitor_mentions(
    baseline_rows: list[dict[str, str]], followup_rows: list[dict[str, str]]
) -> MetricComparison:
    before_total = sum(count for _, count in compute_mention_frequency(baseline_rows, "competitors_cited"))
    after_total = sum(count for _, count in compute_mention_frequency(followup_rows, "competitors_cited"))
    diff = after_total - before_total
    # Informational only, by design: more or fewer competitor mentions is
    # not inherently good or bad for the brand, so no direction judgement
    # is applied here.
    return MetricComparison(
        "Competitor Mention Change",
        str(before_total),
        str(after_total),
        f"{diff:+d}",
        INFORMATIONAL,
    )


def _positive_sentiment_rate(rows: list[dict[str, str]]) -> float | None:
    sentiment = compute_sentiment_summary(rows)
    considered = len(rows) - sentiment["excluded"]
    if considered == 0:
        return None
    return sentiment["positive"] / considered * 100


def _metric_sentiment(
    baseline_rows: list[dict[str, str]], followup_rows: list[dict[str, str]]
) -> MetricComparison:
    before_rate = _positive_sentiment_rate(baseline_rows)
    after_rate = _positive_sentiment_rate(followup_rows)

    if before_rate is None or after_rate is None:
        return MetricComparison(
            "Sentiment Change (Positive Rate)",
            _format_rate_or_na(before_rate),
            _format_rate_or_na(after_rate),
            "N/A (insufficient data)",
            NO_CHANGE,
        )

    diff = after_rate - before_rate
    return MetricComparison(
        "Sentiment Change (Positive Rate)",
        f"{before_rate:.1f}%",
        f"{after_rate:.1f}%",
        f"{diff:+.1f}pp",
        _direction_higher_is_better(before_rate, after_rate),
    )


def _source_coverage_rate(rows: list[dict[str, str]]) -> float | None:
    if not rows:
        return None
    with_sources = sum(1 for r in rows if (r.get("sources_cited") or "").strip())
    return with_sources / len(rows) * 100


def _metric_authority_sources(
    baseline_rows: list[dict[str, str]], followup_rows: list[dict[str, str]]
) -> MetricComparison:
    before_rate = _source_coverage_rate(baseline_rows)
    after_rate = _source_coverage_rate(followup_rows)

    if before_rate is None or after_rate is None:
        return MetricComparison(
            "Authority Source Change",
            _format_rate_or_na(before_rate),
            _format_rate_or_na(after_rate),
            "N/A (insufficient data)",
            NO_CHANGE,
        )

    diff = after_rate - before_rate
    return MetricComparison(
        "Authority Source Change",
        f"{before_rate:.1f}%",
        f"{after_rate:.1f}%",
        f"{diff:+.1f}pp",
        _direction_higher_is_better(before_rate, after_rate),
    )


def _stage_coverage_count(rows: list[dict[str, str]]) -> int:
    stage_counts = compute_stage_coverage(rows)
    return sum(1 for stage in ALL_BUYER_JOURNEY_STAGES if stage_counts.get(stage, 0) > 0)


def _metric_funnel_stage_coverage(
    baseline_rows: list[dict[str, str]], followup_rows: list[dict[str, str]]
) -> MetricComparison:
    before_count = _stage_coverage_count(baseline_rows)
    after_count = _stage_coverage_count(followup_rows)
    diff = after_count - before_count
    total = len(ALL_BUYER_JOURNEY_STAGES)
    return MetricComparison(
        "Funnel Stage Coverage",
        f"{before_count} of {total}",
        f"{after_count} of {total}",
        f"{diff:+d}",
        _direction_higher_is_better(before_count, after_count),
    )


def _maturity_tier(rows: list[dict[str, str]], total_question_count: int) -> str:
    """Early / Developing / Established tier.

    This intentionally mirrors geo_findings_analyzer.py's private
    _finding_geo_maturity tier rule exactly, using the same imported
    threshold constants so the two stay in sync - that function is
    private and Sprint 13 must not be modified, so the branch logic
    itself is duplicated here (approved trade-off).
    """
    unique_questions = len({r["question_id"] for r in rows if r.get("question_id")})
    coverage_ratio = (unique_questions / total_question_count) if total_question_count else 0.0
    visibility_rate = compute_brand_visibility(rows)["rate"] or 0.0
    visibility_ratio = visibility_rate / 100

    if coverage_ratio >= HIGH_CONFIDENCE_THRESHOLD and visibility_ratio >= 0.5:
        return "Established"
    if coverage_ratio >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "Developing"
    return "Early"


def _metric_geo_maturity(
    baseline_rows: list[dict[str, str]], followup_rows: list[dict[str, str]], total_question_count: int
) -> MetricComparison:
    before_tier = _maturity_tier(baseline_rows, total_question_count)
    after_tier = _maturity_tier(followup_rows, total_question_count)
    before_rank = MATURITY_TIERS.index(before_tier)
    after_rank = MATURITY_TIERS.index(after_tier)

    difference = "No change in tier" if before_tier == after_tier else f"{before_tier} -> {after_tier}"

    return MetricComparison(
        "Overall GEO Maturity",
        before_tier,
        after_tier,
        difference,
        _direction_higher_is_better(before_rank, after_rank),
    )


def _build_overall_assessment(metrics: list[MetricComparison]) -> str:
    improved = sum(1 for m in metrics if m.direction == IMPROVED)
    declined = sum(1 for m in metrics if m.direction == DECLINED)
    no_change = sum(1 for m in metrics if m.direction == NO_CHANGE)
    informational = sum(1 for m in metrics if m.direction == INFORMATIONAL)
    evaluated = improved + declined + no_change

    return (
        f"Of {evaluated} directionally-evaluated metric(s), {improved} improved, "
        f"{declined} declined, and {no_change} showed no change. {informational} "
        f"metric(s) are reported as informational only, with no improvement/decline "
        f"judgement applied."
    )


def compare_audits(
    baseline_rows: list[dict[str, str]],
    followup_rows: list[dict[str, str]],
    total_question_count: int,
    brand: str = BRAND,
    market: str = MARKET,
    category: str = CATEGORY,
    generated_at: date | None = None,
) -> Progress:
    """Compare two already-loaded audit datasets and return a structured
    Progress object. Deterministic: the same two datasets and
    total_question_count always produce an identical Progress.

    Raises MeasurementEngineError if either dataset has no rows.
    """
    if not baseline_rows:
        raise MeasurementEngineError("Baseline audit dataset has no rows to compare.")
    if not followup_rows:
        raise MeasurementEngineError("Follow-up audit dataset has no rows to compare.")

    generated_at = generated_at or date.today()

    metrics = [
        _metric_brand_visibility(baseline_rows, followup_rows),
        _metric_brand_mention_frequency(baseline_rows, followup_rows),
        _metric_competitor_mentions(baseline_rows, followup_rows),
        _metric_sentiment(baseline_rows, followup_rows),
        _metric_authority_sources(baseline_rows, followup_rows),
        _metric_funnel_stage_coverage(baseline_rows, followup_rows),
        _metric_geo_maturity(baseline_rows, followup_rows, total_question_count),
    ]

    baseline_unique_questions = len({r["question_id"] for r in baseline_rows if r.get("question_id")})
    followup_unique_questions = len({r["question_id"] for r in followup_rows if r.get("question_id")})

    return Progress(
        brand=brand,
        market=market,
        category=category,
        baseline_row_count=len(baseline_rows),
        followup_row_count=len(followup_rows),
        baseline_unique_questions=baseline_unique_questions,
        followup_unique_questions=followup_unique_questions,
        metrics=metrics,
        overall_assessment=_build_overall_assessment(metrics),
        generated_at=generated_at,
    )


def render_markdown(progress: Progress, is_validation_run: bool = False) -> str:
    """Render the Markdown GEO progress report purely from an already-
    computed Progress object - the structured comparison is the source of
    truth, not this text."""
    lines: list[str] = []
    lines.append("# SignalScope AI GEO Progress Report — Boots UK Health & Beauty")
    lines.append("")

    if is_validation_run:
        lines.append(
            "> **Structural validation run.** This comparison uses the same audit "
            "dataset as both the baseline and the follow-up. It exists to prove the "
            "Measurement Engine runs correctly end to end - it is **not** a real "
            "measurement of change. Genuine progress measurement requires a real "
            "follow-up audit, captured after recommendations have actually been "
            "implemented."
        )
        lines.append("")

    lines.append("## Report Overview")
    lines.append("")
    lines.append(f"- Brand: {progress.brand}")
    lines.append(f"- Market: {progress.market}")
    lines.append(f"- Category: {progress.category}")
    lines.append(
        f"- Baseline audit: {progress.baseline_row_count} row(s), "
        f"{progress.baseline_unique_questions} unique question(s)"
    )
    lines.append(
        f"- Follow-up audit: {progress.followup_row_count} row(s), "
        f"{progress.followup_unique_questions} unique question(s)"
    )
    lines.append(f"- Report generation date: {progress.generated_at.isoformat()}")
    lines.append("")

    lines.append("## Executive Summary")
    lines.append("")
    lines.append(progress.overall_assessment)
    lines.append("")

    lines.append("## KPI Comparison Table")
    lines.append("")
    lines.append("| Metric | Before | After | Difference | Direction |")
    lines.append("|---|---|---|---|---|")
    for m in progress.metrics:
        lines.append(f"| {m.metric_name} | {m.before} | {m.after} | {m.difference} | {m.direction} |")
    lines.append("")

    lines.append("## Improvement Summary")
    lines.append("")
    improved = [m for m in progress.metrics if m.direction == IMPROVED]
    declined = [m for m in progress.metrics if m.direction == DECLINED]
    no_change = [m for m in progress.metrics if m.direction == NO_CHANGE]
    informational = [m for m in progress.metrics if m.direction == INFORMATIONAL]
    lines.append(f"- Improved ({len(improved)}): {', '.join(m.metric_name for m in improved) or 'None'}")
    lines.append(f"- Declined ({len(declined)}): {', '.join(m.metric_name for m in declined) or 'None'}")
    lines.append(f"- No Change ({len(no_change)}): {', '.join(m.metric_name for m in no_change) or 'None'}")
    lines.append(
        f"- Informational only ({len(informational)}): "
        f"{', '.join(m.metric_name for m in informational) or 'None'}"
    )
    lines.append("")

    lines.append("## Detailed Metrics")
    lines.append("")
    for index, m in enumerate(progress.metrics, start=1):
        lines.append(f"### {index}. {m.metric_name}")
        lines.append("")
        lines.append(f"- **Before:** {m.before}")
        lines.append(f"- **After:** {m.after}")
        lines.append(f"- **Difference:** {m.difference}")
        lines.append(f"- **Direction:** {m.direction}")
        lines.append("")

    lines.append("## Overall Assessment")
    lines.append("")
    lines.append(progress.overall_assessment)
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- These figures reflect measured differences between two recorded audit "
        "datasets. They are not guaranteed business outcomes, and do not imply "
        "causation from any specific action taken."
    )
    lines.append(
        "- Brand Mention Frequency and Competitor Mention Change are raw counts, "
        "not rates; if the baseline and follow-up datasets cover different numbers "
        "of questions, these counts are not directly comparable on a like-for-like "
        "basis."
    )
    lines.append(
        "- Competitor Mention Change is reported for information only; no "
        "improvement or decline judgement is applied to it."
    )
    if is_validation_run:
        lines.append(
            "- This report is a structural validation run (baseline and follow-up "
            "are the same dataset). Genuine progress measurement requires a real "
            "follow-up audit conducted after recommendations have been implemented."
        )
    lines.append("")

    return "\n".join(lines)


def generate_geo_progress(
    baseline_results_csv_path: str,
    followup_results_csv_path: str,
    questions_csv_path: str = DEFAULT_QUESTIONS_FILE,
    report_path: str = DEFAULT_PROGRESS_REPORT_FILE,
    generated_at: date | None = None,
    is_validation_run: bool = False,
) -> tuple[Progress, str]:
    """Load two audit datasets, compare them, and render + write the
    Markdown progress report.

    Returns (progress, markdown_text). Raises AuditRunnerError for a
    missing/invalid question file, WriteAuditResultError for a missing/
    schema-invalid results file (baseline or follow-up), ReportGeneratorError
    if either results file has no data rows, or MeasurementEngineError for
    any other comparison problem.
    """
    generated_at = generated_at or date.today()

    all_questions = load_questions(questions_csv_path)
    baseline_rows = load_audit_rows(baseline_results_csv_path)
    followup_rows = load_audit_rows(followup_results_csv_path)

    progress = compare_audits(baseline_rows, followup_rows, len(all_questions), generated_at=generated_at)
    markdown = render_markdown(progress, is_validation_run=is_validation_run)

    out_path = Path(report_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    return progress, markdown


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(
            "Usage: python src/measurement_engine.py <baseline_results.csv> "
            "<followup_results.csv> [questions.csv] [report.md]",
            file=sys.stderr,
        )
        return 1

    baseline_path = argv[0]
    followup_path = argv[1]
    questions_csv_path = argv[2] if len(argv) > 2 else DEFAULT_QUESTIONS_FILE
    report_path = argv[3] if len(argv) > 3 else DEFAULT_PROGRESS_REPORT_FILE
    is_validation_run = Path(baseline_path).resolve() == Path(followup_path).resolve()

    try:
        progress, _ = generate_geo_progress(
            baseline_path,
            followup_path,
            questions_csv_path,
            report_path,
            is_validation_run=is_validation_run,
        )
    except (AuditRunnerError, WriteAuditResultError, ReportGeneratorError, MeasurementEngineError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"GEO progress report written to: {report_path}")
    if is_validation_run:
        print("NOTE: baseline and follow-up paths are identical - this is a structural validation run only.")
    print(progress.overall_assessment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
