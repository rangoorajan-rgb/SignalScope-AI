"""Project configuration for SignalScope AI.

Single source of truth for the presentation layer's company/audit-scope
display values (used by streamlit_app.py). To reuse this portfolio
project for a different company, edit the values below directly - there
is no editing interface.

This file does not affect the Audit, Insights, Recommendation, or
Measurement Engines. Those engines define their own audit-scope
constants independently (see BRAND/MARKET/CATEGORY in
src/report_generator.py and KNOWN_COMPETITORS in
src/run_structured_audit.py) and are not read from here, so that this
polish pass does not touch engine behaviour that is already tested and
working.
"""

COMPANY_NAME = "Boots UK"
INDUSTRY = "Health & Beauty Retail"
COUNTRY = "United Kingdom"
COMPETITORS = [
    "Superdrug",
    "Amazon",
    "Holland & Barrett",
]
QUESTION_LIBRARY = "UK Retail GEO Library"
