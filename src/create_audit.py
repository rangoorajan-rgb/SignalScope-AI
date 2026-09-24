"""Audit creation for SignalScope AI (v2.2).

Creates a new, immediately usable audit workspace:

    audits/<slug>/audit_config.json
    audits/<slug>/buyer_questions.csv
    audits/<slug>/audit_results.csv   (header only)

from explicit operator-supplied company details. Everything is validated
and generated in memory first: the audit config (the v2.1 rules plus
stricter creation-time rules), the master buyer-question template, and
the deterministic placeholder substitution. The workspace is then written
to a temporary staging folder, checked with the existing production
loaders, and published with a single rename - so either the complete
audit exists or nothing does. An existing audit or report folder is never
overwritten.

Never calls Gemini or any other LLM: question generation is plain
placeholder substitution into the master template (see
docs/QUESTION_GENERATION_GUIDE.md).

    python src/create_audit.py --slug <slug> --brand ... --competitor ... [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import audit_config
from audit_config import (
    CONFIG_FILENAME,
    STRING_FIELDS,
    AuditConfig,
    AuditConfigError,
    load_audit_config,
    validate_audit_config_data,
)
from audit_runner import AuditRunnerError, load_questions
from geo_findings_analyzer import ALL_BUYER_JOURNEY_STAGES
from write_single_audit_result import (
    RESULTS_SCHEMA,
    WriteAuditResultError,
    load_existing_results,
    write_results_atomically,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = REPO_ROOT / "questions" / "buyer_questions_master.csv"
REPORTS_DIR = REPO_ROOT / "reports"

QUESTIONS_FILENAME = "buyer_questions.csv"
RESULTS_FILENAME = "audit_results.csv"

# Staging folders start with "." so they can never be a valid audit slug.
STAGING_PREFIX = ".creating-"

TEMPLATE_COLUMNS = ["question_id", "buyer_journey_stage", "question", "intent", "notes"]
# Always quoted when serialised, matching the existing buyer question files.
FREE_TEXT_COLUMNS = {"question", "intent", "notes"}

REQUIRED_COMPETITOR_COUNT = 3
SUPPORTED_PLACEHOLDERS = (
    "BRAND",
    "CATEGORY",
    "MARKET",
    "COMPETITOR_1",
    "COMPETITOR_2",
    "COMPETITOR_3",
)

# A bracketed upper-case token, e.g. [BRAND]. Unbracketed labels such as
# BRAND in the notes column are descriptive text and are never replaced.
_PLACEHOLDER_PATTERN = re.compile(r"\[([A-Z0-9_]+)\]")

# Unicode control, format, surrogate, private-use and unassigned
# characters, plus line and paragraph separators.
_FORBIDDEN_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


class CreateAuditError(Exception):
    """Raised when audit creation input or the question template is invalid."""


# --------------------------------------------------------------------------
# Creation input validation
# --------------------------------------------------------------------------


def _check_creation_value(field_name: str, value: str) -> None:
    if value != value.strip():
        raise CreateAuditError(f"{field_name} must not have leading or trailing whitespace: {value!r}")
    for char in value:
        if unicodedata.category(char) in _FORBIDDEN_CATEGORIES:
            raise CreateAuditError(
                f"{field_name} must not contain line breaks or control characters: {value!r}"
            )
    if "[" in value or "]" in value:
        raise CreateAuditError(f"{field_name} must not contain '[' or ']': {value!r}")


def validate_creation_data(data: object) -> AuditConfig:
    """Validate operator-supplied data for a new audit.

    Applies every v2.1 audit_config.json rule (via
    validate_audit_config_data: the 8 required fields, types, non-empty
    values, unique competitors, slug format), then the v2.2 creation-only
    rules: exactly three competitors, the brand not also listed as a
    competitor, and no surrounding whitespace, line breaks, control
    characters or square brackets in any value.

    Returns the validated AuditConfig. Raises CreateAuditError.
    """
    try:
        config = validate_audit_config_data(data, source="new audit data")
    except AuditConfigError as exc:
        raise CreateAuditError(str(exc)) from exc

    for field_name in STRING_FIELDS:
        _check_creation_value(field_name, getattr(config, field_name))
    for competitor in config.competitors:
        _check_creation_value("competitors entry", competitor)

    if len(config.competitors) != REQUIRED_COMPETITOR_COUNT:
        raise CreateAuditError(
            f"A new audit needs exactly {REQUIRED_COMPETITOR_COUNT} competitors "
            f"(the question template uses [COMPETITOR_1] to [COMPETITOR_{REQUIRED_COMPETITOR_COUNT}]); "
            f"got {len(config.competitors)}."
        )

    competitor_keys = {c.casefold() for c in config.competitors}
    if config.brand.casefold() in competitor_keys:
        raise CreateAuditError(f"The brand {config.brand!r} must not also be listed as a competitor.")

    return config


# --------------------------------------------------------------------------
# Question template validation
# --------------------------------------------------------------------------


def _check_placeholders(value: str, question_id: str, column: str) -> None:
    unknown = sorted(set(_PLACEHOLDER_PATTERN.findall(value)) - set(SUPPORTED_PLACEHOLDERS))
    if unknown:
        raise CreateAuditError(
            f"Question {question_id!r} {column} uses unsupported placeholder(s) {unknown}; "
            f"supported: {list(SUPPORTED_PLACEHOLDERS)}"
        )
    remainder = _PLACEHOLDER_PATTERN.sub("", value)
    if "[" in remainder or "]" in remainder:
        raise CreateAuditError(f"Question {question_id!r} {column} has a malformed placeholder: {value!r}")


def load_question_template(template_path: str | Path = DEFAULT_TEMPLATE_PATH) -> list[dict[str, str]]:
    """Load and validate a buyer question template. Read-only.

    The template must have exactly TEMPLATE_COLUMNS, in order, at least
    one row, a complete set of fields on every row, a unique non-empty
    question_id per row, a known buyer journey stage, and only
    well-formed SUPPORTED_PLACEHOLDERS.

    Returns the rows in file order. Raises CreateAuditError.
    """
    path = Path(template_path)
    if not path.is_file():
        raise CreateAuditError(f"Question template not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        if fieldnames != TEMPLATE_COLUMNS:
            raise CreateAuditError(
                f"Question template columns must be exactly {TEMPLATE_COLUMNS}; found {fieldnames}: {path}"
            )
        raw_rows = list(reader)

    if not raw_rows:
        raise CreateAuditError(f"Question template has no question rows: {path}")

    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for line_number, raw in enumerate(raw_rows, start=2):
        if None in raw or any(raw[column] is None for column in TEMPLATE_COLUMNS):
            raise CreateAuditError(
                f"Question template line {line_number} does not have exactly {len(TEMPLATE_COLUMNS)} fields: {path}"
            )
        question_id = raw["question_id"]
        if not question_id.strip():
            raise CreateAuditError(f"Question template line {line_number} has a blank question_id: {path}")
        if question_id in seen_ids:
            raise CreateAuditError(f"Question template has a duplicate question_id {question_id!r}: {path}")
        seen_ids.add(question_id)
        if raw["buyer_journey_stage"] not in ALL_BUYER_JOURNEY_STAGES:
            raise CreateAuditError(
                f"Question {question_id!r} has an unsupported buyer_journey_stage "
                f"{raw['buyer_journey_stage']!r}; expected one of {ALL_BUYER_JOURNEY_STAGES}"
            )
        for column in TEMPLATE_COLUMNS:
            _check_placeholders(raw[column], question_id, column)
        rows.append({column: raw[column] for column in TEMPLATE_COLUMNS})

    return rows


# --------------------------------------------------------------------------
# Question generation
# --------------------------------------------------------------------------


def placeholder_values(config: AuditConfig) -> dict[str, str]:
    """The value for each supported placeholder, from an audit config
    with exactly REQUIRED_COMPETITOR_COUNT competitors."""
    if len(config.competitors) != REQUIRED_COMPETITOR_COUNT:
        raise CreateAuditError(
            f"Question generation needs exactly {REQUIRED_COMPETITOR_COUNT} competitors; "
            f"got {len(config.competitors)}."
        )
    values = {"BRAND": config.brand, "CATEGORY": config.category, "MARKET": config.market}
    for index, competitor in enumerate(config.competitors, start=1):
        values[f"COMPETITOR_{index}"] = competitor
    return values


def substitute_placeholders(text: str, values: dict[str, str]) -> str:
    """Replace every bracketed placeholder in text in a single pass.

    Replacement values are inserted literally and never rescanned, so a
    value that itself looks like a placeholder is not substituted again.
    Raises CreateAuditError for a placeholder with no value.
    """

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise CreateAuditError(f"No value for placeholder [{name}]")
        return values[name]

    return _PLACEHOLDER_PATTERN.sub(replace, text)


def generate_questions(template_rows: list[dict[str, str]], config: AuditConfig) -> list[dict[str, str]]:
    """Generate an audit's buyer questions from validated template rows.

    Substitutes the supported placeholders in all five columns (the notes
    column can contain one too), leaving all other text, the row order,
    question IDs and stages unchanged. Checks the result keeps the
    template's row count, IDs and stages in order, and contains no square
    brackets. Pure and deterministic - writes nothing.
    """
    values = placeholder_values(config)
    generated = [
        {column: substitute_placeholders(row[column], values) for column in TEMPLATE_COLUMNS}
        for row in template_rows
    ]

    if len(generated) != len(template_rows):
        raise CreateAuditError("Generated question count does not match the template.")
    for source, row in zip(template_rows, generated):
        if (row["question_id"], row["buyer_journey_stage"]) != (
            source["question_id"],
            source["buyer_journey_stage"],
        ):
            raise CreateAuditError(f"Generated question {row['question_id']!r} does not match the template order.")
        for column in TEMPLATE_COLUMNS:
            if "[" in row[column] or "]" in row[column]:
                raise CreateAuditError(
                    f"Generated question {row['question_id']!r} {column} still contains a bracket: {row[column]!r}"
                )
    return generated


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def _format_cell(column: str, value: str) -> str:
    needs_quotes = column in FREE_TEXT_COLUMNS or any(char in value for char in ',"\r\n')
    if needs_quotes:
        return '"' + value.replace('"', '""') + '"'
    return value


def serialise_questions_csv(rows: list[dict[str, str]]) -> str:
    """Serialise question rows to buyer_questions.csv text: UTF-8-safe
    (no BOM), LF line endings, a trailing newline, the header and
    identifier columns quoted only where CSV requires it, and the
    free-text columns always quoted - the format of the existing question
    files. The output is parsed back to confirm it round-trips exactly.
    """
    lines = [",".join(TEMPLATE_COLUMNS)]
    for row in rows:
        if list(row) != TEMPLATE_COLUMNS:
            raise CreateAuditError(f"Question row columns must be exactly {TEMPLATE_COLUMNS}; found {list(row)}")
        lines.append(",".join(_format_cell(column, row[column]) for column in TEMPLATE_COLUMNS))
    text = "\n".join(lines) + "\n"

    parsed = list(csv.DictReader(io.StringIO(text, newline="")))
    if parsed != rows:
        raise CreateAuditError("Serialised question CSV does not round-trip to the same rows.")
    return text


def prepare_buyer_questions(
    data: object, template_path: str | Path = DEFAULT_TEMPLATE_PATH
) -> tuple[AuditConfig, list[dict[str, str]], str]:
    """Validate creation data and the template, then generate and
    serialise the audit's buyer questions - entirely in memory.

    Returns (config, question_rows, csv_text). Raises CreateAuditError.
    """
    config = validate_creation_data(data)
    template_rows = load_question_template(template_path)
    rows = generate_questions(template_rows, config)
    return config, rows, serialise_questions_csv(rows)


# --------------------------------------------------------------------------
# Workspace creation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CreatedAudit:
    """The audit workspace that was created (or, for a dry run, would be)."""

    config: AuditConfig
    audit_dir: Path
    config_file: Path
    questions_file: Path
    results_file: Path
    question_count: int
    dry_run: bool


def serialise_audit_config(config: AuditConfig) -> str:
    """audit_config.json text: exactly the 8 AuditConfig fields in schema
    order, competitors as an ordered list, indent=2, UTF-8 characters kept
    as-is, and a trailing newline."""
    data = dataclasses.asdict(config)
    data["competitors"] = list(config.competitors)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _check_no_collision(audit_dir: Path, report_dir: Path, slug: str) -> None:
    if audit_dir.exists():
        raise CreateAuditError(f"Audit {slug!r} already exists at {audit_dir}; refusing to overwrite it.")
    if report_dir.exists():
        raise CreateAuditError(
            f"A report folder for {slug!r} already exists at {report_dir}; refusing to create an audit "
            "that would reuse it."
        )


def _write_new_text(path: Path, text: str) -> None:
    # "x" refuses to overwrite; newline="" writes the text's LF endings as-is.
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _verify_staged_workspace(
    staging_root: Path, config: AuditConfig, rows: list[dict[str, str]]
) -> None:
    """Load the staged workspace with the existing production loaders and
    confirm it holds exactly what was generated."""
    staged = staging_root / config.slug
    try:
        loaded_config = load_audit_config(config.slug, audits_dir=staging_root)
        loaded_questions = load_questions(str(staged / QUESTIONS_FILENAME))
        loaded_results = load_existing_results(str(staged / RESULTS_FILENAME))
    except (AuditConfigError, AuditRunnerError, WriteAuditResultError) as exc:
        raise CreateAuditError(f"Staged audit workspace failed validation: {exc}") from exc

    if loaded_config != config:
        raise CreateAuditError("Staged audit_config.json does not reload to the intended config.")
    if loaded_questions != rows:
        raise CreateAuditError("Staged buyer_questions.csv does not reload to the generated questions.")
    if loaded_results != []:
        raise CreateAuditError("Staged audit_results.csv is not empty.")


def _publish(staged: Path, target: Path) -> None:
    # Same-filesystem rename (the staging folder is inside the audits
    # folder). Refuses to replace an existing target on Windows; the
    # caller re-checks for a collision immediately beforehand.
    os.rename(staged, target)


def create_audit_workspace(
    data: object,
    *,
    audits_dir: str | Path | None = None,
    reports_dir: str | Path | None = None,
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
    dry_run: bool = False,
) -> CreatedAudit:
    """Create audits/<slug>/ with audit_config.json, buyer_questions.csv
    and a header-only audit_results.csv.

    Order of operations, each a hard stop before the audit is visible:
      1. Validate the creation data, the template and the generated
         questions, entirely in memory.
      2. Refuse if audits/<slug>/ or reports/<slug>/ already exists.
      3. Dry run: return what would be created, having written nothing.
      4. Write all three files into a temporary staging folder inside the
         audits folder, and reload them with the production loaders.
      5. Re-check for a collision, then rename the staged audit into
         place.
    The staging folder is always removed, so a failure leaves no audit
    and no staging folder behind; the original error is re-raised.

    audits_dir and reports_dir default to the project's audits/ and
    reports/ folders. Raises CreateAuditError for invalid input, a
    collision or a failed staged check; OSError for filesystem failures.
    """
    audits_root = Path(audits_dir) if audits_dir is not None else audit_config.AUDITS_DIR
    reports_root = Path(reports_dir) if reports_dir is not None else REPORTS_DIR

    config, rows, questions_csv = prepare_buyer_questions(data, template_path)
    config_json = serialise_audit_config(config)
    if not RESULTS_SCHEMA:
        raise CreateAuditError("The audit results schema is not available.")

    target = audits_root / config.slug
    report_dir = reports_root / config.slug
    if not audits_root.is_dir():
        raise CreateAuditError(f"Audits folder not found: {audits_root}")
    _check_no_collision(target, report_dir, config.slug)

    result = CreatedAudit(
        config=config,
        audit_dir=target,
        config_file=target / CONFIG_FILENAME,
        questions_file=target / QUESTIONS_FILENAME,
        results_file=target / RESULTS_FILENAME,
        question_count=len(rows),
        dry_run=dry_run,
    )
    if dry_run:
        return result

    staging_root = Path(tempfile.mkdtemp(prefix=f"{STAGING_PREFIX}{config.slug}-", dir=audits_root))
    try:
        staged = staging_root / config.slug
        staged.mkdir()
        _write_new_text(staged / CONFIG_FILENAME, config_json)
        _write_new_text(staged / QUESTIONS_FILENAME, questions_csv)
        write_results_atomically(str(staged / RESULTS_FILENAME), [])
        _verify_staged_workspace(staging_root, config, rows)

        _check_no_collision(target, report_dir, config.slug)
        _publish(staged, target)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a new SignalScope AI audit workspace under audits/<slug>/."
    )
    parser.add_argument("--slug", required=True, help="Audit folder name: lowercase letters, digits and hyphens")
    parser.add_argument("--brand", required=True, help="Brand name the audit looks for in AI answers")
    parser.add_argument("--company-name", required=True, help="Company display name")
    parser.add_argument("--report-subject", required=True, help="Report title subject")
    parser.add_argument("--market", required=True, help="Market the audit covers")
    parser.add_argument("--category", required=True, help="Category the brand competes in")
    parser.add_argument(
        "--competitor",
        action="append",
        required=True,
        help=f"A named competitor; give exactly {REQUIRED_COMPETITOR_COUNT}, in order",
    )
    parser.add_argument("--question-library", required=True, help="Question library display name")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and show what would be created, writing nothing"
    )
    return parser.parse_args(argv)


def _display(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    data = {
        "slug": args.slug,
        "brand": args.brand,
        "company_name": args.company_name,
        "report_subject": args.report_subject,
        "market": args.market,
        "category": args.category,
        "competitors": args.competitor,
        "question_library": args.question_library,
    }

    try:
        result = create_audit_workspace(data, dry_run=args.dry_run)
    except (CreateAuditError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    slug = result.config.slug
    if result.dry_run:
        print("Dry run - nothing was written.")
        print(f"Would create audit {slug!r} at {_display(result.audit_dir)}/:")
    else:
        print(f"Created audit {slug!r} at {_display(result.audit_dir)}/:")
    print(f"  {CONFIG_FILENAME}")
    print(f"  {QUESTIONS_FILENAME} ({result.question_count} questions)")
    print(f"  {RESULTS_FILENAME} (header only)")
    if not result.dry_run:
        print(f"Next: python src/audit_runner.py --audit {slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
