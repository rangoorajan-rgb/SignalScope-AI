"""Audit report generator for SignalScope AI.

Builds a single Markdown audit report from the existing rows in
audit_results.csv for one audit instance. Reporting only: this module
never calls Gemini or any other API, never modifies any audit data file,
and never invents a score or finding beyond what the recorded rows
actually contain.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date
from pathlib import Path

from audit_runner import AuditRunnerError, load_questions
from write_single_audit_result import WriteAuditResultError, load_existing_results

DEFAULT_QUESTIONS_FILE = "audits/boots-uk-health-beauty/buyer_questions.csv"
DEFAULT_RESULTS_FILE = "audits/boots-uk-health-beauty/audit_results.csv"
DEFAULT_REPORT_FILE = "reports/boots-uk-health-beauty/audit_report.md"

BRAND = "Boots"
MARKET = "United Kingdom"
CATEGORY = "Health & Beauty Retail"

VALID_BRAND_CITED = {"Y", "N"}
VALID_SENTIMENTS = {"Positive", "Neutral", "Negative"}

FINDINGS_TABLE_COLUMNS = [
    "question_id",
    "funnel_stage",
    "engine",
    "brand_cited",
    "brand_position",
    "sentiment",
    "competitors_cited",
    "answer_snippet",
]


class ReportGeneratorError(Exception):
    """Raised for problems generating an audit report."""


def load_audit_rows(results_csv_path: str) -> list[dict[str, str]]:
    """Load and schema-validate audit_results.csv, then confirm it has data.

    Reuses write_single_audit_result.load_existing_results for the file-
    existence and 11-column schema check. Raises ReportGeneratorError if
    the file is schema-valid but contains no data rows, since a report
    cannot be produced from an empty dataset.
    """
    rows = load_existing_results(results_csv_path)
    if not rows:
        raise ReportGeneratorError(
            f"Audit results file has no data rows to report on: {results_csv_path}"
        )
    return rows


def _parse_semicolon_list(value: str | None) -> list[str]:
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(";") if item.strip()]


def compute_overview(rows: list[dict[str, str]], generated_at: date) -> dict:
    engines = sorted({r["engine"] for r in rows if r.get("engine")})
    unique_questions = {r["question_id"] for r in rows if r.get("question_id")}
    return {
        "brand": BRAND,
        "market": MARKET,
        "category": CATEGORY,
        "engines": engines,
        "total_rows": len(rows),
        "unique_questions": len(unique_questions),
        "generated_at": generated_at.isoformat(),
    }


def compute_engine_coverage(rows: list[dict[str, str]]) -> Counter:
    return Counter(r["engine"] for r in rows if r.get("engine"))


def compute_stage_coverage(rows: list[dict[str, str]]) -> Counter:
    return Counter(r["funnel_stage"] for r in rows if r.get("funnel_stage"))


def compute_brand_visibility(rows: list[dict[str, str]]) -> dict:
    considered = [r for r in rows if r.get("brand_cited") in VALID_BRAND_CITED]
    y_count = sum(1 for r in considered if r["brand_cited"] == "Y")
    n_count = sum(1 for r in considered if r["brand_cited"] == "N")
    rate = (y_count / len(considered) * 100) if considered else None
    return {
        "y": y_count,
        "n": n_count,
        "rate": rate,
        "considered": len(considered),
        "excluded": len(rows) - len(considered),
    }


def compute_brand_position(rows: list[dict[str, str]]) -> dict:
    positions: list[int] = []
    for r in rows:
        value = (r.get("brand_position") or "").strip()
        if value.isdigit() and int(value) >= 1:
            positions.append(int(value))
    if not positions:
        return {"count": 0, "average": None, "best": None}
    return {
        "count": len(positions),
        "average": sum(positions) / len(positions),
        "best": min(positions),
    }


def compute_sentiment_summary(rows: list[dict[str, str]]) -> dict:
    considered = [r for r in rows if r.get("sentiment") in VALID_SENTIMENTS]
    counts = Counter(r["sentiment"] for r in considered)
    return {
        "positive": counts.get("Positive", 0),
        "neutral": counts.get("Neutral", 0),
        "negative": counts.get("Negative", 0),
        "excluded": len(rows) - len(considered),
    }


def compute_mention_frequency(rows: list[dict[str, str]], field_name: str) -> list[tuple[str, int]]:
    """Count mentions of each semicolon-separated value in field_name across
    all rows. Sorted by frequency descending, then alphabetically."""
    counter: Counter = Counter()
    for r in rows:
        for item in _parse_semicolon_list(r.get(field_name)):
            counter[item] += 1
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def _format_list_or_none(items: list[str]) -> str:
    return ", ".join(items) if items else "None"


def _format_rate(rate: float | None) -> str:
    return f"{rate:.1f}%" if rate is not None else "N/A"


def _escape_table_cell(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")


def _build_executive_summary(overview: dict, engine_counts: Counter, total_question_count: int) -> str:
    perplexity_n = engine_counts.get("Perplexity", 0)
    gemini_n = engine_counts.get("Gemini", 0)
    other_engines = {e: c for e, c in engine_counts.items() if e not in ("Perplexity", "Gemini")}
    other_note = ""
    if other_engines:
        other_note = " and " + ", ".join(f"{c} via {e}" for e, c in sorted(other_engines.items()))

    return (
        f"This audit currently holds {overview['total_rows']} recorded result(s), covering "
        f"{overview['unique_questions']} of the {total_question_count} questions in the buyer "
        f"question library, across {_format_list_or_none(overview['engines'])}. {perplexity_n} "
        f"row(s) were manually recorded via Perplexity and {gemini_n} row(s) were generated "
        f"programmatically via Gemini{other_note}. This dataset is partial: it does not yet cover "
        f"the full question library, and no comparative visibility score has been calculated."
    )


def generate_report_markdown(
    rows: list[dict[str, str]], generated_at: date, total_question_count: int
) -> str:
    """Build the report's Markdown text from already-loaded rows.

    Deterministic: the same rows, generated_at, and total_question_count
    always produce byte-identical output (all groupings are explicitly
    sorted; nothing depends on wall-clock time other than generated_at,
    which is passed in rather than read internally).
    """
    overview = compute_overview(rows, generated_at)
    engine_counts = compute_engine_coverage(rows)
    stage_counts = compute_stage_coverage(rows)
    visibility = compute_brand_visibility(rows)
    position = compute_brand_position(rows)
    sentiment = compute_sentiment_summary(rows)
    competitors = compute_mention_frequency(rows, "competitors_cited")
    sources = compute_mention_frequency(rows, "sources_cited")

    lines: list[str] = []
    lines.append("# SignalScope AI Audit Report — Boots UK Health & Beauty")
    lines.append("")

    lines.append("## Audit Overview")
    lines.append("")
    lines.append(f"- Brand: {overview['brand']}")
    lines.append(f"- Market: {overview['market']}")
    lines.append(f"- Category: {overview['category']}")
    lines.append(f"- Engines represented: {_format_list_or_none(overview['engines'])}")
    lines.append(f"- Total audit result rows: {overview['total_rows']}")
    lines.append(f"- Number of unique questions represented: {overview['unique_questions']}")
    lines.append(f"- Report generation date: {overview['generated_at']}")
    lines.append("")

    lines.append("## Executive Summary")
    lines.append("")
    lines.append(_build_executive_summary(overview, engine_counts, total_question_count))
    lines.append("")

    lines.append("## Coverage by Engine")
    lines.append("")
    lines.append(f"- Perplexity row count: {engine_counts.get('Perplexity', 0)}")
    lines.append(f"- Gemini row count: {engine_counts.get('Gemini', 0)}")
    for engine in sorted(e for e in engine_counts if e not in ("Perplexity", "Gemini")):
        lines.append(f"- {engine} row count: {engine_counts[engine]}")
    lines.append("")

    lines.append("## Coverage by Buyer Journey Stage")
    lines.append("")
    if stage_counts:
        for stage in sorted(stage_counts):
            lines.append(f"- {stage}: {stage_counts[stage]}")
    else:
        lines.append("- No buyer journey stage data available.")
    lines.append("")

    lines.append("## Brand Visibility")
    lines.append("")
    lines.append(f"- Y (Boots cited): {visibility['y']}")
    lines.append(f"- N (Boots not cited): {visibility['n']}")
    lines.append(f"- Brand citation rate: {_format_rate(visibility['rate'])}")
    lines.append(f"- Rows excluded (brand_cited blank): {visibility['excluded']}")
    lines.append("")

    lines.append("## Brand Position")
    lines.append("")
    if position["count"] > 0:
        lines.append(f"- Ranked appearances: {position['count']}")
        lines.append(f"- Average position: {position['average']:.2f}")
        lines.append(f"- Best position: {position['best']}")
    else:
        lines.append("- Insufficient data: no rows contain a valid numeric brand_position value.")
    lines.append("")

    lines.append("## Sentiment Summary")
    lines.append("")
    lines.append(f"- Positive: {sentiment['positive']}")
    lines.append(f"- Neutral: {sentiment['neutral']}")
    lines.append(f"- Negative: {sentiment['negative']}")
    lines.append(f"- Excluded (blank sentiment): {sentiment['excluded']}")
    lines.append("")

    lines.append("## Competitors Mentioned")
    lines.append("")
    if competitors:
        for name, count in competitors:
            lines.append(f"- {name}: {count}")
    else:
        lines.append("- No competitors recorded in the available data.")
    lines.append("")

    lines.append("## Sources Mentioned")
    lines.append("")
    if sources:
        for name, count in sources:
            lines.append(f"- {name}: {count}")
    else:
        lines.append("- No sources recorded in the available data.")
    lines.append("")

    lines.append("## Question-Level Findings")
    lines.append("")
    lines.append("| " + " | ".join(FINDINGS_TABLE_COLUMNS) + " |")
    lines.append("|" + "|".join(["---"] * len(FINDINGS_TABLE_COLUMNS)) + "|")
    for r in rows:
        cells = [_escape_table_cell(r.get(col, "")) for col in FINDINGS_TABLE_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    lines.append("- This is a partial audit dataset.")
    lines.append(f"- Not all {total_question_count} buyer questions have Gemini results yet.")
    lines.append("- Blank structured fields were not treated as negative findings.")
    lines.append("- Perplexity rows were manually recorded.")
    lines.append("- Gemini rows were generated programmatically.")
    lines.append("- Conclusions are limited to the currently available records.")
    lines.append("")

    lines.append("## Next Step")
    lines.append("")
    lines.append(
        "Complete the remaining structured Gemini audit questions before producing a "
        "final comparative visibility score."
    )
    lines.append("")

    return "\n".join(lines)


def generate_report(
    questions_csv_path: str = DEFAULT_QUESTIONS_FILE,
    results_csv_path: str = DEFAULT_RESULTS_FILE,
    report_path: str = DEFAULT_REPORT_FILE,
    generated_at: date | None = None,
) -> str:
    """Load the question library and audit results, build the Markdown
    report, and write it to report_path (creating the directory if
    needed). Returns the report's Markdown text.

    Raises AuditRunnerError for a missing/invalid/empty question file,
    WriteAuditResultError for a missing/schema-invalid results file, or
    ReportGeneratorError if the results file has no data rows.
    """
    generated_at = generated_at or date.today()

    all_questions = load_questions(questions_csv_path)
    rows = load_audit_rows(results_csv_path)

    markdown = generate_report_markdown(rows, generated_at, len(all_questions))

    out_path = Path(report_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    return markdown


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    questions_csv_path = argv[0] if len(argv) > 0 else DEFAULT_QUESTIONS_FILE
    results_csv_path = argv[1] if len(argv) > 1 else DEFAULT_RESULTS_FILE
    report_path = argv[2] if len(argv) > 2 else DEFAULT_REPORT_FILE

    try:
        generate_report(questions_csv_path, results_csv_path, report_path)
    except (AuditRunnerError, WriteAuditResultError, ReportGeneratorError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Report written to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
