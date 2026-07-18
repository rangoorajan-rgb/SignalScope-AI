"""Streamlit dashboard for SignalScope AI."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

import config

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard_data import (  # noqa: E402
    build_dashboard_summary,
    list_report_files,
    load_dashboard_rows,
    most_recent_run_date,
    read_markdown_report,
    report_display_title,
)

AUDIT_DIRECTORY = PROJECT_ROOT / "audits" / "boots-uk-health-beauty"
REPORT_DIRECTORY = PROJECT_ROOT / "reports" / "boots-uk-health-beauty"

AUDIT_RESULTS_FILE = AUDIT_DIRECTORY / "audit_results.csv"


st.set_page_config(
    page_title="SignalScope AI",
    page_icon="📡",
    layout="wide",
)

st.title("📡 SignalScope AI")
st.caption(
    "Evidence-Driven Generative Engine Optimisation Intelligence Platform"
)

st.markdown(
    """
SignalScope AI measures how generative AI systems represent a brand,
analyses competitor visibility, generates evidence-based recommendations
and tracks improvement over time.
"""
)


@st.cache_data
def load_audit_results(file_path: Path) -> pd.DataFrame:
    """Load the existing structured audit results for table display."""
    if not file_path.exists():
        return pd.DataFrame()

    return pd.read_csv(file_path)


@st.cache_data
def load_summary(file_path: Path) -> dict | None:
    """Load audit rows via the shared, tested dashboard_data helpers and
    build the headline summary metrics. Returns None if the underlying
    data file has an invalid schema, so the caller can show a clear error
    instead of a raw traceback."""
    try:
        rows = load_dashboard_rows(file_path)
    except Exception as exc:  # noqa: BLE001 - surfaced via st.error below
        return {"error": str(exc)}

    summary = build_dashboard_summary(rows)
    return {
        "total_rows": summary.total_rows,
        "brand_mentions": summary.brand_mentions,
        "brand_citation_rate": summary.brand_citation_rate,
        "rows_with_competitors": summary.rows_with_competitors,
        "rows_with_sources": summary.rows_with_sources,
        "last_audit_date": most_recent_run_date(rows),
    }


audit_results = load_audit_results(AUDIT_RESULTS_FILE)
summary = load_summary(AUDIT_RESULTS_FILE)

with st.sidebar:
    st.header("Project")

    st.write(f"**Brand:** {config.COMPANY_NAME}")
    st.write(f"**Industry:** {config.INDUSTRY}")
    st.write("**Version:** 2.0.0")
    st.write("**Audit provider:** Google Gemini")

    if st.button("Refresh dashboard"):
        st.cache_data.clear()
        st.rerun()


dashboard_tab, audit_tab, reports_tab, about_tab = st.tabs(
    [
        "Dashboard",
        "Audit Evidence",
        "Reports",
        "About",
    ]
)


with dashboard_tab:
    with st.container(border=True):
        st.markdown("#### 📋 Current Project")
        last_audit_date = None
        if summary is not None and "error" not in summary:
            last_audit_date = summary.get("last_audit_date")

        proj_col1, proj_col2, proj_col3 = st.columns(3)
        with proj_col1:
            st.markdown(f"**Company**  \n{config.COMPANY_NAME}")
            st.markdown(f"**Industry**  \n{config.INDUSTRY}")
        with proj_col2:
            st.markdown(f"**Country**  \n{config.COUNTRY}")
            st.markdown(f"**Question Library**  \n{config.QUESTION_LIBRARY}")
        with proj_col3:
            st.markdown(f"**Last Audit Date**  \n{last_audit_date or 'No audits recorded yet'}")

    st.subheader("Audit overview")

    if audit_results.empty:
        st.warning(
            "No audit results were found. Check that "
            "`audits/boots-uk-health-beauty/audit_results.csv` exists."
        )
    elif summary is not None and "error" in summary:
        st.error(f"Could not read audit results: {summary['error']}")
    else:
        rate = summary["brand_citation_rate"]
        rate_display = f"{rate:.1f}%" if rate is not None else "N/A"

        metric_1, metric_2, metric_3, metric_4 = st.columns(4)

        metric_1.metric("Total AI Responses Analysed", summary["total_rows"])
        metric_2.metric(
            "Brand Citations",
            summary["brand_mentions"],
            help=f"Brand citation rate: {rate_display} of rows with a recorded brand_cited value",
        )
        metric_3.metric("Responses Citing Competitors", summary["rows_with_competitors"])
        metric_4.metric("Responses Citing Sources", summary["rows_with_sources"])

        st.divider()

        st.subheader("Audit data preview")
        st.dataframe(
            audit_results,
            use_container_width=True,
            hide_index=True,
        )


with audit_tab:
    st.subheader("Structured audit evidence")

    if audit_results.empty:
        st.info("Audit evidence is not currently available.")
    else:
        available_columns = audit_results.columns.tolist()

        selected_columns = st.multiselect(
            "Choose the fields to display",
            options=available_columns,
            default=available_columns[: min(8, len(available_columns))],
        )

        if selected_columns:
            st.dataframe(
                audit_results[selected_columns],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Select at least one field to display.")


with reports_tab:
    st.subheader("Generated reports")

    if not REPORT_DIRECTORY.exists():
        st.warning(f"Report directory not found: `{REPORT_DIRECTORY}`")
    else:
        report_files = list_report_files(REPORT_DIRECTORY)

        if not report_files:
            st.info("No Markdown reports were found.")
        else:
            selected_report = st.selectbox(
                "Select a report",
                options=report_files,
                format_func=report_display_title,
            )

            report_content = read_markdown_report(selected_report)

            st.markdown(report_content)

            st.download_button(
                label="Download report",
                data=report_content,
                file_name=selected_report.name,
                mime="text/markdown",
            )


with about_tab:
    st.subheader("How SignalScope AI works")

    st.markdown(
        """
### Four-engine workflow

1. **Audit Engine** — collects structured evidence from AI responses.
2. **Insights Engine** — identifies patterns and strategic findings.
3. **Recommendation Engine** — converts findings into prioritised actions.
4. **Measurement Engine** — compares audit evidence over time.

### Engineering approach

Objective calculations are handled with deterministic Python logic.
AI is used only where interpretation and reasoning add genuine value.

The platform follows one central principle:

> **Evidence before interpretation.**
"""
    )