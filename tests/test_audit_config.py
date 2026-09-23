"""Tests for src/audit_config.py.

The real Boots config is only ever read. Every invalid-config case is
built in a temporary audits directory - no second client is created
under the real audits/ folder.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import audit_runner  # noqa: E402
import geo_findings_analyzer  # noqa: E402
import measurement_engine  # noqa: E402
import recommendation_engine  # noqa: E402
import report_generator  # noqa: E402
import run_batch_audit  # noqa: E402
import run_end_to_end_demo  # noqa: E402
import run_single_audit  # noqa: E402
import run_structured_audit  # noqa: E402
import write_single_audit_result  # noqa: E402
from audit_config import (  # noqa: E402
    AUDITS_DIR,
    DEFAULT_AUDIT_SLUG,
    AuditConfig,
    AuditConfigError,
    load_audit_config,
)

BOOTS_SLUG = "boots-uk-health-beauty"


def _load_root_config_module():
    """Load the repo-root config.py (dashboard metadata) without adding the
    repo root to sys.path."""
    spec = importlib.util.spec_from_file_location("_v20_dashboard_config", REPO_ROOT / "config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_payload(slug: str = "example-client", **overrides) -> dict:
    payload = {
        "slug": slug,
        "brand": "Example",
        "company_name": "Example Ltd",
        "report_subject": "Example Ltd Widgets",
        "market": "Exampleland",
        "category": "Widget Retail",
        "competitors": ["Competitor One", "Competitor Two"],
        "question_library": "Example GEO Library",
    }
    payload.update(overrides)
    return payload


class BootsConfigTests(unittest.TestCase):
    """The committed Boots config must reproduce the v2.0 hardcoded values exactly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_audit_config(BOOTS_SLUG)

    def test_default_slug_is_boots(self) -> None:
        self.assertEqual(DEFAULT_AUDIT_SLUG, "boots-uk-health-beauty")

    def test_loads_as_audit_config(self) -> None:
        self.assertIsInstance(self.config, AuditConfig)

    def test_exact_literal_values(self) -> None:
        self.assertEqual(self.config.slug, "boots-uk-health-beauty")
        self.assertEqual(self.config.brand, "Boots")
        self.assertEqual(self.config.company_name, "Boots UK")
        self.assertEqual(self.config.report_subject, "Boots UK Health & Beauty")
        self.assertEqual(self.config.market, "United Kingdom")
        self.assertEqual(self.config.category, "Health & Beauty Retail")
        self.assertEqual(self.config.question_library, "UK Retail GEO Library")

    def test_competitor_order_preserved(self) -> None:
        self.assertEqual(self.config.competitors, ("Superdrug", "Amazon", "Holland & Barrett"))

    def test_brand_is_not_company_name(self) -> None:
        # "Boots" is the string matched in AI answers; "Boots UK" is display only.
        self.assertNotEqual(self.config.brand, self.config.company_name)

    def test_matches_engine_constants(self) -> None:
        self.assertEqual(self.config.brand, report_generator.BRAND)
        self.assertEqual(self.config.market, report_generator.MARKET)
        self.assertEqual(self.config.category, report_generator.CATEGORY)
        self.assertEqual(self.config.brand, run_structured_audit.BRAND)
        self.assertEqual(list(self.config.competitors), run_structured_audit.KNOWN_COMPETITORS)

    def test_matches_dashboard_config(self) -> None:
        dashboard_config = _load_root_config_module()
        self.assertEqual(self.config.company_name, dashboard_config.COMPANY_NAME)
        self.assertEqual(self.config.category, dashboard_config.INDUSTRY)
        self.assertEqual(self.config.market, dashboard_config.COUNTRY)
        self.assertEqual(list(self.config.competitors), dashboard_config.COMPETITORS)
        self.assertEqual(self.config.question_library, dashboard_config.QUESTION_LIBRARY)

    def test_report_subject_matches_committed_report_titles(self) -> None:
        reports_dir = REPO_ROOT / "reports" / BOOTS_SLUG
        for name in ["audit_report.md", "GEO_FINDINGS.md", "GEO_RECOMMENDATIONS.md", "GEO_PROGRESS.md"]:
            first_line = (reports_dir / name).read_text(encoding="utf-8").splitlines()[0]
            self.assertTrue(
                first_line.endswith(f" — {self.config.report_subject}"),
                f"{name} title {first_line!r} does not end with the report_subject",
            )

    def test_is_immutable(self) -> None:
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.config.brand = "Other"  # type: ignore[misc]


class DerivedPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_audit_config(BOOTS_SLUG)

    def test_exact_literal_paths(self) -> None:
        self.assertEqual(self.config.questions_file, "audits/boots-uk-health-beauty/buyer_questions.csv")
        self.assertEqual(self.config.results_file, "audits/boots-uk-health-beauty/audit_results.csv")
        self.assertEqual(self.config.reports_dir, "reports/boots-uk-health-beauty")
        self.assertEqual(self.config.audit_report_file, "reports/boots-uk-health-beauty/audit_report.md")
        self.assertEqual(self.config.findings_report_file, "reports/boots-uk-health-beauty/GEO_FINDINGS.md")
        self.assertEqual(
            self.config.recommendations_report_file, "reports/boots-uk-health-beauty/GEO_RECOMMENDATIONS.md"
        )
        self.assertEqual(self.config.progress_report_file, "reports/boots-uk-health-beauty/GEO_PROGRESS.md")

    def test_paths_are_relative_strings(self) -> None:
        for path in [
            self.config.questions_file,
            self.config.results_file,
            self.config.audit_report_file,
            self.config.findings_report_file,
            self.config.recommendations_report_file,
            self.config.progress_report_file,
        ]:
            self.assertIsInstance(path, str)
            self.assertFalse(Path(path).is_absolute(), path)
            self.assertNotIn("\\", path)

    def test_paths_match_existing_module_defaults(self) -> None:
        c = self.config
        self.assertEqual(c.questions_file, audit_runner.DEFAULT_QUESTION_FILE)
        self.assertEqual(c.questions_file, run_single_audit.DEFAULT_QUESTION_FILE)
        self.assertEqual(c.questions_file, write_single_audit_result.DEFAULT_QUESTION_FILE)
        self.assertEqual(c.results_file, write_single_audit_result.DEFAULT_RESULTS_FILE)
        self.assertEqual(c.questions_file, run_batch_audit.DEFAULT_QUESTION_FILE)
        self.assertEqual(c.results_file, run_batch_audit.DEFAULT_RESULTS_FILE)
        self.assertEqual(c.questions_file, run_structured_audit.DEFAULT_QUESTION_FILE)
        self.assertEqual(c.results_file, run_structured_audit.DEFAULT_RESULTS_FILE)
        self.assertEqual(c.questions_file, run_end_to_end_demo.DEFAULT_QUESTION_FILE)
        self.assertEqual(c.results_file, run_end_to_end_demo.DEFAULT_RESULTS_FILE)
        self.assertEqual(c.audit_report_file, run_end_to_end_demo.DEFAULT_REPORT_FILE)
        self.assertEqual(c.questions_file, report_generator.DEFAULT_QUESTIONS_FILE)
        self.assertEqual(c.results_file, report_generator.DEFAULT_RESULTS_FILE)
        self.assertEqual(c.audit_report_file, report_generator.DEFAULT_REPORT_FILE)
        self.assertEqual(c.questions_file, geo_findings_analyzer.DEFAULT_QUESTIONS_FILE)
        self.assertEqual(c.results_file, geo_findings_analyzer.DEFAULT_RESULTS_FILE)
        self.assertEqual(c.findings_report_file, geo_findings_analyzer.DEFAULT_FINDINGS_REPORT_FILE)
        self.assertEqual(c.questions_file, recommendation_engine.DEFAULT_QUESTIONS_FILE)
        self.assertEqual(c.results_file, recommendation_engine.DEFAULT_RESULTS_FILE)
        self.assertEqual(
            c.recommendations_report_file, recommendation_engine.DEFAULT_RECOMMENDATIONS_REPORT_FILE
        )
        self.assertEqual(c.questions_file, measurement_engine.DEFAULT_QUESTIONS_FILE)
        self.assertEqual(c.progress_report_file, measurement_engine.DEFAULT_PROGRESS_REPORT_FILE)

    def test_derived_paths_exist_in_repo(self) -> None:
        self.assertTrue((REPO_ROOT / self.config.questions_file).is_file())
        self.assertTrue((REPO_ROOT / self.config.results_file).is_file())
        self.assertTrue((REPO_ROOT / self.config.reports_dir).is_dir())

    def test_paths_follow_slug(self) -> None:
        config = dataclasses.replace(self.config, slug="another-audit")
        self.assertEqual(config.questions_file, "audits/another-audit/buyer_questions.csv")
        self.assertEqual(config.progress_report_file, "reports/another-audit/GEO_PROGRESS.md")


class LoaderLocationTests(unittest.TestCase):
    def test_audits_dir_resolved_from_module_not_cwd(self) -> None:
        self.assertTrue(AUDITS_DIR.is_absolute())
        self.assertEqual(AUDITS_DIR, REPO_ROOT / "audits")

    def test_loads_regardless_of_cwd(self) -> None:
        import os

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                config = load_audit_config(BOOTS_SLUG)
            finally:
                os.chdir(original_cwd)
        self.assertEqual(config.brand, "Boots")


class InvalidConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.audits_dir = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def write_config(self, slug: str, payload: object, folder: str | None = None) -> None:
        audit_dir = self.audits_dir / (folder or slug)
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / "audit_config.json").write_text(json.dumps(payload), encoding="utf-8")

    def assert_config_error(self, slug: str, fragment: str) -> None:
        with self.assertRaises(AuditConfigError) as ctx:
            load_audit_config(slug, audits_dir=self.audits_dir)
        self.assertIn(fragment, str(ctx.exception))

    def test_valid_fixture_loads(self) -> None:
        self.write_config("example-client", valid_payload())
        config = load_audit_config("example-client", audits_dir=self.audits_dir)
        self.assertEqual(config.brand, "Example")
        self.assertEqual(config.competitors, ("Competitor One", "Competitor Two"))

    def test_unknown_slug_fails(self) -> None:
        self.assert_config_error("no-such-client", "Unknown audit")

    def test_unknown_slug_fails_against_real_audits_dir(self) -> None:
        with self.assertRaises(AuditConfigError):
            load_audit_config("no-such-client")

    def test_invalid_slug_format_fails(self) -> None:
        for bad in ["", "../boots-uk-health-beauty", "Boots", "a/b", "a--b", "-a", 123]:
            with self.subTest(slug=bad):
                with self.assertRaises(AuditConfigError):
                    load_audit_config(bad, audits_dir=self.audits_dir)  # type: ignore[arg-type]

    def test_missing_config_file_fails(self) -> None:
        (self.audits_dir / "example-client").mkdir()
        self.assert_config_error("example-client", "config file not found")

    def test_malformed_json_fails(self) -> None:
        audit_dir = self.audits_dir / "example-client"
        audit_dir.mkdir()
        (audit_dir / "audit_config.json").write_text('{"slug": "example-client",', encoding="utf-8")
        self.assert_config_error("example-client", "not valid JSON")

    def test_non_object_json_fails(self) -> None:
        self.write_config("example-client", ["not", "an", "object"])
        self.assert_config_error("example-client", "JSON object")

    def test_each_missing_required_field_fails(self) -> None:
        for field_name in valid_payload():
            with self.subTest(field=field_name):
                payload = valid_payload()
                del payload[field_name]
                self.write_config("example-client", payload)
                self.assert_config_error("example-client", "missing field")

    def test_unexpected_field_fails(self) -> None:
        self.write_config("example-client", valid_payload(api_key="secret"))
        self.assert_config_error("example-client", "unexpected field")

    def test_wrong_string_field_types_fail(self) -> None:
        for field_name in ["brand", "company_name", "report_subject", "market", "category", "question_library"]:
            for bad in [None, 123, True, ["Example"], {"name": "Example"}, "", "   "]:
                with self.subTest(field=field_name, value=bad):
                    self.write_config("example-client", valid_payload(**{field_name: bad}))
                    self.assert_config_error("example-client", f"Invalid {field_name}")

    def test_wrong_slug_type_fails(self) -> None:
        self.write_config("example-client", valid_payload(slug=123))
        self.assert_config_error("example-client", "Invalid slug")

    def test_competitors_wrong_type_fails(self) -> None:
        for bad in ["Competitor One", None, {"a": "b"}, 3]:
            with self.subTest(value=bad):
                self.write_config("example-client", valid_payload(competitors=bad))
                self.assert_config_error("example-client", "Invalid competitors")

    def test_empty_competitor_list_fails(self) -> None:
        self.write_config("example-client", valid_payload(competitors=[]))
        self.assert_config_error("example-client", "non-empty list")

    def test_invalid_competitor_values_fail(self) -> None:
        for bad in [["Competitor One", ""], ["   "], ["Competitor One", None], [123], [["nested"]]]:
            with self.subTest(value=bad):
                self.write_config("example-client", valid_payload(competitors=bad))
                self.assert_config_error("example-client", "Invalid competitors entry")

    def test_duplicate_competitors_fail(self) -> None:
        self.write_config("example-client", valid_payload(competitors=["Competitor One", "competitor one"]))
        self.assert_config_error("example-client", "Duplicate competitors entry")

    def test_slug_folder_mismatch_fails(self) -> None:
        self.write_config("example-client", valid_payload(slug="other-client"), folder="example-client")
        self.assert_config_error("example-client", "does not match its audit folder")

    def test_competitor_order_preserved_from_fixture(self) -> None:
        order = ["Zeta", "Alpha", "Mu"]
        self.write_config("example-client", valid_payload(competitors=order))
        config = load_audit_config("example-client", audits_dir=self.audits_dir)
        self.assertEqual(list(config.competitors), order)


class BootsConfigFileHygieneTests(unittest.TestCase):
    def test_config_file_contains_no_secret_like_keys(self) -> None:
        raw = (AUDITS_DIR / BOOTS_SLUG / "audit_config.json").read_text(encoding="utf-8").lower()
        for marker in ["api_key", "apikey", "secret", "token", "password", "gemini_api_key"]:
            self.assertNotIn(marker, raw)


if __name__ == "__main__":
    unittest.main()
