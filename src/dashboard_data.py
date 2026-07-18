"""Reusable, non-UI data access for the Streamlit dashboard.

Wraps report_generator.py's existing, already-tested aggregation helpers
so the dashboard displays exactly the same figures the generated reports
do, instead of a second, independently-computed (and possibly divergent)
set of metrics. No Streamlit import here - this module is plain Python
and fully testable on its own, and it never writes to any audit data file
or report - it only reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from report_generator import ReportGeneratorError, compute_brand_visibility
from report_generator import load_audit_rows as _load_audit_rows


@dataclass(frozen=True)
class DashboardSummary:
    """Headline counts for the dashboard's overview tab."""

    total_rows: int
    brand_mentions: int
    brand_citation_rate: float | None
    rows_with_competitors: int
    rows_with_sources: int


def load_dashboard_rows(results_csv_path: str | Path) -> list[dict[str, str]]:
    """Load audit rows for the dashboard.

    Returns an empty list if the file does not exist yet, or is
    schema-valid but has no data rows - both are legitimate "nothing to
    show yet" states for a read-only dashboard and should not crash it.
    A file that exists but fails schema validation still raises
    WriteAuditResultError, since that indicates real data corruption
    worth surfacing rather than silently hiding.
    """
    path = Path(results_csv_path)
    if not path.is_file():
        return []

    try:
        return _load_audit_rows(str(path))
    except ReportGeneratorError:
        return []


def build_dashboard_summary(rows: list[dict[str, str]]) -> DashboardSummary:
    """Build the dashboard's headline metrics from already-loaded rows."""
    visibility = compute_brand_visibility(rows)
    rows_with_competitors = sum(1 for r in rows if (r.get("competitors_cited") or "").strip())
    rows_with_sources = sum(1 for r in rows if (r.get("sources_cited") or "").strip())

    return DashboardSummary(
        total_rows=len(rows),
        brand_mentions=visibility["y"],
        brand_citation_rate=visibility["rate"],
        rows_with_competitors=rows_with_competitors,
        rows_with_sources=rows_with_sources,
    )


def most_recent_run_date(rows: list[dict[str, str]]) -> str | None:
    """The most recent run_date across all rows (ISO "YYYY-MM-DD" strings
    sort correctly with a plain max()), or None if there are no rows or
    none have a run_date value."""
    dates = [r.get("run_date", "").strip() for r in rows if (r.get("run_date") or "").strip()]
    return max(dates) if dates else None


REPORT_TITLES = {
    "audit_report": "Audit Report",
    "GEO_FINDINGS": "GEO Findings",
    "GEO_RECOMMENDATIONS": "GEO Recommendations",
    "GEO_PROGRESS": "GEO Progress",
}


def report_display_title(report_path: str | Path) -> str:
    """A readable tab/selector title for a report file, preserving the
    "GEO" acronym rather than title-casing it into "Geo"."""
    stem = Path(report_path).stem
    return REPORT_TITLES.get(stem, stem.replace("_", " ").title())


def list_report_files(report_directory: str | Path) -> list[Path]:
    """List available Markdown reports, sorted by name. Returns an empty
    list if the directory does not exist."""
    directory = Path(report_directory)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.md"))


def read_markdown_report(report_path: str | Path) -> str:
    """Read a Markdown report's text, or a clear placeholder if missing."""
    path = Path(report_path)
    if not path.is_file():
        return "Report not available."
    return path.read_text(encoding="utf-8")
