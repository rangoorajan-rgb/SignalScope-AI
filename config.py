"""Backwards-compatible project configuration for SignalScope AI.

Deprecated compatibility shim. Since v2.1, each audit's client/scope
values live in audits/<slug>/audit_config.json and are loaded through
src/audit_config.py. This module only re-exposes the default audit's
values under their v2.0 names, so existing imports of config keep
working. Nothing here should be edited per client - edit the audit's
audit_config.json instead.
"""

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from audit_config import default_audit_config  # noqa: E402

_DEFAULT_AUDIT_CONFIG = default_audit_config()

COMPANY_NAME = _DEFAULT_AUDIT_CONFIG.company_name
INDUSTRY = _DEFAULT_AUDIT_CONFIG.category
COUNTRY = _DEFAULT_AUDIT_CONFIG.market
COMPETITORS = list(_DEFAULT_AUDIT_CONFIG.competitors)
QUESTION_LIBRARY = _DEFAULT_AUDIT_CONFIG.question_library
