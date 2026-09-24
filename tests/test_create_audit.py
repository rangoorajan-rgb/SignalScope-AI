"""Tests for src/create_audit.py.

Checkpoint A: pure validation and in-memory question generation.
Checkpoint B: staged on-disk workspace creation, rollback, collision
refusal, dry run, the CLI, and immediate --audit usability.

Every workspace is created under a temporary project root - never under
the real audits/ or reports/ folders, which (with the master template)
are verified byte-for-byte unchanged after every test. The Gemini SDK is
blocked throughout.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import audit_runner  # noqa: E402
import create_audit  # noqa: E402
import report_generator  # noqa: E402
import run_batch_audit  # noqa: E402
from audit_runner import load_questions  # noqa: E402
from dashboard_data import load_dashboard_rows  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, WriteAuditResultError, load_existing_results  # noqa: E402
from audit_config import (  # noqa: E402
    AuditConfig,
    AuditConfigError,
    default_audit_config,
    load_audit_config,
    validate_audit_config_data,
)
from create_audit import (  # noqa: E402
    DEFAULT_TEMPLATE_PATH,
    SUPPORTED_PLACEHOLDERS,
    TEMPLATE_COLUMNS,
    CreateAuditError,
    generate_questions,
    load_question_template,
    placeholder_values,
    prepare_buyer_questions,
    serialise_questions_csv,
    substitute_placeholders,
    validate_creation_data,
)
from geo_findings_analyzer import ALL_BUYER_JOURNEY_STAGES  # noqa: E402

BOOTS_QUESTIONS_FILE = REPO_ROOT / "audits" / "boots-uk-health-beauty" / "buyer_questions.csv"

BOOTS_LEAK_MARKERS = [
    "Boots", "Superdrug", "Amazon", "Holland & Barrett", "United Kingdom", "Health & Beauty",
    "boots-uk-health-beauty", "UK Retail GEO Library",
]


def fictional_data(**overrides) -> dict:
    """A fictional client exercising &, apostrophes, accents, a comma and
    double quotes."""
    data = {
        "slug": "lumiere-veloria-tea",
        "brand": "Lumière",
        "company_name": "Lumière & Fils Ltd",
        "report_subject": "Lumière & Fils Specialty Tea",
        "market": "Republic of Veloria",
        "category": 'Tea, Infusions & "Tisanes"',
        "competitors": ["Brewvale", "O'Kettle & Co", "Steepwisé"],
        "question_library": "Veloria Tea GEO Library",
    }
    data.update(overrides)
    return data


def boots_data() -> dict:
    config = default_audit_config()
    data = dataclasses.asdict(config)
    data["competitors"] = list(config.competitors)
    return data


def read_csv_rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


class _NoGeminiTestCase(unittest.TestCase):
    """Blocks the Gemini SDK and verifies the committed master template,
    audits and reports are byte-for-byte unchanged after each test."""

    def setUp(self) -> None:
        guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini call attempted"))
        guard.start()
        self.addCleanup(guard.stop)

        protected = [DEFAULT_TEMPLATE_PATH, *sorted((REPO_ROOT / "audits").rglob("*")),
                     *sorted((REPO_ROOT / "reports").rglob("*"))]
        snapshot = {p: (p.read_bytes() if p.is_file() else None) for p in protected}

        def check() -> None:
            current = [DEFAULT_TEMPLATE_PATH, *sorted((REPO_ROOT / "audits").rglob("*")),
                       *sorted((REPO_ROOT / "reports").rglob("*"))]
            self.assertEqual(sorted(current), sorted(snapshot), "files were added to or removed from audits/reports")
            for path, before in snapshot.items():
                if before is not None:
                    self.assertEqual(path.read_bytes(), before, f"Protected file was modified: {path}")

        self.addCleanup(check)


# --------------------------------------------------------------------------
# Part 1 - public audit config validation
# --------------------------------------------------------------------------


class ValidateAuditConfigDataTests(_NoGeminiTestCase):
    def test_boots_data_validates_to_the_loaded_config(self) -> None:
        config = validate_audit_config_data(boots_data())
        self.assertIsInstance(config, AuditConfig)
        self.assertEqual(config, load_audit_config("boots-uk-health-beauty"))

    def test_applies_existing_v21_rules(self) -> None:
        cases = {
            "not a dict": ["not", "a", "dict"],
            "missing field": {k: v for k, v in boots_data().items() if k != "market"},
            "unexpected field": {**boots_data(), "api_key": "x"},
            "empty string": {**boots_data(), "brand": "   "},
            "wrong type": {**boots_data(), "category": 7},
            "empty competitors": {**boots_data(), "competitors": []},
            "duplicate competitors": {**boots_data(), "competitors": ["A", "a"]},
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(AuditConfigError):
                    validate_audit_config_data(data)

    def test_applies_slug_format(self) -> None:
        for slug in ["Boots", "../escape", "a--b", "-a", "a b", ""]:
            with self.subTest(slug=slug):
                with self.assertRaises(AuditConfigError):
                    validate_audit_config_data({**boots_data(), "slug": slug})

    def test_does_not_require_three_competitors(self) -> None:
        # The exactly-three rule is creation-only; v2.1 validation is unchanged.
        config = validate_audit_config_data({**boots_data(), "competitors": ["Only One"]})
        self.assertEqual(config.competitors, ("Only One",))

    def test_source_named_in_errors(self) -> None:
        with self.assertRaises(AuditConfigError) as ctx:
            validate_audit_config_data({**boots_data(), "brand": ""}, source="operator input")
        self.assertIn("operator input", str(ctx.exception))


# --------------------------------------------------------------------------
# Part 6 - Boots recreation
# --------------------------------------------------------------------------


class BootsRecreationTests(_NoGeminiTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config, cls.rows, cls.text = prepare_buyer_questions(boots_data())
        cls.committed_bytes = BOOTS_QUESTIONS_FILE.read_bytes()
        cls.committed_rows = read_csv_rows(cls.committed_bytes.decode("utf-8"))

    def test_boots_config_passes_creation_rules(self) -> None:
        self.assertEqual(self.config, default_audit_config())

    def test_forty_rows_same_ids_stages_and_order(self) -> None:
        self.assertEqual(len(self.rows), 40)
        self.assertEqual([r["question_id"] for r in self.rows], [r["question_id"] for r in self.committed_rows])
        self.assertEqual(
            [r["buyer_journey_stage"] for r in self.rows], [r["buyer_journey_stage"] for r in self.committed_rows]
        )

    def test_every_parsed_field_matches_committed_file(self) -> None:
        self.assertEqual(self.rows, self.committed_rows)
        self.assertEqual(read_csv_rows(self.text), self.committed_rows)

    def test_csv_bytes_match_committed_file(self) -> None:
        # The committed file is stored with LF; a checkout may convert it to CRLF.
        self.assertEqual(self.text.encode("utf-8"), self.committed_bytes.replace(b"\r\n", b"\n"))

    def test_serialisation_format(self) -> None:
        data = self.text.encode("utf-8")
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.endswith(b"\n"))
        self.assertFalse(data.endswith(b"\n\n"))

    def test_serialiser_also_reproduces_master_template(self) -> None:
        template_rows = load_question_template()
        self.assertEqual(
            serialise_questions_csv(template_rows).encode("utf-8"),
            DEFAULT_TEMPLATE_PATH.read_bytes().replace(b"\r\n", b"\n"),
        )


# --------------------------------------------------------------------------
# Part 7 - fictional client
# --------------------------------------------------------------------------


class FictionalClientTests(_NoGeminiTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = load_question_template()
        cls.config, cls.rows, cls.text = prepare_buyer_questions(fictional_data())

    def all_text(self) -> str:
        return "\n".join(value for row in self.rows for value in row.values())

    def test_all_eight_values_validate(self) -> None:
        expected = fictional_data()
        for field in ["slug", "brand", "company_name", "report_subject", "market", "category", "question_library"]:
            self.assertEqual(getattr(self.config, field), expected[field])

    def test_three_competitors_retained_in_order(self) -> None:
        self.assertEqual(self.config.competitors, ("Brewvale", "O'Kettle & Co", "Steepwisé"))

    def test_forty_questions_with_ids_stages_and_order_unchanged(self) -> None:
        self.assertEqual(len(self.rows), 40)
        self.assertEqual([r["question_id"] for r in self.rows], [r["question_id"] for r in self.template])
        self.assertEqual(
            [r["buyer_journey_stage"] for r in self.rows], [r["buyer_journey_stage"] for r in self.template]
        )
        self.assertEqual([list(r) for r in self.rows], [TEMPLATE_COLUMNS] * 40)

    def test_template_uses_all_six_placeholders_and_each_is_substituted(self) -> None:
        template_text = "\n".join(value for row in self.template for value in row.values())
        for name in SUPPORTED_PLACEHOLDERS:
            self.assertIn(f"[{name}]", template_text)
        generated = self.all_text()
        for value in placeholder_values(self.config).values():
            self.assertIn(value, generated)

    def test_specific_substitutions(self) -> None:
        by_id = {r["question_id"]: r for r in self.rows}
        self.assertEqual(
            by_id["PA01"]["question"],
            'What are the most common challenges businesses in Republic of Veloria face when it comes to '
            'Tea, Infusions & "Tisanes"?',
        )
        self.assertEqual(by_id["VC03"]["question"], "Is Lumière better than Brewvale and O'Kettle & Co?")
        self.assertEqual(by_id["PD07"]["question"], "Is Lumière a safe long-term choice compared to Steepwisé?")

    def test_sd04_notes_substitution(self) -> None:
        self.assertIn("[BRAND]", {r["question_id"]: r for r in self.template}["SD04"]["notes"])
        notes = {r["question_id"]: r for r in self.rows}["SD04"]["notes"]
        self.assertIn("likely to surface Lumière and competitors", notes)

    def test_unbracketed_labels_unchanged(self) -> None:
        by_id = {r["question_id"]: r for r in self.rows}
        self.assertEqual(by_id["VC01"]["notes"], "Uses BRAND and COMPETITOR_1 together; foundational comparison question.")
        for source, row in zip(self.template, self.rows):
            for column in ("intent", "notes"):
                if "[" not in source[column]:
                    self.assertEqual(row[column], source[column])

    def test_no_boots_values_and_no_brackets(self) -> None:
        text = self.all_text() + self.text
        for marker in BOOTS_LEAK_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("[", text)
        self.assertNotIn("]", text)

    def test_csv_round_trip_is_exact(self) -> None:
        self.assertEqual(read_csv_rows(self.text), self.rows)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "buyer_questions.csv"
            path.write_bytes(self.text.encode("utf-8"))
            with path.open(newline="", encoding="utf-8-sig") as handle:
                self.assertEqual(list(csv.DictReader(handle)), self.rows)

    def test_generation_is_deterministic(self) -> None:
        _, rows, text = prepare_buyer_questions(fictional_data())
        self.assertEqual((rows, text), (self.rows, self.text))


class SinglePassSubstitutionTests(_NoGeminiTestCase):
    def test_value_resembling_a_token_is_not_substituted_again(self) -> None:
        values = {"BRAND": "[MARKET]", "MARKET": "Veloria"}
        self.assertEqual(substitute_placeholders("[BRAND] in [MARKET]", values), "[MARKET] in Veloria")

    def test_generation_refuses_a_bracketed_value_rather_than_resubstituting(self) -> None:
        # Bypasses creation validation (which already rejects brackets) to
        # prove the generator's own final check.
        config = AuditConfig(
            slug="x", brand="[MARKET]", company_name="X", report_subject="X", market="Veloria",
            category="Tea", competitors=("A", "B", "C"), question_library="L",
        )
        with self.assertRaises(CreateAuditError) as ctx:
            generate_questions(load_question_template(), config)
        self.assertIn("still contains a bracket", str(ctx.exception))

    def test_missing_value_fails(self) -> None:
        with self.assertRaises(CreateAuditError):
            substitute_placeholders("[BRAND]", {})

    def test_generation_requires_three_competitors(self) -> None:
        config = dataclasses.replace(default_audit_config(), competitors=("A", "B"))
        with self.assertRaises(CreateAuditError):
            generate_questions(load_question_template(), config)


# --------------------------------------------------------------------------
# Part 8 - invalid creation input
# --------------------------------------------------------------------------


class InvalidCreationInputTests(_NoGeminiTestCase):
    def assert_invalid(self, data: object, fragment: str | None = None) -> None:
        with self.assertRaises(CreateAuditError) as ctx:
            validate_creation_data(data)
        if fragment:
            self.assertIn(fragment, str(ctx.exception))
        with self.assertRaises(CreateAuditError):
            prepare_buyer_questions(data)

    def test_valid_fictional_data_passes(self) -> None:
        self.assertEqual(validate_creation_data(fictional_data()).brand, "Lumière")

    def test_competitor_counts_other_than_three(self) -> None:
        for competitors in ([], ["A"], ["A", "B"], ["A", "B", "C", "D"]):
            with self.subTest(count=len(competitors)):
                self.assert_invalid(fictional_data(competitors=competitors))

    def test_count_message(self) -> None:
        self.assert_invalid(fictional_data(competitors=["A", "B"]), "exactly 3 competitors")

    def test_duplicate_competitors_ignoring_case(self) -> None:
        self.assert_invalid(fictional_data(competitors=["Brewvale", "BREWVALE", "Steepwisé"]), "Duplicate")

    def test_brand_listed_as_competitor_ignoring_case(self) -> None:
        self.assert_invalid(fictional_data(competitors=["Brewvale", "LUMIÈRE", "Steepwisé"]), "must not also be listed")

    def test_blank_values(self) -> None:
        for field in ["slug", "brand", "company_name", "report_subject", "market", "category", "question_library"]:
            for blank in ["", "   "]:
                with self.subTest(field=field, value=blank):
                    self.assert_invalid(fictional_data(**{field: blank}))
        self.assert_invalid(fictional_data(competitors=["Brewvale", "", "Steepwisé"]))

    def test_leading_and_trailing_whitespace(self) -> None:
        for field in ["brand", "company_name", "report_subject", "market", "category", "question_library"]:
            for value in [" Lumière", "Lumière ", "\tLumière"]:
                with self.subTest(field=field, value=value):
                    self.assert_invalid(fictional_data(**{field: value}))
        self.assert_invalid(fictional_data(competitors=["Brewvale ", "Kettle", "Steepwisé"]), "whitespace")

    def test_newline_and_control_characters(self) -> None:
        for value in ["Lumi\nère", "Lumi\rère", "Lumi\x00ère", "Lumi\x1bère", "Lumi ère", "Lumi​ère"]:
            with self.subTest(value=value):
                self.assert_invalid(fictional_data(company_name=value), "control characters")
        self.assert_invalid(fictional_data(competitors=["Brew\nvale", "Kettle", "Steepwisé"]))

    def test_brackets_in_values(self) -> None:
        for field in ["brand", "company_name", "report_subject", "market", "category", "question_library"]:
            for value in ["[BRAND]", "Lumière [Tea]", "Tea]"]:
                with self.subTest(field=field, value=value):
                    self.assert_invalid(fictional_data(**{field: value}), "'[' or ']'")
        self.assert_invalid(fictional_data(competitors=["[COMPETITOR_2]", "Kettle", "Steepwisé"]))

    def test_malformed_slug(self) -> None:
        for slug in ["Lumiere", "lumière-tea", "lumiere_tea", "lumiere--tea", "-lumiere", "../lumiere", "a b"]:
            with self.subTest(slug=slug):
                self.assert_invalid(fictional_data(slug=slug), "Invalid audit slug")

    def test_schema_errors_become_create_audit_errors(self) -> None:
        self.assert_invalid(["not a mapping"])
        self.assert_invalid({k: v for k, v in fictional_data().items() if k != "report_subject"}, "missing field")
        self.assert_invalid({**fictional_data(), "extra": "x"}, "unexpected field")
        self.assert_invalid(fictional_data(competitors="Brewvale"))
        self.assert_invalid(fictional_data(brand=42))


# --------------------------------------------------------------------------
# Part 3/8 - template validation
# --------------------------------------------------------------------------

VALID_TEMPLATE_ROWS = [
    ["PA01", "Problem Awareness", "What do [MARKET] buyers want from [CATEGORY]?", "Intent.", "Notes."],
    ["VC01", "Vendor Comparison", "How does [BRAND] compare to [COMPETITOR_1]?", "Intent.", "Uses BRAND."],
]


class TemplateValidationTests(_NoGeminiTestCase):
    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "template.csv"

    def write(self, header: list[str] | None, rows: list[list[str]], raw: str | None = None) -> Path:
        if raw is not None:
            self.path.write_text(raw, encoding="utf-8")
            return self.path
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if header is not None:
                writer.writerow(header)
            writer.writerows(rows)
        return self.path

    def assert_template_invalid(self, fragment: str) -> None:
        with self.assertRaises(CreateAuditError) as ctx:
            load_question_template(self.path)
        self.assertIn(fragment, str(ctx.exception))
        with self.assertRaises(CreateAuditError):
            prepare_buyer_questions(fictional_data(), template_path=self.path)

    def test_master_template_is_valid(self) -> None:
        rows = load_question_template()
        self.assertEqual(len(rows), 40)
        self.assertEqual({r["buyer_journey_stage"] for r in rows}, set(ALL_BUYER_JOURNEY_STAGES))

    def test_valid_temporary_template(self) -> None:
        self.write(TEMPLATE_COLUMNS, VALID_TEMPLATE_ROWS)
        _, rows, _ = prepare_buyer_questions(fictional_data(), template_path=self.path)
        self.assertEqual(rows[1]["question"], "How does Lumière compare to Brewvale?")
        self.assertEqual(rows[1]["notes"], "Uses BRAND.")

    def test_missing_template_file(self) -> None:
        self.assert_template_invalid("not found")

    def test_missing_required_column(self) -> None:
        self.write(TEMPLATE_COLUMNS[:-1], [row[:-1] for row in VALID_TEMPLATE_ROWS])
        self.assert_template_invalid("columns must be exactly")

    def test_extra_column(self) -> None:
        self.write([*TEMPLATE_COLUMNS, "extra"], [[*row, "x"] for row in VALID_TEMPLATE_ROWS])
        self.assert_template_invalid("columns must be exactly")

    def test_reordered_columns(self) -> None:
        order = [1, 0, 2, 3, 4]
        self.write([TEMPLATE_COLUMNS[i] for i in order], [[row[i] for i in order] for row in VALID_TEMPLATE_ROWS])
        self.assert_template_invalid("columns must be exactly")

    def test_empty_file(self) -> None:
        self.write(None, [], raw="")
        self.assert_template_invalid("columns must be exactly")

    def test_header_only_template(self) -> None:
        self.write(TEMPLATE_COLUMNS, [])
        self.assert_template_invalid("no question rows")

    def test_row_with_too_few_or_too_many_fields(self) -> None:
        self.write(TEMPLATE_COLUMNS, [VALID_TEMPLATE_ROWS[0][:3]])
        self.assert_template_invalid("exactly 5 fields")
        self.write(TEMPLATE_COLUMNS, [[*VALID_TEMPLATE_ROWS[0], "surplus"]])
        self.assert_template_invalid("exactly 5 fields")

    def test_blank_question_id(self) -> None:
        self.write(TEMPLATE_COLUMNS, [["  ", *VALID_TEMPLATE_ROWS[0][1:]]])
        self.assert_template_invalid("blank question_id")

    def test_duplicate_question_id(self) -> None:
        self.write(TEMPLATE_COLUMNS, [VALID_TEMPLATE_ROWS[0], VALID_TEMPLATE_ROWS[0]])
        self.assert_template_invalid("duplicate question_id")

    def test_unsupported_stage(self) -> None:
        self.write(TEMPLATE_COLUMNS, [["PA01", "Awareness", "Q [BRAND]?", "I", "N"]])
        self.assert_template_invalid("unsupported buyer_journey_stage")

    def test_unknown_placeholder(self) -> None:
        for column_index, text in [(2, "Is [PRODUCT] good?"), (4, "Mentions [COMPETITOR_4].")]:
            with self.subTest(text=text):
                row = list(VALID_TEMPLATE_ROWS[0])
                row[column_index] = text
                self.write(TEMPLATE_COLUMNS, [row])
                self.assert_template_invalid("unsupported placeholder")

    def test_malformed_bracket_tokens(self) -> None:
        for text in ["Is [BRAND good?", "Is BRAND] good?", "Is [brand] good?", "Is [] good?", "Is [[BRAND]] good?",
                     "Is [BRAND ] good?"]:
            with self.subTest(text=text):
                self.write(TEMPLATE_COLUMNS, [["PA01", "Problem Awareness", text, "I", "N"]])
                self.assert_template_invalid("malformed placeholder")


class StaticSourceTests(unittest.TestCase):
    def test_module_contains_no_client_literals(self) -> None:
        source = Path(create_audit.__file__).read_text(encoding="utf-8")
        for marker in BOOTS_LEAK_MARKERS:
            self.assertNotIn(marker, source)

    def test_staging_prefix_can_never_be_a_valid_slug(self) -> None:
        with self.assertRaises(AuditConfigError):
            validate_audit_config_data({**boots_data(), "slug": f"{create_audit.STAGING_PREFIX}x"})


# ==========================================================================
# Checkpoint B - on-disk workspace creation
# ==========================================================================

OTHER_AUDIT_SLUG = "existing-other-audit"
FICTIONAL_SLUG = fictional_data()["slug"]
EXPECTED_WORKSPACE_FILES = ["audit_config.json", "audit_results.csv", "buyer_questions.csv"]


def tree_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


class _WorkspaceTestCase(_NoGeminiTestCase):
    """A temporary project root with audits/ and reports/ folders, holding
    one pre-existing audit that must never be touched."""

    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.audits = self.root / "audits"
        self.reports = self.root / "reports"
        (self.audits / OTHER_AUDIT_SLUG).mkdir(parents=True)
        (self.audits / OTHER_AUDIT_SLUG / "audit_config.json").write_text('{"keep": "me"}\n', encoding="utf-8")
        (self.reports / OTHER_AUDIT_SLUG).mkdir(parents=True)
        (self.reports / OTHER_AUDIT_SLUG / "audit_report.md").write_text("# kept\n", encoding="utf-8")
        self.baseline = tree_snapshot(self.root)

    def create(self, data: object | None = None, **kwargs) -> create_audit.CreatedAudit:
        return create_audit.create_audit_workspace(
            fictional_data() if data is None else data, audits_dir=self.audits, reports_dir=self.reports, **kwargs
        )

    def staging_dirs(self) -> list[str]:
        return [p.name for p in self.audits.iterdir() if p.name.startswith(".")]

    def assert_nothing_created(self) -> None:
        self.assertFalse((self.audits / FICTIONAL_SLUG).exists())
        self.assertFalse((self.reports / FICTIONAL_SLUG).exists())
        self.assertEqual(self.staging_dirs(), [])
        self.assertEqual(tree_snapshot(self.root), self.baseline)


class SuccessfulWorkspaceTests(_WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.result = self.create()
        self.audit_dir = self.audits / FICTIONAL_SLUG

    def test_exactly_three_files_and_nothing_else(self) -> None:
        self.assertEqual(sorted(p.name for p in self.audit_dir.iterdir()), EXPECTED_WORKSPACE_FILES)
        self.assertEqual(sorted(p.name for p in self.audits.iterdir()), sorted([OTHER_AUDIT_SLUG, FICTIONAL_SLUG]))
        self.assertEqual(self.staging_dirs(), [])
        self.assertFalse((self.reports / FICTIONAL_SLUG).exists())
        self.assertFalse(any(p.suffix == ".xlsx" for p in self.audit_dir.iterdir()))

    def test_other_audit_untouched(self) -> None:
        for relative, content in self.baseline.items():
            self.assertEqual(tree_snapshot(self.root)[relative], content)

    def test_result_object(self) -> None:
        self.assertFalse(self.result.dry_run)
        self.assertEqual(self.result.audit_dir, self.audit_dir)
        self.assertEqual(self.result.config_file, self.audit_dir / "audit_config.json")
        self.assertEqual(self.result.questions_file, self.audit_dir / "buyer_questions.csv")
        self.assertEqual(self.result.results_file, self.audit_dir / "audit_results.csv")
        self.assertEqual(self.result.question_count, 40)
        self.assertEqual(self.result.config, validate_creation_data(fictional_data()))

    def test_audit_config_json_exact(self) -> None:
        text = (self.audit_dir / "audit_config.json").read_bytes().decode("utf-8")
        expected = fictional_data()
        self.assertEqual(text, json.dumps(expected, indent=2, ensure_ascii=False) + "\n")
        self.assertEqual(list(json.loads(text)), list(expected))  # the 8 fields, in schema order
        self.assertIn("Lumière", text)  # UTF-8 kept, not \u-escaped
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(load_audit_config(FICTIONAL_SLUG, audits_dir=self.audits), self.result.config)

    def test_buyer_questions_file(self) -> None:
        _, expected_rows, expected_text = prepare_buyer_questions(fictional_data())
        data = (self.audit_dir / "buyer_questions.csv").read_bytes()
        self.assertEqual(data, expected_text.encode("utf-8"))
        rows = load_questions(str(self.audit_dir / "buyer_questions.csv"))
        self.assertEqual(rows, expected_rows)
        template = load_question_template()
        self.assertEqual([r["question_id"] for r in rows], [r["question_id"] for r in template])
        self.assertEqual([r["buyer_journey_stage"] for r in rows], [r["buyer_journey_stage"] for r in template])
        self.assertNotIn(b"[", data)
        self.assertNotIn(b"]", data)

    def test_results_file_header_only(self) -> None:
        path = self.audit_dir / "audit_results.csv"
        self.assertEqual(load_existing_results(str(path)), [])
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, [",".join(RESULTS_SCHEMA)])
        self.assertEqual(load_dashboard_rows(path), [])


class CollisionProtectionTests(_WorkspaceTestCase):
    def test_existing_audit_folder_refused_and_unchanged(self) -> None:
        (self.audits / FICTIONAL_SLUG).mkdir()
        (self.audits / FICTIONAL_SLUG / "notes.txt").write_text("pre-existing\n", encoding="utf-8")
        before = tree_snapshot(self.root)
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with self.assertRaises(CreateAuditError) as ctx:
                    self.create(dry_run=dry_run)
                self.assertIn("already exists", str(ctx.exception))
                self.assertEqual(tree_snapshot(self.root), before)
                self.assertEqual(self.staging_dirs(), [])

    def test_existing_report_folder_refused_and_unchanged(self) -> None:
        (self.reports / FICTIONAL_SLUG).mkdir()
        (self.reports / FICTIONAL_SLUG / "audit_report.md").write_text("# old report\n", encoding="utf-8")
        before = tree_snapshot(self.root)
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with self.assertRaises(CreateAuditError) as ctx:
                    self.create(dry_run=dry_run)
                self.assertIn("report folder", str(ctx.exception))
                self.assertEqual(tree_snapshot(self.root), before)
                self.assertFalse((self.audits / FICTIONAL_SLUG).exists())
                self.assertEqual(self.staging_dirs(), [])

    def test_boots_slug_refused_against_real_project_folders(self) -> None:
        # Uses the real audits/ and reports/ defaults; the base class
        # verifies every committed Boots file is unchanged afterwards.
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with self.assertRaises(CreateAuditError) as ctx:
                    create_audit.create_audit_workspace(boots_data(), dry_run=dry_run)
                self.assertIn("already exists", str(ctx.exception))
        self.assertEqual([p.name for p in (REPO_ROOT / "audits").iterdir()], ["boots-uk-health-beauty"])

    def test_target_appearing_during_creation_is_not_overwritten(self) -> None:
        def race(staging_root, config, rows) -> None:
            (self.audits / FICTIONAL_SLUG).mkdir()
            (self.audits / FICTIONAL_SLUG / "racer.txt").write_text("created concurrently\n", encoding="utf-8")

        with patch("create_audit._verify_staged_workspace", side_effect=race):
            with self.assertRaises(CreateAuditError) as ctx:
                self.create()
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual(sorted(p.name for p in (self.audits / FICTIONAL_SLUG).iterdir()), ["racer.txt"])
        self.assertEqual(self.staging_dirs(), [])


class RollbackTests(_WorkspaceTestCase):
    def assert_rolled_back(self, exc_type: type[BaseException], fragment: str, *patchers) -> None:
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        with self.assertRaises(exc_type) as ctx:
            self.create()
        self.assertIn(fragment, str(ctx.exception))
        for p in patchers:
            p.stop()
        self.assert_nothing_created()

    def failing_write_on(self, filename: str):
        real_write = create_audit._write_new_text

        def write(path: Path, text: str) -> None:
            if path.name == filename:
                raise OSError(f"simulated failure writing {filename}")
            real_write(path, text)

        return write

    def test_failure_writing_audit_config(self) -> None:
        self.assert_rolled_back(
            OSError, "writing audit_config.json",
            patch("create_audit._write_new_text", side_effect=self.failing_write_on("audit_config.json")),
        )

    def test_failure_writing_buyer_questions(self) -> None:
        self.assert_rolled_back(
            OSError, "writing buyer_questions.csv",
            patch("create_audit._write_new_text", side_effect=self.failing_write_on("buyer_questions.csv")),
        )

    def test_failure_writing_results_file(self) -> None:
        self.assert_rolled_back(
            OSError, "disk full", patch("create_audit.write_results_atomically", side_effect=OSError("disk full"))
        )

    def test_staged_validation_mismatch(self) -> None:
        self.assert_rolled_back(
            CreateAuditError, "does not reload to the generated questions",
            patch("create_audit.load_questions", return_value=[]),
        )

    def test_staged_validation_loader_error(self) -> None:
        self.assert_rolled_back(
            CreateAuditError, "failed validation",
            patch("create_audit.load_existing_results", side_effect=WriteAuditResultError("bad schema")),
        )

    def test_failure_at_final_rename(self) -> None:
        self.assert_rolled_back(OSError, "rename failed", patch("create_audit._publish", side_effect=OSError("rename failed")))

    def test_interrupt_at_final_rename(self) -> None:
        self.assert_rolled_back(KeyboardInterrupt, "", patch("create_audit._publish", side_effect=KeyboardInterrupt()))

    def test_invalid_input_and_template_create_nothing(self) -> None:
        with self.assertRaises(CreateAuditError):
            self.create(fictional_data(competitors=["A", "B"]))
        self.assert_nothing_created()
        bad_template = self.root / "bad_template.csv"
        bad_template.write_text("question_id,buyer_journey_stage,question,intent,notes\n", encoding="utf-8")
        self.baseline = tree_snapshot(self.root)
        with self.assertRaises(CreateAuditError):
            self.create(template_path=bad_template)
        self.assert_nothing_created()


class DryRunTests(_WorkspaceTestCase):
    def test_valid_dry_run_writes_nothing(self) -> None:
        result = self.create(dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.config.slug, FICTIONAL_SLUG)
        self.assertEqual(result.audit_dir, self.audits / FICTIONAL_SLUG)
        self.assertEqual(result.question_count, 40)
        self.assert_nothing_created()

    def test_dry_run_refuses_invalid_input_and_template(self) -> None:
        with self.assertRaises(CreateAuditError):
            self.create(fictional_data(brand=" Lumière"), dry_run=True)
        bad_template = self.root / "bad_template.csv"
        bad_template.write_text(
            "question_id,buyer_journey_stage,question,intent,notes\nPA01,Problem Awareness,Is [PRODUCT] good?,I,N\n",
            encoding="utf-8",
        )
        self.baseline = tree_snapshot(self.root)
        with self.assertRaises(CreateAuditError):
            self.create(template_path=bad_template, dry_run=True)
        self.assert_nothing_created()

    def test_missing_audits_folder_refused(self) -> None:
        with self.assertRaises(CreateAuditError):
            create_audit.create_audit_workspace(
                fictional_data(), audits_dir=self.root / "missing", reports_dir=self.reports, dry_run=True
            )


class BootsOnDiskRecreationTests(_WorkspaceTestCase):
    def test_boots_workspace_recreated_in_temporary_root(self) -> None:
        self.create(boots_data())
        boots_dir = self.audits / "boots-uk-health-beauty"
        committed = REPO_ROOT / "audits" / "boots-uk-health-beauty"

        self.assertEqual(
            load_audit_config("boots-uk-health-beauty", audits_dir=self.audits), default_audit_config()
        )
        for name in ("audit_config.json", "buyer_questions.csv"):
            with self.subTest(file=name):
                self.assertEqual(
                    (boots_dir / name).read_bytes(), (committed / name).read_bytes().replace(b"\r\n", b"\n")
                )
        self.assertEqual(load_existing_results(str(boots_dir / "audit_results.csv")), [])


def cli_args(**overrides) -> list[str]:
    data = fictional_data(**overrides)
    args = [
        "--slug", data["slug"], "--brand", data["brand"], "--company-name", data["company_name"],
        "--report-subject", data["report_subject"], "--market", data["market"], "--category", data["category"],
        "--question-library", data["question_library"],
    ]
    for competitor in data["competitors"]:
        args += ["--competitor", competitor]
    return args


def run_cli(main_fn, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main_fn(argv)
    return code, out.getvalue(), err.getvalue()


class CliTests(_WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        for target, value in (("audit_config.AUDITS_DIR", self.audits), ("create_audit.REPORTS_DIR", self.reports)):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def test_success(self) -> None:
        code, out, err = run_cli(create_audit.main, cli_args())
        self.assertEqual(code, 0, err)
        self.assertIn(f"Created audit '{FICTIONAL_SLUG}' at {self.audits / FICTIONAL_SLUG}", out)
        self.assertIn("buyer_questions.csv (40 questions)", out)
        self.assertIn("audit_results.csv (header only)", out)
        self.assertIn(f"Next: python src/audit_runner.py --audit {FICTIONAL_SLUG}", out)
        config = load_audit_config(FICTIONAL_SLUG, audits_dir=self.audits)
        self.assertEqual(config.competitors, ("Brewvale", "O'Kettle & Co", "Steepwisé"))
        self.assertEqual(config.category, 'Tea, Infusions & "Tisanes"')

    def test_competitor_order_from_cli_is_kept(self) -> None:
        code, _, err = run_cli(create_audit.main, cli_args(competitors=["Zeta", "Alpha", "Mu"]))
        self.assertEqual(code, 0, err)
        self.assertEqual(load_audit_config(FICTIONAL_SLUG, audits_dir=self.audits).competitors, ("Zeta", "Alpha", "Mu"))

    def test_dry_run(self) -> None:
        code, out, err = run_cli(create_audit.main, [*cli_args(), "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("Dry run - nothing was written.", out)
        self.assertIn(f"Would create audit '{FICTIONAL_SLUG}'", out)
        self.assertIn("(40 questions)", out)
        self.assertNotIn("Next:", out)
        self.assert_nothing_created()

    def test_validation_error_is_clean(self) -> None:
        code, out, err = run_cli(create_audit.main, cli_args(competitors=["A", "B"]))
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("Error: "), err)
        self.assertIn("exactly 3 competitors", err)
        self.assertNotIn("Traceback", err)
        self.assert_nothing_created()

    def test_collision_error_is_clean(self) -> None:
        self.assertEqual(run_cli(create_audit.main, cli_args())[0], 0)
        code, _, err = run_cli(create_audit.main, cli_args())
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

    def test_filesystem_error_is_clean(self) -> None:
        with patch("create_audit._publish", side_effect=PermissionError("access denied")):
            code, _, err = run_cli(create_audit.main, cli_args())
        self.assertEqual(code, 1)
        self.assertEqual(err.strip(), "Error: access denied")
        self.assert_nothing_created()

    def test_missing_required_option_exits_with_usage_error(self) -> None:
        args = cli_args()
        index = args.index("--market")
        del args[index : index + 2]
        with redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                create_audit.main(args)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--market", err.getvalue())


class AuditFlagUsabilityTests(_WorkspaceTestCase):
    """A freshly created audit is immediately usable through the existing
    v2.1 --audit CLIs, run from the temporary project root."""

    def setUp(self) -> None:
        super().setUp()
        self.create()
        p = patch("audit_config.AUDITS_DIR", self.audits)
        p.start()
        self.addCleanup(p.stop)
        original_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, original_cwd)

    def test_loads_through_audit_config(self) -> None:
        self.assertEqual(load_audit_config(FICTIONAL_SLUG).brand, "Lumière")

    def test_audit_runner(self) -> None:
        code, out, err = run_cli(audit_runner.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        self.assertIn("Total questions loaded: 40", out)
        self.assertIn("Is Lumière better than Brewvale and O'Kettle & Co?", out)

    @patch("run_batch_audit.generate_response")
    def test_batch_audit_limit_zero_makes_no_api_call(self, mock_generate) -> None:
        code, out, err = run_cli(run_batch_audit.main, ["--audit", FICTIONAL_SLUG, "--limit", "0"])
        self.assertEqual(code, 0, err)
        self.assertIn("Total questions: 40", out)
        self.assertIn("Already completed (Gemini): 0", out)
        self.assertIn("Remaining: 40", out)
        mock_generate.assert_not_called()
        self.assertEqual(load_existing_results(f"audits/{FICTIONAL_SLUG}/audit_results.csv"), [])

    def test_report_generator_reports_no_data_yet(self) -> None:
        code, _, err = run_cli(report_generator.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 1)
        self.assertIn("no data rows", err)
        self.assertFalse((self.reports / FICTIONAL_SLUG).exists())


# ==========================================================================
# Checkpoint C - release governance
# ==========================================================================

GITIGNORE = REPO_ROOT / ".gitignore"
BOOTS_SLUG = "boots-uk-health-beauty"


class ReleaseGovernanceTests(unittest.TestCase):
    def test_streamlit_displays_version_2_2_0(self) -> None:
        source = (REPO_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"\*\*Version:\*\* (\d+\.\d+\.\d+)", source), ["2.2.0"])

    def test_gitignore_contains_client_data_rules_and_boots_whitelist(self) -> None:
        lines = [line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()]
        for rule in [
            "audits/*",
            f"!audits/{BOOTS_SLUG}/",
            f"!audits/{BOOTS_SLUG}/**",
            "reports/*",
            f"!reports/{BOOTS_SLUG}/",
            f"!reports/{BOOTS_SLUG}/**",
        ]:
            self.assertIn(rule, lines)
        # The top-level folders themselves are never ignored outright.
        for broad in ["audits", "audits/", "reports", "reports/", "/audits", "/reports"]:
            self.assertNotIn(broad, lines)

    @unittest.skipUnless(shutil.which("git") and (REPO_ROOT / ".git").exists(), "git repository not available")
    def test_git_applies_the_client_data_rules(self) -> None:
        # check-ignore evaluates path names only, so nothing is created.
        expected = {
            "audits/example-client/audit_config.json": True,
            "audits/example-client/buyer_questions.csv": True,
            "audits/example-client/audit_results.csv": True,
            "reports/example-client/audit_report.md": True,
            "audits/.creating-example-client-123/audit_config.json": True,
            f"audits/{BOOTS_SLUG}/audit_config.json": False,
            f"audits/{BOOTS_SLUG}/buyer_questions.csv": False,
            f"audits/{BOOTS_SLUG}/audit_results.csv": False,
            f"reports/{BOOTS_SLUG}/audit_report.md": False,
            "questions/buyer_questions_master.csv": False,
            "src/create_audit.py": False,
        }
        for path, ignored in expected.items():
            with self.subTest(path=path):
                completed = subprocess.run(
                    ["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True
                )
                self.assertEqual(completed.returncode, 0 if ignored else 1, completed.stderr)

    def test_create_audit_module_contains_no_client_literals(self) -> None:
        source = Path(create_audit.__file__).read_text(encoding="utf-8")
        for marker in [*BOOTS_LEAK_MARKERS, "Boots UK"]:
            self.assertNotIn(marker, source)


if __name__ == "__main__":
    unittest.main()
