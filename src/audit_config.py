"""Audit configuration for SignalScope AI.

Loads one audit's client/scope values (brand, market, category,
competitors, report subject, question library name) from
audits/<slug>/audit_config.json into a frozen AuditConfig, and derives
that audit's standard project file paths from its slug.

The core engines and runners accept an optional AuditConfig and fall
back to default_audit_config() (the default demonstration audit) when
none is given. CLIs select an audit with --audit SLUG (see
parse_audit_arg). Stdlib only - no new dependency.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDITS_DIR = REPO_ROOT / "audits"
CONFIG_FILENAME = "audit_config.json"

DEFAULT_AUDIT_SLUG = "boots-uk-health-beauty"

# Lowercase letters/digits separated by single hyphens - also guarantees a
# slug can never escape the audits directory (no "/", "\" or "..").
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

STRING_FIELDS = (
    "slug",
    "brand",
    "company_name",
    "report_subject",
    "market",
    "category",
    "question_library",
)
REQUIRED_FIELDS = set(STRING_FIELDS) | {"competitors"}


class AuditConfigError(Exception):
    """Raised when an audit configuration cannot be found, parsed, or validated."""


@dataclass(frozen=True)
class AuditConfig:
    """One audit's client and scope values.

    brand is the name the Audit Engine looks for in AI answers ("Acme");
    company_name is the display name ("Acme Ltd"); report_subject is the
    report title suffix ("Acme Ltd Garden Supplies"). These are distinct
    on purpose and must not be derived from one another. competitors is a
    tuple so its order - which maps to [COMPETITOR_1], [COMPETITOR_2], ...
    in the question library - is preserved and cannot be mutated.
    """

    slug: str
    brand: str
    company_name: str
    report_subject: str
    market: str
    category: str
    competitors: tuple[str, ...]
    question_library: str

    # Derived project paths. Deliberately relative strings, matching the
    # format of the existing DEFAULT_* constants in src/.

    @property
    def questions_file(self) -> str:
        return f"audits/{self.slug}/buyer_questions.csv"

    @property
    def results_file(self) -> str:
        return f"audits/{self.slug}/audit_results.csv"

    @property
    def reports_dir(self) -> str:
        return f"reports/{self.slug}"

    @property
    def audit_report_file(self) -> str:
        return f"{self.reports_dir}/audit_report.md"

    @property
    def findings_report_file(self) -> str:
        return f"{self.reports_dir}/GEO_FINDINGS.md"

    @property
    def recommendations_report_file(self) -> str:
        return f"{self.reports_dir}/GEO_RECOMMENDATIONS.md"

    @property
    def progress_report_file(self) -> str:
        return f"{self.reports_dir}/GEO_PROGRESS.md"


def _validate(data: object, slug: str, config_path: Path) -> AuditConfig:
    if not isinstance(data, dict):
        raise AuditConfigError(f"Audit config must be a JSON object: {config_path}")

    actual_fields = set(data.keys())
    missing = REQUIRED_FIELDS - actual_fields
    if missing:
        raise AuditConfigError(f"Audit config is missing field(s) {sorted(missing)}: {config_path}")
    unexpected = actual_fields - REQUIRED_FIELDS
    if unexpected:
        raise AuditConfigError(f"Audit config has unexpected field(s) {sorted(unexpected)}: {config_path}")

    for field_name in STRING_FIELDS:
        value = data[field_name]
        if not isinstance(value, str) or not value.strip():
            raise AuditConfigError(
                f"Invalid {field_name} value in {config_path}: expected a non-empty string, got {value!r}"
            )

    competitors = data["competitors"]
    if not isinstance(competitors, list) or not competitors:
        raise AuditConfigError(
            f"Invalid competitors value in {config_path}: expected a non-empty list, got {competitors!r}"
        )
    seen: set[str] = set()
    for item in competitors:
        if not isinstance(item, str) or not item.strip():
            raise AuditConfigError(
                f"Invalid competitors entry in {config_path}: expected a non-empty string, got {item!r}"
            )
        key = item.strip().lower()
        if key in seen:
            raise AuditConfigError(f"Duplicate competitors entry in {config_path}: {item!r}")
        seen.add(key)

    if data["slug"] != slug:
        raise AuditConfigError(
            f"Audit config slug {data['slug']!r} does not match its audit folder {slug!r}: {config_path}"
        )

    return AuditConfig(
        slug=data["slug"],
        brand=data["brand"],
        company_name=data["company_name"],
        report_subject=data["report_subject"],
        market=data["market"],
        category=data["category"],
        competitors=tuple(competitors),
        question_library=data["question_library"],
    )


def load_audit_config(slug: str, *, audits_dir: str | Path | None = None) -> AuditConfig:
    """Load and validate audits/<slug>/audit_config.json.

    The audits directory is resolved from this file's location, never
    from the current working directory. audits_dir overrides it (used by
    tests to load fixtures from a temporary directory).

    Raises AuditConfigError for an invalid slug, an unknown audit, a
    missing config file, malformed JSON, or any missing/invalid field.
    """
    if not isinstance(slug, str) or not _SLUG_PATTERN.match(slug):
        raise AuditConfigError(
            f"Invalid audit slug {slug!r}: use lowercase letters, digits and single hyphens only."
        )

    base = Path(audits_dir) if audits_dir is not None else AUDITS_DIR
    audit_dir = base / slug
    if not audit_dir.is_dir():
        raise AuditConfigError(f"Unknown audit {slug!r}: no audit folder at {audit_dir}")

    config_path = audit_dir / CONFIG_FILENAME
    if not config_path.is_file():
        raise AuditConfigError(f"Audit config file not found for {slug!r}: {config_path}")

    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise AuditConfigError(f"Audit config is not valid JSON ({exc}): {config_path}") from exc

    return _validate(data, slug, config_path)


@functools.lru_cache(maxsize=1)
def default_audit_config() -> AuditConfig:
    """The default audit's config, loaded once and shared. Used by the
    engines when no AuditConfig is passed, and to derive their
    backwards-compatible module constants (BRAND, DEFAULT_*, ...)."""
    return load_audit_config(DEFAULT_AUDIT_SLUG)


AUDIT_FLAG = "--audit"


def parse_audit_arg(argv: list[str]) -> tuple[AuditConfig | None, list[str]]:
    """Extract an optional "--audit SLUG" (or "--audit=SLUG") from a CLI
    argument list, wherever it appears.

    Returns (audit_config, remaining_argv). audit_config is None when the
    flag is absent, so callers keep their existing default behaviour.
    Raises AuditConfigError if the flag has no value, is repeated, or
    names an audit that cannot be loaded.
    """
    remaining: list[str] = []
    slugs: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == AUDIT_FLAG:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise AuditConfigError(f"{AUDIT_FLAG} requires an audit slug, e.g. {AUDIT_FLAG} {DEFAULT_AUDIT_SLUG}")
            slugs.append(argv[index + 1])
            index += 2
            continue
        if arg.startswith(AUDIT_FLAG + "="):
            slugs.append(arg.partition("=")[2])
            index += 1
            continue
        remaining.append(arg)
        index += 1

    if len(slugs) > 1:
        raise AuditConfigError(f"{AUDIT_FLAG} may only be given once.")
    if not slugs:
        return None, remaining
    return load_audit_config(slugs[0]), remaining
