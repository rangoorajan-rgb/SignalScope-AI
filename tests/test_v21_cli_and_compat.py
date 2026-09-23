"""v2.1 Checkpoint C tests: --audit CLI selection, path-only runners,
legacy defaults, the root config.py shim, the Streamlit dashboard, and a
static guard against client literals in reusable code.

No second client is created under the real audits/ folder: fictional
audits live in a temporary workspace (audit_config.AUDITS_DIR is patched
to point at it, and the working directory is switched to it so the
config's relative paths resolve there). Gemini is mocked, and the Gemini
SDK client is blocked, throughout. Every test verifies afterwards that
the real Boots audit files and reports are unchanged.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    DEFAULT_AUDIT_SLUG,
    AuditConfigError,
    default_audit_config,
    load_audit_config,
    parse_audit_arg,
)
from write_single_audit_result import RESULTS_SCHEMA  # noqa: E402

BOOTS = default_audit_config()
FICTIONAL_SLUG = "lumora-veloria-tea"
FICTIONAL_CONFIG = {
    "slug": FICTIONAL_SLUG,
    "brand": "Lumora",
    "company_name": "Lumora Tea Co.",
    "report_subject": "Lumora Tea Co. Specialty Tea",
    "market": "Republic of Veloria",
    "category": "Specialty Tea Retail",
    "competitors": ["Brewvale", "Kettleworth", "Steepwise"],
    "question_library": "Veloria Tea GEO Library",
}

BOOTS_LEAK_MARKERS = [
    "Boots", "Superdrug", "Amazon", "Holland & Barrett", "United Kingdom", "Health & Beauty", DEFAULT_AUDIT_SLUG,
]

QUESTION_ROWS = [
    {"question_id": "PA01", "buyer_journey_stage": "Problem Awareness", "question": "Tea challenges?",
     "intent": "", "notes": ""},
    {"question_id": "PA04", "buyer_journey_stage": "Problem Awareness", "question": "Is tea worth it?",
     "intent": "", "notes": ""},
    {"question_id": "PA05", "buyer_journey_stage": "Problem Awareness", "question": "Ignore tea?",
     "intent": "", "notes": ""},
]

RESULT_ROWS = [
    {"run_date": "2026-07-18", "question_id": "SD01", "question": "Best tea?", "funnel_stage": "Solution Discovery",
     "engine": "Perplexity", "brand_cited": "Y", "brand_position": "1", "competitors_cited": "Brewvale",
     "sources_cited": "Leaf Journal", "sentiment": "Positive", "answer_snippet": "Lumora leads."},
]

ANALYSIS_RESULT = {
    "brand_cited": "Y", "brand_position": 1, "competitors_cited": ["Brewvale"],
    "sources_cited": ["Leaf Journal"], "sentiment": "Positive",
}

FULL_ROW = {name: "x" for name in RESULTS_SCHEMA}

CANNED_RECOMMENDATIONS = json.dumps([{
    "title": "Grow Lumora Citations", "problem_addressed": "Lumora is under-cited.",
    "recommendation_rationale": "Visibility gap.", "recommended_action": "Publish guides naming Lumora.",
    "potential_impact": "High", "indicative_effort": "Low", "success_metric": "Citation rate.",
    "source_findings": ["Overall AI Search Visibility"],
}])


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_main(main_fn, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main_fn(argv)
    return code, out.getvalue(), err.getvalue()


class _SafeTestCase(unittest.TestCase):
    """Blocks the Gemini SDK and verifies the real Boots files are untouched."""

    def setUp(self) -> None:
        guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini call attempted"))
        guard.start()
        self.addCleanup(guard.stop)
        boots_files = [
            *sorted((REPO_ROOT / "audits" / DEFAULT_AUDIT_SLUG).iterdir()),
            *sorted((REPO_ROOT / "reports" / DEFAULT_AUDIT_SLUG).iterdir()),
        ]
        snapshot = {p: p.read_bytes() for p in boots_files}

        def check() -> None:
            for path, before in snapshot.items():
                self.assertEqual(path.read_bytes(), before, f"Boots file was modified: {path}")

        self.addCleanup(check)

    def assert_no_boots_leak(self, text: str) -> None:
        for marker in BOOTS_LEAK_MARKERS:
            self.assertNotIn(marker, text)


class _FictionalWorkspaceTestCase(_SafeTestCase):
    """A temp workspace containing audits/lumora-veloria-tea/, selected via
    --audit, with the working directory switched into it."""

    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)
        audit_dir = self.workspace / "audits" / FICTIONAL_SLUG
        audit_dir.mkdir(parents=True)
        (audit_dir / "audit_config.json").write_text(json.dumps(FICTIONAL_CONFIG), encoding="utf-8")
        write_csv(audit_dir / "buyer_questions.csv", list(QUESTION_ROWS[0]), QUESTION_ROWS)
        write_csv(audit_dir / "audit_results.csv", RESULTS_SCHEMA, RESULT_ROWS)

        dir_patch = patch("audit_config.AUDITS_DIR", self.workspace / "audits")
        dir_patch.start()
        self.addCleanup(dir_patch.stop)

        original_cwd = os.getcwd()
        os.chdir(self.workspace)
        self.addCleanup(os.chdir, original_cwd)

        self.config = load_audit_config(FICTIONAL_SLUG)

    def read(self, relative: str) -> str:
        return (self.workspace / relative).read_text(encoding="utf-8")

    def results_rows(self) -> list[dict[str, str]]:
        with (self.workspace / self.config.results_file).open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))


# --------------------------------------------------------------------------
# 1. Legacy KNOWN_COMPETITORS behaviour
# --------------------------------------------------------------------------


class LegacyKnownCompetitorsTests(_SafeTestCase):
    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.questions = self.tmp / "q.csv"
        self.results = self.tmp / "r.csv"
        write_csv(self.questions, list(QUESTION_ROWS[0]), QUESTION_ROWS)
        write_csv(self.results, RESULTS_SCHEMA, [])
        self.fictional = load_audit_config(FICTIONAL_SLUG, audits_dir=self._fictional_audits_dir())

    def _fictional_audits_dir(self) -> Path:
        audit_dir = self.tmp / "audits" / FICTIONAL_SLUG
        audit_dir.mkdir(parents=True)
        (audit_dir / "audit_config.json").write_text(json.dumps(FICTIONAL_CONFIG), encoding="utf-8")
        return self.tmp / "audits"

    @patch("run_structured_audit.analyze_response", return_value=dict(ANALYSIS_RESULT))
    @patch("run_structured_audit.generate_response", return_value="Answer.")
    def test_structured_default_uses_module_level_list_object(self, _gen, mock_analyze) -> None:
        sentinel = ["Legacy Competitor"]
        with patch("run_structured_audit.KNOWN_COMPETITORS", sentinel):
            run_structured_audit.run_structured_audit(str(self.questions), str(self.results))
        self.assertIs(mock_analyze.call_args.args[2], sentinel)

    @patch("run_structured_audit.analyze_response", return_value=dict(ANALYSIS_RESULT))
    @patch("run_structured_audit.generate_response", return_value="Answer.")
    def test_structured_supplied_config_uses_config_competitors(self, _gen, mock_analyze) -> None:
        with patch("run_structured_audit.KNOWN_COMPETITORS", ["Legacy Competitor"]):
            run_structured_audit.run_structured_audit(
                str(self.questions), str(self.results), audit_config=self.fictional
            )
        self.assertEqual(mock_analyze.call_args.args[2], ["Brewvale", "Kettleworth", "Steepwise"])

    @patch("run_structured_audit.analyze_response", return_value=dict(ANALYSIS_RESULT))
    @patch("run_structured_audit.generate_response", return_value="Answer.")
    def test_structured_explicit_competitors_always_win(self, _gen, mock_analyze) -> None:
        explicit = ["Explicit One"]
        run_structured_audit.run_structured_audit(
            str(self.questions), str(self.results), known_competitors=explicit, audit_config=self.fictional
        )
        self.assertIs(mock_analyze.call_args.args[2], explicit)

    @patch("run_end_to_end_demo.analyze_response", return_value=dict(ANALYSIS_RESULT))
    @patch("run_end_to_end_demo.generate_response", return_value="Answer.")
    def test_demo_default_uses_module_level_list_object(self, _gen, mock_analyze) -> None:
        sentinel = ["Legacy Competitor"]
        with patch("run_end_to_end_demo.KNOWN_COMPETITORS", sentinel):
            run_end_to_end_demo.run_end_to_end_demo(
                str(self.questions), str(self.results), str(self.tmp / "report.md")
            )
        self.assertIs(mock_analyze.call_args.args[2], sentinel)

    def test_default_module_list_values_unchanged(self) -> None:
        self.assertEqual(run_structured_audit.KNOWN_COMPETITORS, ["Superdrug", "Amazon", "Holland & Barrett"])
        self.assertIs(run_end_to_end_demo.KNOWN_COMPETITORS, run_structured_audit.KNOWN_COMPETITORS)


# --------------------------------------------------------------------------
# 2. Root config.py shim
# --------------------------------------------------------------------------


class RootConfigShimTests(unittest.TestCase):
    def load_shim(self):
        spec = importlib.util.spec_from_file_location("_root_config_shim", REPO_ROOT / "config.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_exact_v20_values(self) -> None:
        shim = self.load_shim()
        self.assertEqual(shim.COMPANY_NAME, "Boots UK")
        self.assertEqual(shim.INDUSTRY, "Health & Beauty Retail")
        self.assertEqual(shim.COUNTRY, "United Kingdom")
        self.assertEqual(shim.COMPETITORS, ["Superdrug", "Amazon", "Holland & Barrett"])
        self.assertIsInstance(shim.COMPETITORS, list)
        self.assertEqual(shim.QUESTION_LIBRARY, "UK Retail GEO Library")

    def test_values_are_derived_not_duplicated(self) -> None:
        source = (REPO_ROOT / "config.py").read_text(encoding="utf-8")
        for literal in ["Boots", "Superdrug", "Health & Beauty", "United Kingdom", "UK Retail GEO Library"]:
            self.assertNotIn(literal, source)
        self.assertIn("default_audit_config()", source)


# --------------------------------------------------------------------------
# 3, 4, 6, 7. CLI --audit selection (workhorse functions mocked)
# --------------------------------------------------------------------------

# (module, main, workhorse name, return value, argv tail, expected default paths)
CLI_CASES = [
    ("report_generator", report_generator.main, "generate_report", "", [],
     (BOOTS.questions_file, BOOTS.results_file, BOOTS.audit_report_file)),
    ("geo_findings_analyzer", geo_findings_analyzer.main, "generate_geo_findings", ([], ""), [],
     (BOOTS.questions_file, BOOTS.results_file, BOOTS.findings_report_file)),
    ("recommendation_engine", recommendation_engine.main, "generate_geo_recommendations", ([], ""), [],
     (BOOTS.questions_file, BOOTS.results_file, BOOTS.recommendations_report_file)),
    ("measurement_engine", measurement_engine.main, "generate_geo_progress", (MagicMock(), ""), ["b.csv", "f.csv"],
     ("b.csv", "f.csv", BOOTS.questions_file, BOOTS.progress_report_file)),
    ("run_structured_audit", run_structured_audit.main, "run_structured_audit", FULL_ROW, [],
     (BOOTS.questions_file, BOOTS.results_file)),
    ("run_end_to_end_demo", run_end_to_end_demo.main, "run_end_to_end_demo", FULL_ROW, [],
     (BOOTS.questions_file, BOOTS.results_file, BOOTS.audit_report_file)),
    ("write_single_audit_result", write_single_audit_result.main, "write_single_audit_result", FULL_ROW, [],
     (BOOTS.questions_file, BOOTS.results_file)),
    ("run_single_audit", run_single_audit.main, "run_single_audit",
     ({"question_id": "PA01", "buyer_journey_stage": "Problem Awareness", "question": "Q?"}, "A."), [],
     (BOOTS.questions_file,)),
]


class CliAuditFlagTests(_SafeTestCase):
    def call(self, module_name, main_fn, workhorse, return_value, argv):
        with patch(f"{module_name}.{workhorse}", return_value=return_value) as mock_fn:
            code, out, err = run_main(main_fn, argv)
        return code, out, err, mock_fn

    def test_audit_omitted_gives_boots_defaults(self) -> None:
        for module_name, main_fn, workhorse, rv, tail, expected in CLI_CASES:
            with self.subTest(module=module_name):
                code, _, err, mock_fn = self.call(module_name, main_fn, workhorse, rv, list(tail))
                self.assertEqual(code, 0, err)
                self.assertEqual(mock_fn.call_args.args[: len(expected)], expected)
                self.assertIsNone(mock_fn.call_args.kwargs.get("audit_config"))

    def test_audit_boots_gives_identical_paths_and_default_config(self) -> None:
        for module_name, main_fn, workhorse, rv, tail, expected in CLI_CASES:
            with self.subTest(module=module_name):
                code, _, err, mock_fn = self.call(
                    module_name, main_fn, workhorse, rv, [*tail, "--audit", DEFAULT_AUDIT_SLUG]
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(mock_fn.call_args.args[: len(expected)], expected)
                self.assertEqual(mock_fn.call_args.kwargs["audit_config"], BOOTS)

    def test_unknown_slug_fails_clearly(self) -> None:
        for module_name, main_fn, workhorse, rv, tail, _ in CLI_CASES:
            with self.subTest(module=module_name):
                code, _, err, mock_fn = self.call(
                    module_name, main_fn, workhorse, rv, [*tail, "--audit", "no-such-client"]
                )
                self.assertEqual(code, 1)
                self.assertIn("Unknown audit 'no-such-client'", err)
                mock_fn.assert_not_called()

    def test_audit_flag_without_value_fails(self) -> None:
        code, _, err = run_main(report_generator.main, ["--audit"])
        self.assertEqual(code, 1)
        self.assertIn("--audit requires an audit slug", err)

    def test_audit_runner_defaults_and_unknown_slug(self) -> None:
        with patch("audit_runner.load_questions", return_value=[]) as mock_load:
            code, _, _ = run_main(audit_runner.main, [])
            self.assertEqual(code, 0)
            mock_load.assert_called_once_with(BOOTS.questions_file)
            code, _, _ = run_main(audit_runner.main, ["--audit", DEFAULT_AUDIT_SLUG])
            self.assertEqual(code, 0)
            self.assertEqual(mock_load.call_args.args, (BOOTS.questions_file,))
        code, _, err = run_main(audit_runner.main, ["--audit", "no-such-client"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown audit", err)

    def test_batch_defaults_boots_and_unknown_slug(self) -> None:
        with patch("run_batch_audit.run_batch_audit") as mock_batch:
            code, _, _ = run_main(run_batch_audit.main, [])
            self.assertEqual(code, 0)
            kwargs = mock_batch.call_args.kwargs
            self.assertIsNone(kwargs["question_csv_path"])
            self.assertIsNone(kwargs["results_csv_path"])
            self.assertIsNone(kwargs["audit_config"])

            code, _, _ = run_main(run_batch_audit.main, ["--audit", DEFAULT_AUDIT_SLUG])
            self.assertEqual(mock_batch.call_args.kwargs["audit_config"], BOOTS)

            mock_batch.reset_mock()
            code, _, err = run_main(run_batch_audit.main, ["--audit", "no-such-client"])
            self.assertEqual(code, 1)
            self.assertIn("Unknown audit", err)
            mock_batch.assert_not_called()

    def test_batch_none_paths_resolve_to_boots(self) -> None:
        with patch("run_batch_audit.load_questions", side_effect=audit_runner.AuditRunnerError("stop")) as mock_load:
            with self.assertRaises(audit_runner.AuditRunnerError):
                run_batch_audit.run_batch_audit()
        mock_load.assert_called_once_with(BOOTS.questions_file)


class ParseAuditArgTests(unittest.TestCase):
    def test_absent_flag_returns_none_and_unchanged_argv(self) -> None:
        self.assertEqual(parse_audit_arg(["a", "b"]), (None, ["a", "b"]))

    def test_flag_anywhere_and_equals_form(self) -> None:
        for argv in (["--audit", DEFAULT_AUDIT_SLUG, "a", "b"], ["a", f"--audit={DEFAULT_AUDIT_SLUG}", "b"]):
            with self.subTest(argv=argv):
                config, remaining = parse_audit_arg(argv)
                self.assertEqual(config, BOOTS)
                self.assertEqual(remaining, ["a", "b"])

    def test_repeated_or_missing_value_fails(self) -> None:
        for argv in (["--audit"], ["--audit", "--other"], ["--audit", DEFAULT_AUDIT_SLUG, "--audit", DEFAULT_AUDIT_SLUG]):
            with self.subTest(argv=argv):
                with self.assertRaises(AuditConfigError):
                    parse_audit_arg(argv)


class BootsAuditFlagByteIdenticalTests(_SafeTestCase):
    """Real (unmocked) CLI runs: --audit boots output == no-flag output == committed report."""

    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.questions = str(REPO_ROOT / BOOTS.questions_file)
        self.results = str(REPO_ROOT / BOOTS.results_file)
        # The CLIs stamp today's date; pin it to the committed reference date.
        for module in ("report_generator", "geo_findings_analyzer", "measurement_engine"):
            date_patch = patch(f"{module}.date", MagicMock(today=MagicMock(return_value=date(2026, 7, 18))))
            date_patch.start()
            self.addCleanup(date_patch.stop)

    def committed(self, name: str) -> bytes:
        return (REPO_ROOT / BOOTS.reports_dir / name).read_bytes().replace(b"\r\n", b"\n")

    def generated(self, path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    def test_report_generator(self) -> None:
        a, b = self.tmp / "a.md", self.tmp / "b.md"
        self.assertEqual(run_main(report_generator.main, [self.questions, self.results, str(a)])[0], 0)
        self.assertEqual(
            run_main(report_generator.main, ["--audit", DEFAULT_AUDIT_SLUG, self.questions, self.results, str(b)])[0], 0
        )
        self.assertEqual(self.generated(a), self.generated(b))
        self.assertEqual(self.generated(b), self.committed("audit_report.md"))

    def test_geo_findings(self) -> None:
        a, b = self.tmp / "a.md", self.tmp / "b.md"
        run_main(geo_findings_analyzer.main, [self.questions, self.results, str(a)])
        run_main(geo_findings_analyzer.main, [self.questions, self.results, str(b), "--audit", DEFAULT_AUDIT_SLUG])
        self.assertEqual(self.generated(a), self.generated(b))
        self.assertEqual(self.generated(b), self.committed("GEO_FINDINGS.md"))

    def test_measurement(self) -> None:
        a, b = self.tmp / "a.md", self.tmp / "b.md"
        run_main(measurement_engine.main, [self.results, self.results, self.questions, str(a)])
        run_main(measurement_engine.main, ["--audit", DEFAULT_AUDIT_SLUG, self.results, self.results, self.questions, str(b)])
        self.assertEqual(self.generated(a), self.generated(b))
        self.assertEqual(self.generated(b), self.committed("GEO_PROGRESS.md"))


# --------------------------------------------------------------------------
# 5, 7, 8. --audit selecting a fictional audit (real CLI runs)
# --------------------------------------------------------------------------


class FictionalAuditCliTests(_FictionalWorkspaceTestCase):
    def assert_fictional_report(self, relative: str, title_prefix: str) -> None:
        text = self.read(relative)
        self.assertEqual(text.splitlines()[0], f"{title_prefix} — Lumora Tea Co. Specialty Tea")
        self.assertIn("- Brand: Lumora", text)
        self.assert_no_boots_leak(text)

    def test_report_generator(self) -> None:
        code, out, err = run_main(report_generator.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        self.assertIn(self.config.audit_report_file, out)
        self.assert_fictional_report(self.config.audit_report_file, "# SignalScope AI Audit Report")

    def test_geo_findings(self) -> None:
        code, _, err = run_main(geo_findings_analyzer.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        self.assert_fictional_report(self.config.findings_report_file, "# SignalScope AI GEO Findings Report")

    @patch("recommendation_engine.generate_response", return_value=CANNED_RECOMMENDATIONS)
    def test_recommendation_engine(self, mock_generate) -> None:
        code, _, err = run_main(recommendation_engine.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        prompt = mock_generate.call_args.args[0]
        self.assertIn("Brand: Lumora\nMarket: Republic of Veloria\nCategory: Specialty Tea Retail", prompt)
        self.assert_no_boots_leak(prompt)
        self.assert_fictional_report(
            self.config.recommendations_report_file, "# SignalScope AI GEO Recommendations Report"
        )

    def test_measurement_engine(self) -> None:
        results = self.config.results_file
        code, out, err = run_main(measurement_engine.main, [results, results, "--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        self.assertIn("structural validation run", out)
        self.assert_fictional_report(self.config.progress_report_file, "# SignalScope AI GEO Progress Report")

    @patch("run_structured_audit.analyze_response", return_value=dict(ANALYSIS_RESULT))
    @patch("run_structured_audit.generate_response", return_value="Lumora answer.")
    def test_structured_audit(self, _gen, mock_analyze) -> None:
        code, _, err = run_main(run_structured_audit.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        mock_analyze.assert_called_once_with("Lumora answer.", "Lumora", ["Brewvale", "Kettleworth", "Steepwise"])
        self.assertEqual(self.results_rows()[-1]["question_id"], "PA04")

    @patch("run_end_to_end_demo.analyze_response", return_value=dict(ANALYSIS_RESULT))
    @patch("run_end_to_end_demo.generate_response", return_value="Lumora answer.")
    def test_end_to_end_demo(self, _gen, mock_analyze) -> None:
        code, out, err = run_main(run_end_to_end_demo.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        mock_analyze.assert_called_once_with("Lumora answer.", "Lumora", ["Brewvale", "Kettleworth", "Steepwise"])
        self.assertIn(self.config.results_file, out)
        self.assertEqual(self.results_rows()[-1]["question_id"], "PA05")
        self.assert_fictional_report(self.config.audit_report_file, "# SignalScope AI Audit Report")

    @patch("run_batch_audit.generate_response", return_value="Lumora batch answer.")
    def test_batch_audit_uses_selected_audit_paths(self, mock_generate) -> None:
        code, out, err = run_main(run_batch_audit.main, ["--audit", FICTIONAL_SLUG, "--delay", "0", "--limit", "1"])
        self.assertEqual(code, 0, err)
        self.assertIn("Total questions: 3", out)
        mock_generate.assert_called_once_with("Tea challenges?")
        rows = self.results_rows()
        self.assertEqual((rows[-1]["question_id"], rows[-1]["engine"]), ("PA01", "Gemini"))

    def test_batch_audit_passes_selected_config(self) -> None:
        with patch("run_batch_audit.run_batch_audit") as mock_batch:
            run_main(run_batch_audit.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(mock_batch.call_args.kwargs["audit_config"], self.config)

    @patch("write_single_audit_result.generate_response", return_value="Lumora single answer.")
    def test_write_single_audit_result(self, _gen) -> None:
        code, _, err = run_main(write_single_audit_result.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.results_rows()[-1]["answer_snippet"], "Lumora single answer.")

    @patch("run_single_audit.generate_response", return_value="Lumora single answer.")
    def test_run_single_audit(self, mock_generate) -> None:
        code, out, err = run_main(run_single_audit.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        mock_generate.assert_called_once_with("Tea challenges?")
        self.assertIn("Lumora single answer.", out)

    def test_audit_runner(self) -> None:
        code, out, err = run_main(audit_runner.main, ["--audit", FICTIONAL_SLUG])
        self.assertEqual(code, 0, err)
        self.assertIn("Total questions loaded: 3", out)

    def test_no_boots_folders_created_in_workspace(self) -> None:
        run_main(report_generator.main, ["--audit", FICTIONAL_SLUG])
        self.assertFalse((self.workspace / "audits" / DEFAULT_AUDIT_SLUG).exists())
        self.assertFalse((self.workspace / "reports" / DEFAULT_AUDIT_SLUG).exists())


class ExplicitPathOverrideTests(_FictionalWorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.alt_questions = self.workspace / "elsewhere" / "q.csv"
        self.alt_results = self.workspace / "elsewhere" / "r.csv"
        write_csv(self.alt_questions, list(QUESTION_ROWS[0]), QUESTION_ROWS[:1])
        write_csv(self.alt_results, RESULTS_SCHEMA, RESULT_ROWS)

    def test_positional_paths_override_config_paths(self) -> None:
        out_path = self.workspace / "elsewhere" / "report.md"
        code, _, err = run_main(
            report_generator.main,
            ["--audit", FICTIONAL_SLUG, str(self.alt_questions), str(self.alt_results), str(out_path)],
        )
        self.assertEqual(code, 0, err)
        text = out_path.read_text(encoding="utf-8")
        self.assertIn("covering 1 of the 1 questions", text)  # alt question file, not the config's 3
        self.assertIn("— Lumora Tea Co. Specialty Tea", text.splitlines()[0])
        self.assertFalse((self.workspace / self.config.audit_report_file).exists())

    def test_workhorse_receives_explicit_paths(self) -> None:
        with patch("geo_findings_analyzer.generate_geo_findings", return_value=([], "")) as mock_fn:
            run_main(geo_findings_analyzer.main, ["--audit", FICTIONAL_SLUG, "q.csv", "r.csv", "out.md"])
        self.assertEqual(mock_fn.call_args.args, ("q.csv", "r.csv", "out.md"))
        self.assertEqual(mock_fn.call_args.kwargs["audit_config"], self.config)

    @patch("run_batch_audit.generate_response", return_value="Answer.")
    def test_batch_explicit_questions_override_selected_audit(self, mock_generate) -> None:
        code, out, err = run_main(
            run_batch_audit.main,
            ["--audit", FICTIONAL_SLUG, "--questions", str(self.alt_questions), "--delay", "0", "--limit", "1"],
        )
        self.assertEqual(code, 0, err)
        self.assertIn("Total questions: 1", out)  # alt question file
        self.assertEqual(self.results_rows()[-1]["question_id"], "PA01")  # config's results file


# --------------------------------------------------------------------------
# 9. Streamlit dashboard
# --------------------------------------------------------------------------


class StreamlitDashboardTests(unittest.TestCase):
    APP = REPO_ROOT / "streamlit_app.py"

    def test_source_has_no_client_literals_and_uses_audit_config(self) -> None:
        source = self.APP.read_text(encoding="utf-8")
        for literal in BOOTS_LEAK_MARKERS:
            self.assertNotIn(literal, source)
        self.assertIn("default_audit_config()", source)
        self.assertNotRegex(source, r"^import config\b")

    def test_dashboard_renders_default_boots_audit(self) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:  # pragma: no cover - streamlit is a declared dependency
            self.skipTest("streamlit.testing is not available")

        app = AppTest.from_file(str(self.APP), default_timeout=60).run()
        self.assertFalse(app.exception, app.exception)

        sidebar = " ".join(m.value for m in app.sidebar.markdown)
        self.assertIn("**Brand:** Boots UK", sidebar)
        self.assertIn("**Industry:** Health & Beauty Retail", sidebar)
        self.assertIn("**Version:** 2.1.0", sidebar)

        body = " ".join(m.value for m in app.markdown)
        self.assertIn("**Country**  \nUnited Kingdom", body)
        self.assertIn("**Question Library**  \nUK Retail GEO Library", body)
        self.assertEqual(len(app.warning), 0)  # the default audit's results were found


# --------------------------------------------------------------------------
# 10. Static guard: no client literals in reusable production code
# --------------------------------------------------------------------------


class StaticClientLiteralGuardTests(unittest.TestCase):
    MARKERS = ["Boots", "Superdrug", "Amazon", "Holland & Barrett", "Health & Beauty Retail", "United Kingdom"]
    ALLOWED_SLUG_LINE = f'DEFAULT_AUDIT_SLUG = "{DEFAULT_AUDIT_SLUG}"'

    def production_files(self) -> list[Path]:
        return [*sorted(SRC_DIR.glob("*.py")), REPO_ROOT / "config.py", REPO_ROOT / "streamlit_app.py"]

    def test_no_client_business_literals(self) -> None:
        for path in self.production_files():
            source = path.read_text(encoding="utf-8")
            for marker in self.MARKERS:
                with self.subTest(file=path.name, marker=marker):
                    self.assertNotIn(marker, source)

    def test_default_slug_only_in_audit_config(self) -> None:
        for path in self.production_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if DEFAULT_AUDIT_SLUG in line:
                    with self.subTest(file=path.name, line=number):
                        self.assertEqual(path.name, "audit_config.py")
                        self.assertEqual(line.strip(), self.ALLOWED_SLUG_LINE)

    def test_guard_covers_every_src_module(self) -> None:
        names = {p.name for p in self.production_files()}
        self.assertTrue({"audit_config.py", "report_generator.py", "run_batch_audit.py"} <= names)
        self.assertTrue(re.match(r"^[a-z0-9-]+$", DEFAULT_AUDIT_SLUG))


if __name__ == "__main__":
    unittest.main()
