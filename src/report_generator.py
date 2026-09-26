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

from audit_config import AuditConfig, AuditConfigError, default_audit_config, parse_audit_arg
from audit_runner import AuditRunnerError, load_questions
from write_single_audit_result import WriteAuditResultError, load_existing_results

# Backwards-compatible aliases for the default audit's values. Functions
# take an optional audit_config instead of reading these directly.
_DEFAULT_AUDIT_CONFIG = default_audit_config()

DEFAULT_QUESTIONS_FILE = _DEFAULT_AUDIT_CONFIG.questions_file
DEFAULT_RESULTS_FILE = _DEFAULT_AUDIT_CONFIG.results_file
DEFAULT_REPORT_FILE = _DEFAULT_AUDIT_CONFIG.audit_report_file

BRAND = _DEFAULT_AUDIT_CONFIG.brand
MARKET = _DEFAULT_AUDIT_CONFIG.market
CATEGORY = _DEFAULT_AUDIT_CONFIG.category

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


def compute_overview(
    rows: list[dict[str, str]], generated_at: date, *, audit_config: AuditConfig | None = None
) -> dict:
    audit_config = audit_config or _DEFAULT_AUDIT_CONFIG
    engines = sorted({r["engine"] for r in rows if r.get("engine")})
    unique_questions = {r["question_id"] for r in rows if r.get("question_id")}
    return {
        "brand": audit_config.brand,
        "market": audit_config.market,
        "category": audit_config.category,
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


def gemini_coverage_complete(rows: list[dict[str, str]], questions: list[dict[str, str]]) -> bool:
    """True only when every question in the library has a structurally
    complete Gemini result row. Uses the structured batch runner's
    is_structurally_complete, so there is one definition of completeness;
    raw-answer-only Gemini rows and rows from other engines (e.g.
    Perplexity) do not count."""
    # Imported here so reporting does not load the batch runner (and the
    # Gemini SDK) unless coverage is actually being assessed.
    from run_structured_batch_audit import TARGET_ENGINE, is_structurally_complete

    if not questions:
        return False
    gemini_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("engine") == TARGET_ENGINE:
            gemini_rows.setdefault(row.get("question_id", ""), []).append(row)
    return all(
        any(is_structurally_complete(row, question) for row in gemini_rows.get(question["question_id"], []))
        for question in questions
    )


def _build_executive_summary(
    overview: dict, engine_counts: Counter, total_question_count: int, coverage_complete: bool = False
) -> str:
    perplexity_n = engine_counts.get("Perplexity", 0)
    gemini_n = engine_counts.get("Gemini", 0)
    other_engines = {e: c for e, c in engine_counts.items() if e not in ("Perplexity", "Gemini")}
    other_note = ""
    if other_engines:
        other_note = " and " + ", ".join(f"{c} via {e}" for e, c in sorted(other_engines.items()))

    opening = (
        f"This audit currently holds {overview['total_rows']} recorded result(s), covering "
        f"{overview['unique_questions']} of the {total_question_count} questions in the buyer "
        f"question library, across {_format_list_or_none(overview['engines'])}."
    )
    if perplexity_n:
        sources = (
            f" {perplexity_n} row(s) were manually recorded via Perplexity and {gemini_n} row(s) were "
            f"generated programmatically via Gemini{other_note}."
        )
    elif gemini_n:
        sources = f" {gemini_n} row(s) were generated programmatically via Gemini{other_note}."
    elif other_engines:
        sources = " " + "; ".join(f"{c} row(s) were recorded via {e}" for e, c in sorted(other_engines.items())) + "."
    else:
        sources = ""

    if coverage_complete:
        closing = (
            f" Structured Gemini results are recorded for all {total_question_count} questions in the "
            f"buyer question library. No comparative visibility score has been calculated."
        )
    else:
        closing = (
            " This dataset is partial: it does not yet cover the full question library, and no "
            "comparative visibility score has been calculated."
        )
    return opening + sources + closing


def generate_report_markdown(
    rows: list[dict[str, str]],
    generated_at: date,
    total_question_count: int,
    *,
    audit_config: AuditConfig | None = None,
    questions: list[dict[str, str]] | None = None,
) -> str:
    """Build the report's Markdown text from already-loaded rows.

    Deterministic: the same rows, generated_at, total_question_count,
    audit_config and questions always produce byte-identical output (all
    groupings are explicitly sorted; nothing depends on wall-clock time
    other than generated_at, which is passed in rather than read
    internally). audit_config defaults to the default audit.

    questions (the audit's question library rows) lets the report state
    that the dataset is complete when every question has a structurally
    complete Gemini result (see gemini_coverage_complete); without it the
    dataset is described as partial, as before.
    """
    audit_config = audit_config or _DEFAULT_AUDIT_CONFIG
    coverage_complete = questions is not None and gemini_coverage_complete(rows, questions)
    overview = compute_overview(rows, generated_at, audit_config=audit_config)
    engine_counts = compute_engine_coverage(rows)
    stage_counts = compute_stage_coverage(rows)
    visibility = compute_brand_visibility(rows)
    position = compute_brand_position(rows)
    sentiment = compute_sentiment_summary(rows)
    competitors = compute_mention_frequency(rows, "competitors_cited")
    sources = compute_mention_frequency(rows, "sources_cited")

    lines: list[str] = []
    lines.append(f"# SignalScope AI Audit Report — {audit_config.report_subject}")
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
    lines.append(_build_executive_summary(overview, engine_counts, total_question_count, coverage_complete))
    lines.append("")

    lines.append("## Coverage by Engine")
    lines.append("")
    if engine_counts.get("Perplexity", 0):
        lines.append(f"- Perplexity row count: {engine_counts['Perplexity']}")
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
    lines.append(f"- Y ({audit_config.brand} cited): {visibility['y']}")
    lines.append(f"- N ({audit_config.brand} not cited): {visibility['n']}")
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
    if coverage_complete:
        lines.append(f"- Structured Gemini results are recorded for all {total_question_count} buyer questions.")
    else:
        lines.append("- This is a partial audit dataset.")
        lines.append(f"- Not all {total_question_count} buyer questions have Gemini results yet.")
    lines.append("- Blank structured fields were not treated as negative findings.")
    if engine_counts.get("Perplexity", 0):
        lines.append("- Perplexity rows were manually recorded.")
    if engine_counts.get("Gemini", 0):
        lines.append("- Gemini rows were generated programmatically.")
    if coverage_complete:
        lines.append(
            "- Each result reflects the AI response recorded on its run date; the same questions "
            "may be answered differently if asked again."
        )
        lines.append("- Conclusions are limited to the recorded results.")
    else:
        lines.append("- Conclusions are limited to the currently available records.")
    lines.append("")

    lines.append("## Next Step")
    lines.append("")
    if coverage_complete:
        lines.append(
            "Review these results alongside the GEO findings and recommendations reports. No "
            "comparative visibility score has been calculated."
        )
    else:
        lines.append(
            "Complete the remaining structured Gemini audit questions before producing a "
            "final comparative visibility score."
        )
    lines.append("")

    return "\n".join(lines)


def generate_report(
    questions_csv_path: str | None = None,
    results_csv_path: str | None = None,
    report_path: str | None = None,
    generated_at: date | None = None,
    *,
    audit_config: AuditConfig | None = None,
) -> str:
    """Load the question library and audit results, build the Markdown
    report, and write it to report_path (creating the directory if
    needed). Returns the report's Markdown text.

    audit_config defaults to the default audit; any path left as None is
    taken from it, so a non-default audit never writes to another
    audit's files.

    Raises AuditRunnerError for a missing/invalid/empty question file,
    WriteAuditResultError for a missing/schema-invalid results file, or
    ReportGeneratorError if the results file has no data rows.
    """
    audit_config = audit_config or _DEFAULT_AUDIT_CONFIG
    if questions_csv_path is None:
        questions_csv_path = audit_config.questions_file
    if results_csv_path is None:
        results_csv_path = audit_config.results_file
    if report_path is None:
        report_path = audit_config.audit_report_file
    generated_at = generated_at or date.today()

    all_questions = load_questions(questions_csv_path)
    rows = load_audit_rows(results_csv_path)

    markdown = generate_report_markdown(
        rows, generated_at, len(all_questions), audit_config=audit_config, questions=all_questions
    )

    out_path = Path(report_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    return markdown


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        audit_config, argv = parse_audit_arg(argv)
    except AuditConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    paths = audit_config or _DEFAULT_AUDIT_CONFIG
    questions_csv_path = argv[0] if len(argv) > 0 else paths.questions_file
    results_csv_path = argv[1] if len(argv) > 1 else paths.results_file
    report_path = argv[2] if len(argv) > 2 else paths.audit_report_file

    try:
        generate_report(questions_csv_path, results_csv_path, report_path, audit_config=audit_config)
    except (AuditRunnerError, WriteAuditResultError, ReportGeneratorError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Report written to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
