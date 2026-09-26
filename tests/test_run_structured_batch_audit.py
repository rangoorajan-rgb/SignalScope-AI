"""Tests for src/run_structured_batch_audit.py - v2.3 Checkpoint A:
raw evidence, question states and single-question processing.

Answers are faked by patching run_batch_audit.generate_response (used by
generate_with_retry); analysis is faked by patching
response_analyzer.generate_response, so the real, unchanged analyser
parses and validates the fake JSON. The Gemini SDK is blocked. Every
evidence file is written under a temporary directory; the real audits/,
reports/ and master template are verified unchanged after each test, and
no raw_responses folder may appear under the real audits/.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import os
import subprocess
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gemini_client  # noqa: E402
import run_structured_batch_audit as sba  # noqa: E402
from audit_config import AuditConfig  # noqa: E402
from gemini_client import GeminiClientError  # noqa: E402
from response_analyzer import ResponseAnalysisError  # noqa: E402
from run_structured_batch_audit import (  # noqa: E402
    EVIDENCE_FIELDS,
    STATE_ANSWER_STORED,
    STATE_COMPLETE_WITH_EVIDENCE,
    STATE_EVIDENCE_INTEGRITY_ERROR,
    STATE_LEGACY_COMPLETE_NO_EVIDENCE,
    STATE_LEGACY_INCOMPLETE,
    STATE_NOT_STARTED,
    EvidenceIntegrityError,
    EvidenceStorageError,
    QuestionProcessingError,
    RawEvidence,
    classify_question,
    evidence_dir_for,
    evidence_path,
    is_structurally_complete,
    load_evidence,
    parse_evidence,
    process_question,
    publish_evidence,
    serialise_evidence,
    structural_problems,
    validate_question_ids,
)
from write_single_audit_result import RESULTS_SCHEMA, normalise_snippet  # noqa: E402
import create_audit  # noqa: E402
import write_single_audit_result  # noqa: E402
from audit_runner import AuditRunnerError, load_questions  # noqa: E402
from geo_findings_analyzer import generate_geo_findings  # noqa: E402
from report_generator import gemini_coverage_complete, generate_report  # noqa: E402
from run_structured_batch_audit import StructuredBatchError, run_structured_batch_audit  # noqa: E402
from write_single_audit_result import WriteAuditResultError, load_existing_results  # noqa: E402

BOOTS_SLUG = "boots-uk-health-beauty"
BOOTS_AUDIT_DIR = REPO_ROOT / "audits" / BOOTS_SLUG
MASTER_TEMPLATE = REPO_ROOT / "questions" / "buyer_questions_master.csv"

CONFIG = AuditConfig(
    slug="lumiere-veloria-tea",
    brand="Lumière",
    company_name="Lumière & Fils Ltd",
    report_subject="Lumière & Fils Specialty Tea",
    market="Republic of Veloria",
    category="Specialty Tea Retail",
    competitors=("Brewvale", "O'Kettle & Co", "Steepwisé"),
    question_library="Veloria Tea GEO Library",
)

QUESTION = {
    "question_id": "SD04",
    "buyer_journey_stage": "Solution Discovery",
    "question": "Who are the leading companies offering Specialty Tea Retail in Republic of Veloria?",
    "intent": "Intent.",
    "notes": "Notes.",
}

LONG_ANSWER = (
    'The leading specialty tea retailers in the Republic of Veloria are, in order:\n\n'
    '1. Lumière — "the connoisseur\'s choice", praised for single-estate oolongs; widely stocked.\n'
    '2. Brewvale, a value-focused chain with 120 stores; strong on everyday blends.\n'
    '3. O\'Kettle & Co — known for its ceremonial matcha (抹茶) and rooibos, 🍵 lovers\' favourite.\n\n'
    'Sources: Veloria Tea Review, "Leaf Journal" (2026); Café Society Annual.\n'
    + "Further detail: " + "provenance, freshness; price, service, range. " * 12
    + "\n\tEnd of answer — naïve façade coöperation résumé."
)

FIXED_DAY = date(2026, 9, 26)


def analysis_json(**overrides) -> str:
    payload = {
        "brand_cited": "Y",
        "brand_position": 1,
        "competitors_cited": ["Brewvale", "O'Kettle & Co"],
        "sources_cited": ["Veloria Tea Review", "Leaf Journal"],
        "sentiment": "Positive",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def make_evidence(**overrides) -> RawEvidence:
    values = dict(
        format_version=1,
        audit_slug=CONFIG.slug,
        question_id=QUESTION["question_id"],
        question=QUESTION["question"],
        engine="Gemini",
        requested_model="gemini-2.5-flash",
        run_date="2026-09-20",
        raw_response_text=LONG_ANSWER,
    )
    values.update(overrides)
    return RawEvidence(**values)


def complete_row(**overrides) -> dict[str, str]:
    row = {
        "run_date": "2026-09-20",
        "question_id": QUESTION["question_id"],
        "question": QUESTION["question"],
        "funnel_stage": QUESTION["buyer_journey_stage"],
        "engine": "Gemini",
        "brand_cited": "Y",
        "brand_position": "1",
        "competitors_cited": "Brewvale; O'Kettle & Co",
        "sources_cited": "Veloria Tea Review",
        "sentiment": "Positive",
        "answer_snippet": normalise_snippet(LONG_ANSWER),
    }
    row.update(overrides)
    return row


class RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def production_snapshot() -> dict[str, bytes | None]:
    paths = [MASTER_TEMPLATE, *(REPO_ROOT / "audits").rglob("*"), *(REPO_ROOT / "reports").rglob("*")]
    return {str(p): (p.read_bytes() if p.is_file() else None) for p in sorted(paths)}


class _SafeTestCase(unittest.TestCase):
    """Blocks the Gemini SDK, gives each test a temporary evidence folder,
    and verifies production data is unchanged afterwards."""

    def setUp(self) -> None:
        guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini call attempted"))
        guard.start()
        self.addCleanup(guard.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.evidence_dir = self.tmp / "audits" / CONFIG.slug / "raw_responses"
        before = production_snapshot()

        def check() -> None:
            self.assertEqual(production_snapshot(), before, "production audits/reports/template changed")
            self.assertEqual(list((REPO_ROOT / "audits").glob("*/raw_responses")), [])

        self.addCleanup(check)

    def evidence_file(self) -> Path:
        return evidence_path(self.evidence_dir, QUESTION["question_id"])

    def write_raw_evidence_text(self, text: str) -> Path:
        path = self.evidence_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def temp_files(self) -> list[str]:
        if not self.evidence_dir.exists():
            return []
        return [p.name for p in self.evidence_dir.iterdir() if p.name.endswith(".tmp")]

    def process(self, existing_rows=None, sleep=None) -> dict[str, str]:
        return process_question(
            QUESTION, CONFIG, existing_rows or [],
            evidence_dir=self.evidence_dir, sleep_fn=sleep or RecordingSleep(), today=lambda: FIXED_DAY,
        )


# --------------------------------------------------------------------------
# Question IDs
# --------------------------------------------------------------------------


class QuestionIdTests(unittest.TestCase):
    def test_standard_ids_accepted(self) -> None:
        with MASTER_TEMPLATE.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        validate_question_ids(rows)
        validate_question_ids([{"question_id": "Q_1-a"}])

    def test_unsafe_ids_rejected(self) -> None:
        for bad in ["PA/01", "PA\\01", "..", "../PA01", "PA.01", "PA 01", "PA01!", "PA:01", "PÄ01", "", "PA01\n"]:
            with self.subTest(question_id=bad):
                with self.assertRaises(QuestionProcessingError):
                    validate_question_ids([{"question_id": bad}])

    def test_case_insensitive_collision_rejected(self) -> None:
        with self.assertRaises(QuestionProcessingError) as ctx:
            validate_question_ids([{"question_id": "PA01"}, {"question_id": "pa01"}])
        self.assertIn("differ only by case", str(ctx.exception))

    def test_evidence_path(self) -> None:
        self.assertEqual(evidence_path("x", "PA01"), Path("x") / "PA01__gemini.json")
        self.assertEqual(
            evidence_dir_for("audits/acme/audit_results.csv"), Path("audits/acme/raw_responses")
        )


class UnsafeQuestionProcessingTests(_SafeTestCase):
    @patch("response_analyzer.generate_response")
    @patch("run_batch_audit.generate_response")
    def test_no_api_call_before_id_validation(self, mock_answer, mock_analysis) -> None:
        for bad in ["../PA01", "PA 01"]:
            with self.subTest(question_id=bad):
                with self.assertRaises(QuestionProcessingError):
                    process_question({**QUESTION, "question_id": bad}, CONFIG, [], evidence_dir=self.evidence_dir)
        mock_answer.assert_not_called()
        mock_analysis.assert_not_called()
        self.assertFalse(self.evidence_dir.exists())


# --------------------------------------------------------------------------
# Raw evidence format and validation
# --------------------------------------------------------------------------


class EvidenceFormatTests(_SafeTestCase):
    def test_long_answer_fixture_exercises_edge_cases(self) -> None:
        self.assertGreater(len(LONG_ANSWER), 500)
        for fragment in ["\n", '"', ",", ";", "抹茶", "🍵", "\t"]:
            self.assertIn(fragment, LONG_ANSWER)

    def test_serialise_parse_round_trip_is_exact(self) -> None:
        evidence = make_evidence()
        text = serialise_evidence(evidence)
        self.assertEqual(parse_evidence(text, audit_slug=CONFIG.slug, question_row=QUESTION), evidence)
        self.assertEqual(json.loads(text)["raw_response_text"], LONG_ANSWER)

    def test_serialisation_format(self) -> None:
        text = serialise_evidence(make_evidence())
        self.assertEqual(list(json.loads(text)), list(EVIDENCE_FIELDS))
        self.assertEqual(text, json.dumps(dataclasses.asdict(make_evidence()), indent=2, ensure_ascii=False) + "\n")
        self.assertIn("抹茶", text)  # not \u-escaped
        self.assertTrue(text.endswith("}\n"))
        self.assertFalse(text.encode("utf-8").startswith(b"\xef\xbb\xbf"))
        self.assertEqual(serialise_evidence(make_evidence()), text)  # deterministic

    def test_different_requested_model_is_accepted(self) -> None:
        text = serialise_evidence(make_evidence(requested_model="gemini-9.9-pro"))
        self.assertEqual(
            parse_evidence(text, audit_slug=CONFIG.slug, question_row=QUESTION).requested_model, "gemini-9.9-pro"
        )

    def assert_rejected(self, text: str, fragment: str) -> None:
        with self.assertRaises(EvidenceIntegrityError) as ctx:
            parse_evidence(text, audit_slug=CONFIG.slug, question_row=QUESTION)
        self.assertIn(fragment, str(ctx.exception))

    def test_conflicting_evidence_rejected(self) -> None:
        cases = {
            "audit_slug": ("another-audit", "audit_slug"),
            "question_id": ("SD05", "question_id"),
            "question": ("A different question?", "question text"),
            "engine": ("Perplexity", "engine"),
            "raw_response_text": ("   \n ", "raw_response_text is empty"),
            "requested_model": (" ", "requested_model is empty"),
            "run_date": ("26/09/2026", "run_date"),
        }
        for field, (value, fragment) in cases.items():
            with self.subTest(field=field):
                self.assert_rejected(serialise_evidence(make_evidence(**{field: value})), fragment)
        self.assert_rejected(serialise_evidence(make_evidence(run_date="2026-02-30")), "run_date")

    def test_structural_problems_rejected(self) -> None:
        base = dataclasses.asdict(make_evidence())
        self.assert_rejected("{not json", "not valid JSON")
        self.assert_rejected("[1, 2]", "not a JSON object")
        self.assert_rejected(json.dumps({k: v for k, v in base.items() if k != "engine"}), "missing field")
        self.assert_rejected(json.dumps({**base, "analysis": {}}), "unexpected field")
        for version in (2, 0, "1", True, None):
            with self.subTest(format_version=version):
                self.assert_rejected(json.dumps({**base, "format_version": version}), "format_version")
        self.assert_rejected(json.dumps({**base, "question": 7}), "must be a string")

    def test_load_evidence(self) -> None:
        self.assertIsNone(load_evidence(self.evidence_file(), audit_slug=CONFIG.slug, question_row=QUESTION))
        self.write_raw_evidence_text(serialise_evidence(make_evidence()))
        self.assertEqual(
            load_evidence(self.evidence_file(), audit_slug=CONFIG.slug, question_row=QUESTION), make_evidence()
        )
        self.evidence_file().write_bytes(b"\xff\xfe not utf-8")
        with self.assertRaises(EvidenceIntegrityError):
            load_evidence(self.evidence_file(), audit_slug=CONFIG.slug, question_row=QUESTION)


class PublishEvidenceTests(_SafeTestCase):
    def test_publish_creates_folder_and_exact_file(self) -> None:
        self.assertFalse(self.evidence_dir.exists())
        path = publish_evidence(make_evidence(), self.evidence_dir)
        self.assertEqual(path, self.evidence_file())
        self.assertEqual(path.read_bytes(), serialise_evidence(make_evidence()).encode("utf-8"))
        self.assertEqual(self.temp_files(), [])

    def test_existing_evidence_never_overwritten(self) -> None:
        original = serialise_evidence(make_evidence(raw_response_text="Original answer."))
        self.write_raw_evidence_text(original)
        with self.assertRaises(EvidenceIntegrityError) as ctx:
            publish_evidence(make_evidence(raw_response_text="Replacement answer."), self.evidence_dir)
        self.assertIn("will not be overwritten", str(ctx.exception))
        self.assertEqual(self.evidence_file().read_text(encoding="utf-8"), original)
        self.assertEqual(self.temp_files(), [])

    def test_hard_link_failure_is_a_storage_error_without_fallback(self) -> None:
        with patch("run_structured_batch_audit.os.link", side_effect=OSError("hard links not supported")), \
                patch("run_structured_batch_audit.os.replace", side_effect=AssertionError("no replace fallback")), \
                patch("run_structured_batch_audit.os.rename", side_effect=AssertionError("no rename fallback")):
            with self.assertRaises(EvidenceStorageError) as ctx:
                publish_evidence(make_evidence(), self.evidence_dir)
        self.assertIn("hard links", str(ctx.exception))
        self.assertFalse(self.evidence_file().exists())
        self.assertEqual(self.temp_files(), [])

    def test_write_failure_leaves_no_final_file(self) -> None:
        with patch("run_structured_batch_audit.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                publish_evidence(make_evidence(), self.evidence_dir)
        self.assertFalse(self.evidence_file().exists())
        self.assertEqual(self.temp_files(), [])


# --------------------------------------------------------------------------
# Structural completeness
# --------------------------------------------------------------------------


class StructuralCompletenessTests(unittest.TestCase):
    def test_complete_row(self) -> None:
        self.assertTrue(is_structurally_complete(complete_row(), QUESTION))
        self.assertTrue(is_structurally_complete(
            complete_row(brand_cited="N", brand_position="", competitors_cited="", sources_cited="",
                         sentiment="Neutral"), QUESTION))
        self.assertTrue(is_structurally_complete(complete_row(brand_position=""), QUESTION))

    def test_incomplete_rows(self) -> None:
        cases = {
            "engine": complete_row(engine="Perplexity"),
            "question_id": complete_row(question_id="SD05"),
            "question": complete_row(question="Other?"),
            "funnel_stage": complete_row(funnel_stage="Purchase Decision"),
            "run_date blank": complete_row(run_date=""),
            "run_date invalid": complete_row(run_date="2026-13-01"),
            "snippet blank": complete_row(answer_snippet=" "),
            "brand_cited blank": complete_row(brand_cited=""),
            "brand_cited invalid": complete_row(brand_cited="Yes"),
            "sentiment blank": complete_row(sentiment=""),
            "sentiment invalid": complete_row(sentiment="Mixed"),
            "position zero": complete_row(brand_position="0"),
            "position text": complete_row(brand_position="first"),
            "position with N": complete_row(brand_cited="N", brand_position="2"),
            "line break": complete_row(sources_cited="A\nB"),
        }
        for name, row in cases.items():
            with self.subTest(case=name):
                self.assertFalse(is_structurally_complete(row, QUESTION))
        self.assertIn("columns", structural_problems({"question_id": "SD04"}, QUESTION)[0])


# --------------------------------------------------------------------------
# A-F classification
# --------------------------------------------------------------------------


class ClassificationTests(_SafeTestCase):
    def classify(self, rows):
        return classify_question(QUESTION, rows, evidence_dir=self.evidence_dir, audit_slug=CONFIG.slug)

    def test_a_not_started(self) -> None:
        self.assertEqual(self.classify([]).state, STATE_NOT_STARTED)
        perplexity = complete_row(engine="Perplexity")
        self.assertEqual(self.classify([perplexity]).state, STATE_NOT_STARTED)

    def test_b_answer_stored(self) -> None:
        publish_evidence(make_evidence(), self.evidence_dir)
        state = self.classify([])
        self.assertEqual(state.state, STATE_ANSWER_STORED)
        self.assertEqual(state.evidence, make_evidence())

    def test_c_complete_with_evidence(self) -> None:
        publish_evidence(make_evidence(), self.evidence_dir)
        self.assertEqual(self.classify([complete_row()]).state, STATE_COMPLETE_WITH_EVIDENCE)

    def test_d_legacy_incomplete_with_or_without_evidence(self) -> None:
        raw_row = complete_row(brand_cited="", brand_position="", competitors_cited="", sources_cited="",
                               sentiment="")
        self.assertEqual(self.classify([raw_row]).state, STATE_LEGACY_INCOMPLETE)
        publish_evidence(make_evidence(), self.evidence_dir)
        state = self.classify([raw_row])
        self.assertEqual(state.state, STATE_LEGACY_INCOMPLETE)
        self.assertIn("evidence file also exists", state.detail)
        self.write_raw_evidence_text("{malformed")
        self.evidence_file().write_text("{malformed", encoding="utf-8")
        self.assertEqual(self.classify([raw_row]).state, STATE_LEGACY_INCOMPLETE)

    def test_e_legacy_complete_without_evidence(self) -> None:
        self.assertEqual(self.classify([complete_row()]).state, STATE_LEGACY_COMPLETE_NO_EVIDENCE)

    def test_f_integrity_errors(self) -> None:
        self.write_raw_evidence_text("{malformed")
        self.assertEqual(self.classify([]).state, STATE_EVIDENCE_INTEGRITY_ERROR)
        self.assertEqual(self.classify([complete_row()]).state, STATE_EVIDENCE_INTEGRITY_ERROR)

        self.evidence_file().write_text(serialise_evidence(make_evidence(audit_slug="other-audit")), encoding="utf-8")
        self.assertEqual(self.classify([]).state, STATE_EVIDENCE_INTEGRITY_ERROR)

        self.evidence_file().write_text(serialise_evidence(make_evidence()), encoding="utf-8")
        snippet_mismatch = self.classify([complete_row(answer_snippet="Something else entirely.")])
        self.assertEqual(snippet_mismatch.state, STATE_EVIDENCE_INTEGRITY_ERROR)
        self.assertIn("answer_snippet", snippet_mismatch.detail)
        date_mismatch = self.classify([complete_row(run_date="2026-09-21")])
        self.assertEqual(date_mismatch.state, STATE_EVIDENCE_INTEGRITY_ERROR)
        self.assertIn("run_date", date_mismatch.detail)

        self.assertEqual(self.classify([complete_row(), complete_row()]).state, STATE_EVIDENCE_INTEGRITY_ERROR)

    def test_classification_never_writes(self) -> None:
        self.classify([])
        self.assertFalse(self.evidence_dir.exists())


class RealBootsClassificationTests(_SafeTestCase):
    """Protects the historical-data policy: the committed Boots rows are
    classified, never reprocessed, and no evidence is created for them."""

    def test_real_boots_states(self) -> None:
        with (BOOTS_AUDIT_DIR / "buyer_questions.csv").open(newline="", encoding="utf-8-sig") as handle:
            questions = list(csv.DictReader(handle))
        with (BOOTS_AUDIT_DIR / "audit_results.csv").open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        evidence_dir = evidence_dir_for(BOOTS_AUDIT_DIR / "audit_results.csv")
        self.assertFalse(evidence_dir.exists())

        states = {
            q["question_id"]: classify_question(q, rows, evidence_dir=evidence_dir, audit_slug=BOOTS_SLUG).state
            for q in questions
        }
        by_state: dict[str, list[str]] = {}
        for question_id, state in states.items():
            by_state.setdefault(state, []).append(question_id)

        self.assertEqual(by_state[STATE_LEGACY_INCOMPLETE], ["PA01", "PA02", "PA03"])
        self.assertEqual(by_state[STATE_LEGACY_COMPLETE_NO_EVIDENCE], ["PA04", "PA05"])
        self.assertEqual(len(by_state[STATE_NOT_STARTED]), 35)
        self.assertEqual(set(by_state), {STATE_LEGACY_INCOMPLETE, STATE_LEGACY_COMPLETE_NO_EVIDENCE, STATE_NOT_STARTED})
        self.assertFalse(evidence_dir.exists())

    @patch("response_analyzer.generate_response")
    @patch("run_batch_audit.generate_response")
    def test_boots_legacy_rows_are_refused_by_process_question(self, mock_answer, mock_analysis) -> None:
        with (BOOTS_AUDIT_DIR / "buyer_questions.csv").open(newline="", encoding="utf-8-sig") as handle:
            questions = {q["question_id"]: q for q in csv.DictReader(handle)}
        with (BOOTS_AUDIT_DIR / "audit_results.csv").open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        boots = AuditConfig(**{**dataclasses.asdict(CONFIG), "slug": BOOTS_SLUG})
        for question_id in ("PA01", "PA04"):
            with self.subTest(question_id=question_id):
                with self.assertRaises(QuestionProcessingError):
                    process_question(questions[question_id], boots, rows, evidence_dir=self.evidence_dir)
        mock_answer.assert_not_called()
        mock_analysis.assert_not_called()
        self.assertFalse(self.evidence_dir.exists())


# --------------------------------------------------------------------------
# Single-question processing, failures and resume
# --------------------------------------------------------------------------


@patch("response_analyzer.generate_response")
@patch("run_batch_audit.generate_response")
class ProcessQuestionTests(_SafeTestCase):
    def test_a_new_question(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.return_value = analysis_json()

        row = self.process()

        mock_answer.assert_called_once_with(QUESTION["question"])
        mock_analysis.assert_called_once()
        self.assertIn(LONG_ANSWER, mock_analysis.call_args.args[0])  # analysed the full answer
        evidence = load_evidence(self.evidence_file(), audit_slug=CONFIG.slug, question_row=QUESTION)
        self.assertEqual(evidence.raw_response_text, LONG_ANSWER)
        self.assertEqual(evidence.requested_model, gemini_client.DEFAULT_MODEL)
        self.assertEqual(evidence.run_date, "2026-09-26")
        self.assertEqual(evidence.engine, "Gemini")
        self.assertEqual(list(row), RESULTS_SCHEMA)
        self.assertTrue(is_structurally_complete(row, QUESTION))
        self.assertEqual(row["brand_cited"], "Y")
        self.assertEqual(row["brand_position"], "1")
        self.assertEqual(row["competitors_cited"], "Brewvale; O'Kettle & Co")
        self.assertEqual(row["sources_cited"], "Veloria Tea Review; Leaf Journal")
        self.assertEqual(row["sentiment"], "Positive")
        self.assertEqual(row["run_date"], "2026-09-26")

    def test_full_answer_in_evidence_only_snippet_in_row(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.return_value = analysis_json()
        row = self.process()
        self.assertEqual(json.loads(self.evidence_file().read_text(encoding="utf-8"))["raw_response_text"], LONG_ANSWER)
        self.assertEqual(row["answer_snippet"], normalise_snippet(LONG_ANSWER))
        self.assertEqual(len(row["answer_snippet"]), 500)
        self.assertNotIn("\n", row["answer_snippet"])

    def test_analysis_uses_the_stored_file(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.return_value = analysis_json()
        with patch("run_structured_batch_audit.analyze_response", wraps=sba.analyze_response) as spy, \
                patch("run_structured_batch_audit.load_evidence", wraps=sba.load_evidence) as load_spy:
            self.process()
        self.assertEqual(spy.call_args.args[0], LONG_ANSWER)
        self.assertEqual(spy.call_args.args[1:], ("Lumière", ["Brewvale", "O'Kettle & Co", "Steepwisé"]))
        self.assertGreaterEqual(load_spy.call_count, 2)  # classification + reload after publishing

    def test_b_stored_answer_analysed_without_answer_call(self, mock_answer, mock_analysis) -> None:
        publish_evidence(make_evidence(), self.evidence_dir)
        mock_analysis.return_value = analysis_json(brand_cited="N", brand_position=None, competitors_cited=[],
                                                   sources_cited=[], sentiment="Neutral")
        row = self.process()
        mock_answer.assert_not_called()
        mock_analysis.assert_called_once()
        self.assertEqual(row["run_date"], "2026-09-20")  # the evidence date, not today
        self.assertEqual(
            (row["brand_cited"], row["brand_position"], row["competitors_cited"], row["sources_cited"], row["sentiment"]),
            ("N", "", "", "", "Neutral"),
        )

    def test_c_transient_answer_failure_retried(self, mock_answer, mock_analysis) -> None:
        mock_answer.side_effect = [GeminiClientError("Gemini API call failed: 503 UNAVAILABLE"), LONG_ANSWER]
        mock_analysis.return_value = analysis_json()
        sleep = RecordingSleep()
        self.process(sleep=sleep)
        self.assertEqual(mock_answer.call_count, 2)
        self.assertEqual(sleep.calls, [10])

    def test_permanent_answer_failure_writes_nothing(self, mock_answer, mock_analysis) -> None:
        mock_answer.side_effect = GeminiClientError("Gemini API call failed: 401 UNAUTHENTICATED")
        with self.assertRaises(GeminiClientError):
            self.process()
        mock_analysis.assert_not_called()
        self.assertFalse(self.evidence_file().exists())

    def test_blank_answer_is_not_stored(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = "   \n"
        with self.assertRaises(GeminiClientError):
            self.process()
        self.assertFalse(self.evidence_file().exists())
        mock_analysis.assert_not_called()

    def test_d_transient_analysis_failure_retried_without_new_answer(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.side_effect = [
            GeminiClientError("Gemini API call failed: 429 RESOURCE_EXHAUSTED"),
            GeminiClientError("Gemini API call failed: 503 UNAVAILABLE"),
            analysis_json(),
        ]
        sleep = RecordingSleep()
        row = self.process(sleep=sleep)
        self.assertTrue(is_structurally_complete(row, QUESTION))
        self.assertEqual(mock_answer.call_count, 1)
        self.assertEqual(mock_analysis.call_count, 3)
        self.assertEqual(sleep.calls, [10, 30])

    def test_transient_analysis_failure_exhausts_retries(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.side_effect = GeminiClientError("Gemini API call failed: 503 UNAVAILABLE")
        with self.assertRaises(ResponseAnalysisError):
            self.process()
        self.assertEqual(mock_analysis.call_count, 3)
        self.assertTrue(self.evidence_file().exists())

    def test_e_permanent_analysis_error_keeps_evidence_then_resumes_as_b(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.side_effect = GeminiClientError("Gemini API call failed: 400 INVALID_ARGUMENT")
        with self.assertRaises(ResponseAnalysisError):
            self.process()
        self.assertEqual(mock_analysis.call_count, 1)
        stored = self.evidence_file().read_bytes()

        self.assertEqual(
            classify_question(QUESTION, [], evidence_dir=self.evidence_dir, audit_slug=CONFIG.slug).state,
            STATE_ANSWER_STORED,
        )
        mock_answer.reset_mock()
        mock_analysis.reset_mock(side_effect=True)
        mock_analysis.return_value = analysis_json()
        row = self.process()
        mock_answer.assert_not_called()
        self.assertEqual(row["run_date"], "2026-09-26")
        self.assertEqual(self.evidence_file().read_bytes(), stored)

    def test_f_malformed_analysis_json_not_retried(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.return_value = '{"brand_cited": "Y", "error": "500 internal"}'  # contains "500"
        with self.assertRaises(ResponseAnalysisError):
            self.process()
        self.assertEqual(mock_analysis.call_count, 1)
        self.assertTrue(self.evidence_file().exists())

    def test_invalid_analysis_values_not_retried(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.return_value = analysis_json(sentiment="Mixed")
        with self.assertRaises(ResponseAnalysisError):
            self.process()
        self.assertEqual(mock_analysis.call_count, 1)

    def test_g_evidence_publish_failure_stops_before_analysis(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        with patch("run_structured_batch_audit.os.link", side_effect=OSError("hard links not supported")):
            with self.assertRaises(EvidenceStorageError):
                self.process()
        mock_analysis.assert_not_called()
        self.assertFalse(self.evidence_file().exists())
        self.assertEqual(self.temp_files(), [])

    def test_h_evidence_appearing_during_answer_is_not_overwritten(self, mock_answer, mock_analysis) -> None:
        original = serialise_evidence(make_evidence(raw_response_text="Concurrent answer."))

        def answer_while_another_process_publishes(prompt: str) -> str:
            self.write_raw_evidence_text(original)
            return LONG_ANSWER

        mock_answer.side_effect = answer_while_another_process_publishes
        with self.assertRaises(EvidenceIntegrityError):
            self.process()
        mock_analysis.assert_not_called()
        self.assertEqual(self.evidence_file().read_text(encoding="utf-8"), original)

    def test_i_interrupt_after_evidence_then_resume_as_b(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.process()
        self.assertTrue(self.evidence_file().exists())

        mock_answer.reset_mock()
        mock_analysis.reset_mock(side_effect=True)
        mock_analysis.return_value = analysis_json()
        row = self.process()
        mock_answer.assert_not_called()
        self.assertTrue(is_structurally_complete(row, QUESTION))

    def test_run_date_from_evidence_when_analysed_another_day(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            process_question(QUESTION, CONFIG, [], evidence_dir=self.evidence_dir, today=lambda: date(2026, 9, 26))
        mock_analysis.reset_mock(side_effect=True)
        mock_analysis.return_value = analysis_json()
        row = process_question(QUESTION, CONFIG, [], evidence_dir=self.evidence_dir, today=lambda: date(2026, 10, 3))
        self.assertEqual(row["run_date"], "2026-09-26")

    def test_states_c_d_e_f_are_refused(self, mock_answer, mock_analysis) -> None:
        cases = {
            "E": [complete_row()],
            "D": [complete_row(brand_cited="", sentiment="")],
        }
        for name, rows in cases.items():
            with self.subTest(state=name):
                with self.assertRaises(QuestionProcessingError):
                    self.process(rows)
        publish_evidence(make_evidence(), self.evidence_dir)
        with self.assertRaises(QuestionProcessingError):
            self.process([complete_row()])  # C
        self.evidence_file().unlink()
        self.write_raw_evidence_text("{malformed")
        with self.assertRaises(QuestionProcessingError):
            self.process([])  # F
        self.assertEqual(self.evidence_file().read_text(encoding="utf-8"), "{malformed")
        mock_answer.assert_not_called()
        mock_analysis.assert_not_called()


@patch("response_analyzer.generate_response")
@patch("run_batch_audit.generate_response")
class AnalysisVariationTests(_SafeTestCase):
    """Existing analyser behaviour through process_question - not new semantics."""

    def run_with(self, mock_answer, mock_analysis, **analysis) -> dict[str, str]:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.return_value = analysis_json(**analysis)
        return self.process()

    def test_brand_cited_without_ranked_list(self, mock_answer, mock_analysis) -> None:
        row = self.run_with(mock_answer, mock_analysis, brand_position=None)
        self.assertEqual((row["brand_cited"], row["brand_position"]), ("Y", ""))

    def test_brand_removed_from_competitors_and_deduplicated(self, mock_answer, mock_analysis) -> None:
        row = self.run_with(mock_answer, mock_analysis,
                            competitors_cited=["Lumière", "Brewvale", "brewvale", "Steepwisé"])
        self.assertEqual(row["competitors_cited"], "Brewvale; Steepwisé")

    def test_each_sentiment(self, mock_answer, mock_analysis) -> None:
        for sentiment in ("Positive", "Neutral", "Negative"):
            with self.subTest(sentiment=sentiment):
                if self.evidence_dir.exists():
                    shutil.rmtree(self.evidence_dir)
                mock_answer.reset_mock()
                row = self.run_with(mock_answer, mock_analysis, sentiment=sentiment)
                self.assertEqual(row["sentiment"], sentiment)

    def test_position_given_with_brand_absent_is_rejected_by_analyser(self, mock_answer, mock_analysis) -> None:
        mock_answer.return_value = LONG_ANSWER
        mock_analysis.return_value = analysis_json(brand_cited="N", brand_position=2)
        with self.assertRaises(ResponseAnalysisError):
            self.process()


class GitignoreRawEvidenceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git") and (REPO_ROOT / ".git").exists(), "git repository not available")
    def test_raw_evidence_ignored_boots_data_tracked(self) -> None:
        expected = {
            f"audits/{BOOTS_SLUG}/raw_responses/PA01__gemini.json": True,
            "audits/some-client/raw_responses/PA01__gemini.json": True,
            "audits/some-client/audit_results.csv": True,
            f"audits/{BOOTS_SLUG}/audit_results.csv": False,
            f"audits/{BOOTS_SLUG}/audit_config.json": False,
            f"audits/{BOOTS_SLUG}/buyer_questions.csv": False,
            f"reports/{BOOTS_SLUG}/audit_report.md": False,
        }
        for path, ignored in expected.items():
            with self.subTest(path=path):
                completed = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True)
                self.assertEqual(completed.returncode, 0 if ignored else 1, completed.stderr)

    def test_rule_follows_boots_exceptions(self) -> None:
        lines = [line.strip() for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
        self.assertIn("audits/*/raw_responses/", lines)
        self.assertGreater(lines.index("audits/*/raw_responses/"), lines.index(f"!audits/{BOOTS_SLUG}/**"))


class StaticSourceTests(unittest.TestCase):
    def test_no_client_literals(self) -> None:
        source = Path(sba.__file__).read_text(encoding="utf-8")
        for marker in ["Boots", "Superdrug", "Amazon", "Holland & Barrett", "United Kingdom", "Health & Beauty",
                       BOOTS_SLUG]:
            self.assertNotIn(marker, source)

    def test_module_integrity_check_is_not_an_assert(self) -> None:
        source = Path(sba.__file__).read_text(encoding="utf-8")
        self.assertNotIn("\nassert ", source)
        sba._check_evidence_fields()  # passes for the real module
        with patch("run_structured_batch_audit.EVIDENCE_FIELDS", EVIDENCE_FIELDS[:-1]):
            with self.assertRaises(RuntimeError):
                sba._check_evidence_fields()


# ==========================================================================
# Checkpoint B - the structured batch
# ==========================================================================

CREATION_DATA = {
    "slug": CONFIG.slug,
    "brand": CONFIG.brand,
    "company_name": CONFIG.company_name,
    "report_subject": CONFIG.report_subject,
    "market": CONFIG.market,
    "category": CONFIG.category,
    "competitors": list(CONFIG.competitors),
    "question_library": CONFIG.question_library,
}


def fake_answer(prompt: str) -> str:
    """A deterministic answer, well over 500 characters, naming the brand."""
    return f"For the question {prompt!r}: Lumière leads, ahead of Brewvale.\n" + "Supporting detail; " * 40


class _BatchTestCase(_SafeTestCase):
    """A fictional audit created with v2.2's create_audit_workspace in a
    temporary project root; both Gemini paths are faked."""

    def setUp(self) -> None:
        super().setUp()
        self.audits = self.tmp / "audits"
        self.audits.mkdir(exist_ok=True)
        created = create_audit.create_audit_workspace(
            CREATION_DATA, audits_dir=self.audits, reports_dir=self.tmp / "reports"
        )
        self.config = created.config
        self.questions_path = str(created.questions_file)
        self.results_path = str(created.results_file)
        self.evidence_dir = evidence_dir_for(self.results_path)
        self.questions = load_questions(self.questions_path)
        self.ids = [q["question_id"] for q in self.questions]
        self.by_text = {q["question"]: q["question_id"] for q in self.questions}

        answer = patch("run_batch_audit.generate_response", side_effect=self.answer)
        analysis = patch("response_analyzer.generate_response", side_effect=self.analysis)
        self.mock_answer = answer.start()
        self.mock_analysis = analysis.start()
        self.addCleanup(answer.stop)
        self.addCleanup(analysis.stop)
        self.answer_failures: dict[str, BaseException] = {}
        self.analysis_failures: dict[str, object] = {}

    # Fakes: a question can be made to fail by ID.
    def answer(self, prompt: str) -> str:
        question_id = self.by_text[prompt]
        if question_id in self.answer_failures:
            raise self.answer_failures[question_id]
        return fake_answer(prompt)

    def analysis(self, prompt: str) -> str:
        question_id = next(qid for text, qid in self.by_text.items() if repr(text) in prompt)
        failure = self.analysis_failures.get(question_id)
        if isinstance(failure, BaseException):
            raise failure
        if isinstance(failure, str):
            return failure
        return analysis_json()

    def run_batch(self, limit=None, delay=0, sleep=None, today=FIXED_DAY):
        with redirect_stdout(io.StringIO()) as out:
            result = run_structured_batch_audit(
                self.questions_path, self.results_path, delay, limit,
                sleep_fn=sleep or RecordingSleep(), audit_config=self.config, today=lambda: today,
            )
        self.output = out.getvalue()
        return result

    def rows(self) -> list[dict[str, str]]:
        return load_existing_results(self.results_path)

    def evidence_ids(self) -> list[str]:
        if not self.evidence_dir.exists():
            return []
        return sorted(p.name.split("__")[0] for p in self.evidence_dir.glob("*__gemini.json"))

    def state_snapshot(self) -> dict[str, bytes]:
        files = [Path(self.results_path), *sorted(self.evidence_dir.glob("*"))] if self.evidence_dir.exists() \
            else [Path(self.results_path)]
        return {str(p): p.read_bytes() for p in files}

    def reset_calls(self) -> None:
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()


class BatchFullRunTests(_BatchTestCase):
    def test_full_40_question_run_then_idempotent_rerun(self) -> None:
        result = self.run_batch()

        self.assertEqual(self.mock_answer.call_count, 40)
        self.assertEqual(self.mock_analysis.call_count, 40)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.completed_new_answers, self.ids)
        rows = self.rows()
        self.assertEqual(len(rows), 40)
        self.assertEqual([r["question_id"] for r in rows], self.ids)  # question-file order
        self.assertEqual(self.ids[:3], ["PA01", "PA02", "PA03"])
        self.assertEqual(self.ids[-1], "PD08")
        for question, row in zip(self.questions, rows):
            self.assertTrue(is_structurally_complete(row, question), row["question_id"])
            self.assertEqual(row["run_date"], "2026-09-26")
        self.assertEqual(self.evidence_ids(), sorted(self.ids))
        for question in self.questions:
            evidence = load_evidence(evidence_path(self.evidence_dir, question["question_id"]),
                                     audit_slug=self.config.slug, question_row=question)
            self.assertEqual(evidence.raw_response_text, fake_answer(question["question"]))
        states = {classify_question(q, rows, evidence_dir=self.evidence_dir, audit_slug=self.config.slug).state
                  for q in self.questions}
        self.assertEqual(states, {STATE_COMPLETE_WITH_EVIDENCE})

        before = self.state_snapshot()
        self.reset_calls()
        with patch("run_structured_batch_audit.write_results_atomically") as mock_write, \
                patch("run_structured_batch_audit.publish_evidence") as mock_publish:
            rerun = self.run_batch()
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()
        mock_write.assert_not_called()
        mock_publish.assert_not_called()
        self.assertEqual(self.state_snapshot(), before)
        self.assertEqual(rerun.attempted, [])
        self.assertEqual(rerun.exit_code, 0)
        self.assertEqual(len(rerun.ids_in(STATE_COMPLETE_WITH_EVIDENCE)), 40)

    def test_rows_are_saved_one_at_a_time(self) -> None:
        saved_counts = []
        real_write = write_single_audit_result.write_results_atomically

        def spy(path, rows):
            saved_counts.append(len(rows))
            real_write(path, rows)

        with patch("run_structured_batch_audit.write_results_atomically", side_effect=spy):
            self.run_batch(limit=3)
        self.assertEqual(saved_counts, [1, 2, 3])


class BatchLimitAndDelayTests(_BatchTestCase):
    def test_limit_sequence(self) -> None:
        before = self.state_snapshot()
        zero = self.run_batch(limit=0)
        self.assertEqual(zero.attempted, [])
        self.assertEqual(self.state_snapshot(), before)
        self.assertFalse(self.evidence_dir.exists())
        self.mock_answer.assert_not_called()

        self.assertEqual(self.run_batch(limit=1).completed, ["PA01"])
        self.assertEqual(self.run_batch(limit=5).completed, ["PA02", "PA03", "PA04", "PA05", "PA06"])
        rest = self.run_batch()
        self.assertEqual(len(rest.completed), 34)
        self.assertEqual(rest.completed[0], "PA07")

        rows = self.rows()
        self.assertEqual([r["question_id"] for r in rows], self.ids)
        self.assertEqual(len({r["question_id"] for r in rows}), 40)
        self.assertEqual(self.mock_answer.call_count, 40)

    def test_limit_counts_failures_and_skips_completed(self) -> None:
        self.run_batch(limit=2)
        self.answer_failures["PA03"] = GeminiClientError("Gemini API call failed: 401 UNAUTHENTICATED")
        result = self.run_batch(limit=2)
        self.assertEqual(result.attempted, ["PA03", "PA04"])
        self.assertEqual(result.completed, ["PA04"])
        self.assertEqual(result.pending_after, 40 - 3)

    def test_delay_only_between_attempted_questions(self) -> None:
        sleep = RecordingSleep()
        self.run_batch(limit=3, delay=2.5, sleep=sleep)
        self.assertEqual(sleep.calls, [2.5, 2.5])
        sleep_one = RecordingSleep()
        self.run_batch(limit=1, delay=2.5, sleep=sleep_one)
        self.assertEqual(sleep_one.calls, [])

    def test_negative_limit_and_delay_rejected_before_work(self) -> None:
        for kwargs in ({"limit": -1}, {"delay": -0.5}):
            with self.subTest(**kwargs):
                with self.assertRaises(StructuredBatchError):
                    self.run_batch(**kwargs)
        self.mock_answer.assert_not_called()


class BatchPreflightTests(_BatchTestCase):
    def write_questions(self, mutate) -> None:
        rows = [dict(q) for q in self.questions]
        mutate(rows)
        with open(self.questions_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def assert_preflight_fails(self, exc_type) -> None:
        before = self.state_snapshot()
        with self.assertRaises(exc_type):
            self.run_batch()
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()
        self.assertEqual(self.state_snapshot(), before)
        self.assertFalse(self.evidence_dir.exists())

    def test_unsafe_question_id(self) -> None:
        self.write_questions(lambda rows: rows[5].update(question_id="../SD01"))
        self.assert_preflight_fails(QuestionProcessingError)

    def test_case_colliding_question_ids(self) -> None:
        self.write_questions(lambda rows: rows[1].update(question_id="pa01"))
        self.assert_preflight_fails(QuestionProcessingError)

    def test_duplicate_gemini_rows(self) -> None:
        row = complete_row(question_id="PA01", question=self.questions[0]["question"],
                           funnel_stage="Problem Awareness")
        write_single_audit_result.write_results_atomically(self.results_path, [row, row])
        self.assert_preflight_fails(StructuredBatchError)

    def test_missing_or_invalid_files(self) -> None:
        os.remove(self.questions_path)
        self.assert_preflight_fails(AuditRunnerError)
        shutil.copy(REPO_ROOT / "questions" / "buyer_questions_master.csv", self.questions_path)
        Path(self.results_path).write_text("wrong,header\n", encoding="utf-8")
        self.assert_preflight_fails(WriteAuditResultError)


class BatchResumeTests(_BatchTestCase):
    def test_stop_after_ten_then_restart(self) -> None:
        self.run_batch(limit=10)
        self.reset_calls()
        result = self.run_batch()
        self.assertEqual(result.attempted, self.ids[10:])
        self.assertEqual(self.mock_answer.call_count, 30)
        prompts = [c.args[0] for c in self.mock_answer.call_args_list]
        self.assertFalse(any(self.by_text[p] in self.ids[:10] for p in prompts))
        self.assertEqual(len(self.rows()), 40)

    def test_analysis_failure_resumes_from_evidence(self) -> None:
        self.analysis_failures["PA02"] = GeminiClientError("Gemini API call failed: 400 INVALID_ARGUMENT")
        first = self.run_batch(limit=3)
        self.assertEqual([qid for qid, _ in first.failed], ["PA02"])
        self.assertEqual(first.completed, ["PA01", "PA03"])
        self.assertEqual(first.exit_code, 1)
        self.assertIn("PA02", self.evidence_ids())
        self.assertNotIn("PA02", [r["question_id"] for r in self.rows()])
        stored = evidence_path(self.evidence_dir, "PA02").read_bytes()

        del self.analysis_failures["PA02"]
        self.reset_calls()
        second = self.run_batch(limit=1)
        self.assertEqual(second.completed_from_stored, ["PA02"])
        self.mock_answer.assert_not_called()
        self.assertEqual(self.mock_analysis.call_count, 1)
        self.assertEqual(evidence_path(self.evidence_dir, "PA02").read_bytes(), stored)
        self.assertIn("PA02", [r["question_id"] for r in self.rows()])

    def test_completed_question_never_reprocessed(self) -> None:
        self.run_batch(limit=1)
        self.reset_calls()
        self.run_batch(limit=1)
        prompts = [c.args[0] for c in self.mock_answer.call_args_list]
        self.assertEqual([self.by_text[p] for p in prompts], ["PA02"])

    def test_integrity_problem_reported_skipped_and_untouched(self) -> None:
        bad = evidence_path(self.evidence_dir, "PA01")
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{malformed", encoding="utf-8")
        result = self.run_batch(limit=2)
        self.assertEqual(result.ids_in(STATE_EVIDENCE_INTEGRITY_ERROR), ["PA01"])
        self.assertEqual(result.attempted, ["PA02", "PA03"])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(bad.read_text(encoding="utf-8"), "{malformed")
        self.assertNotIn(self.questions[0]["question"], [c.args[0] for c in self.mock_answer.call_args_list])
        self.assertIn("Evidence integrity problems (F): 1 - PA01", self.output)


class BatchFailureTests(_BatchTestCase):
    def test_question_failures_continue(self) -> None:
        self.answer_failures["PA02"] = GeminiClientError("Gemini API call failed: 403 PERMISSION_DENIED")
        self.analysis_failures["PA03"] = '{"not": "the expected shape"}'
        result = self.run_batch(limit=6)

        self.assertEqual([qid for qid, _ in result.failed], ["PA02", "PA03"])
        self.assertEqual(result.completed, ["PA01", "PA04", "PA05", "PA06"])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual([r["question_id"] for r in self.rows()], ["PA01", "PA04", "PA05", "PA06"])
        self.assertNotIn("PA02", self.evidence_ids())
        self.assertIn("PA03", self.evidence_ids())
        self.assertIn("Failed this run: 2 - PA02, PA03", self.output)

        self.answer_failures.clear()
        self.analysis_failures.clear()
        self.reset_calls()
        retry = self.run_batch(limit=2)
        self.assertEqual(retry.attempted, ["PA02", "PA03"])
        self.assertEqual(retry.completed_new_answers, ["PA02"])
        self.assertEqual(retry.completed_from_stored, ["PA03"])
        self.assertEqual(self.mock_answer.call_count, 1)
        self.assertEqual(self.mock_analysis.call_count, 2)

    def test_results_write_failure_stops_and_resumes_from_evidence(self) -> None:
        real_write = write_single_audit_result.write_results_atomically
        calls = {"n": 0}

        def failing_write(path, rows):
            calls["n"] += 1
            if calls["n"] == 4:
                raise OSError("disk full")
            real_write(path, rows)

        with patch("run_structured_batch_audit.write_results_atomically", side_effect=failing_write):
            result = self.run_batch()
        self.assertIn("disk full", result.stopped)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.attempted, ["PA01", "PA02", "PA03", "PA04"])
        self.assertEqual([r["question_id"] for r in self.rows()], ["PA01", "PA02", "PA03"])
        self.assertEqual(self.evidence_ids(), ["PA01", "PA02", "PA03", "PA04"])  # PA05+ untouched
        stored = evidence_path(self.evidence_dir, "PA04").read_bytes()

        self.reset_calls()
        restart = self.run_batch(limit=2)
        self.assertEqual(restart.completed_from_stored, ["PA04"])
        self.assertEqual(restart.completed_new_answers, ["PA05"])
        self.assertEqual([self.by_text[c.args[0]] for c in self.mock_answer.call_args_list], ["PA05"])
        self.assertEqual(evidence_path(self.evidence_dir, "PA04").read_bytes(), stored)

    def test_evidence_storage_failure_stops(self) -> None:
        self.run_batch(limit=2)
        with patch("run_structured_batch_audit.os.link", side_effect=OSError("hard links not supported")):
            result = self.run_batch()
        self.assertIn("hard links", result.stopped)
        self.assertEqual(result.attempted, ["PA03"])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.evidence_ids(), ["PA01", "PA02"])

    def test_external_change_to_results_file_stops_without_duplicate(self) -> None:
        self.run_batch(limit=1)
        real_process = sba.process_question

        def process_while_another_writer_saves(question_row, *args, **kwargs):
            row = real_process(question_row, *args, **kwargs)
            other = dict(row)  # another process saves the same question first
            write_single_audit_result.write_results_atomically(self.results_path, self.rows() + [other])
            return row

        with patch("run_structured_batch_audit.process_question", side_effect=process_while_another_writer_saves):
            result = self.run_batch(limit=3)
        self.assertIn("changed during the run", result.stopped)
        self.assertEqual(result.attempted, ["PA02"])
        ids = [r["question_id"] for r in self.rows()]
        self.assertEqual(ids, ["PA01", "PA02"])  # only the other writer's row; no duplicate from this run

    def test_evidence_collision_during_run_stops(self) -> None:
        original = serialise_evidence(make_evidence(audit_slug=self.config.slug, question_id="PA01",
                                                    question=self.questions[0]["question"],
                                                    raw_response_text="Concurrent answer."))

        def answer_and_collide(prompt: str) -> str:
            path = evidence_path(self.evidence_dir, self.by_text[prompt])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(original, encoding="utf-8")
            return fake_answer(prompt)

        self.mock_answer.side_effect = answer_and_collide
        result = self.run_batch(limit=3)
        self.assertIn("will not be overwritten", result.stopped)
        self.assertEqual(result.attempted, ["PA01"])
        self.assertEqual(evidence_path(self.evidence_dir, "PA01").read_text(encoding="utf-8"), original)
        self.assertEqual(self.rows(), [])


class BatchInterruptTests(_BatchTestCase):
    def test_interrupt_before_evidence(self) -> None:
        self.run_batch(limit=3)
        self.answer_failures["PA04"] = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_batch()
        self.assertEqual(len(self.rows()), 3)
        self.assertNotIn("PA04", self.evidence_ids())
        del self.answer_failures["PA04"]
        self.reset_calls()
        restart = self.run_batch(limit=1)
        self.assertEqual(restart.completed_new_answers, ["PA04"])

    def test_interrupt_after_evidence_before_row(self) -> None:
        self.run_batch(limit=3)
        self.analysis_failures["PA04"] = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_batch()
        self.assertEqual([r["question_id"] for r in self.rows()], ["PA01", "PA02", "PA03"])
        self.assertIn("PA04", self.evidence_ids())
        del self.analysis_failures["PA04"]
        self.reset_calls()
        restart = self.run_batch(limit=1)
        self.assertEqual(restart.completed_from_stored, ["PA04"])
        self.mock_answer.assert_not_called()


class BootsCopyHistoricalPolicyTests(_SafeTestCase):
    """Runs against a COPY of the Boots workspace, never the committed one."""

    def setUp(self) -> None:
        super().setUp()
        self.audit_dir = self.tmp / "audits" / BOOTS_SLUG
        shutil.copytree(BOOTS_AUDIT_DIR, self.audit_dir)
        self.results_path = str(self.audit_dir / "audit_results.csv")
        self.original_bytes = Path(self.results_path).read_bytes()
        self.config = sba.load_audit_config(BOOTS_SLUG, audits_dir=self.tmp / "audits")
        answer = patch("run_batch_audit.generate_response", side_effect=fake_answer)
        analysis = patch("response_analyzer.generate_response", return_value=analysis_json(
            brand_cited="Y", competitors_cited=[], sources_cited=[], sentiment="Neutral"))
        self.mock_answer = answer.start()
        self.mock_analysis = analysis.start()
        self.addCleanup(answer.stop)
        self.addCleanup(analysis.stop)

    def test_limit_one_processes_only_pa06(self) -> None:
        with redirect_stdout(io.StringIO()):
            result = run_structured_batch_audit(
                str(self.audit_dir / "buyer_questions.csv"), self.results_path, 0, 1,
                sleep_fn=RecordingSleep(), audit_config=self.config, today=lambda: FIXED_DAY,
            )
        self.assertEqual(result.ids_in(STATE_LEGACY_INCOMPLETE), ["PA01", "PA02", "PA03"])
        self.assertEqual(result.ids_in(STATE_LEGACY_COMPLETE_NO_EVIDENCE), ["PA04", "PA05"])
        self.assertEqual(len(result.ids_in(STATE_NOT_STARTED)), 35)
        self.assertEqual(result.attempted, ["PA06"])
        self.assertEqual(result.exit_code, 0)  # legacy D/E alone do not fail the run

        questions = {q["question_id"]: q["question"] for q in load_questions(str(self.audit_dir / "buyer_questions.csv"))}
        self.mock_answer.assert_called_once_with(questions["PA06"])
        self.assertEqual(self.mock_analysis.call_count, 1)

        new_bytes = Path(self.results_path).read_bytes()
        self.assertTrue(new_bytes.startswith(self.original_bytes), "historical rows were rewritten")
        rows = load_existing_results(self.results_path)
        self.assertEqual(len(rows), 11)
        self.assertEqual(rows[-1]["question_id"], "PA06")
        self.assertEqual(sorted(p.name for p in (self.audit_dir / "raw_responses").iterdir()), ["PA06__gemini.json"])


class EndToEndChainTests(_BatchTestCase):
    def test_create_then_batch_then_existing_reports(self) -> None:
        result = self.run_batch()
        self.assertEqual(len(result.completed), 40)

        report_path = self.tmp / "reports" / self.config.slug / "audit_report.md"
        markdown = generate_report(self.questions_path, self.results_path, str(report_path), FIXED_DAY,
                                   audit_config=self.config)
        self.assertIn("covering 40 of the 40 questions", markdown)
        self.assertIn("- Y (Lumière cited): 40", markdown)
        self.assertIn("- Brand citation rate: 100.0%", markdown)
        self.assertIn("- Positive: 40", markdown)
        self.assertIn("- Brewvale: 40", markdown)

        findings, findings_md = generate_geo_findings(
            self.questions_path, self.results_path, str(self.tmp / "reports" / self.config.slug / "GEO_FINDINGS.md"),
            FIXED_DAY, audit_config=self.config,
        )
        self.assertEqual(len(findings), 7)
        by_title = {f.title: f for f in findings}
        self.assertIn("40 of 40 buyer questions", by_title["Overall AI Search Visibility"].value)
        self.assertIn("5 of 5 buyer journey stages", by_title["Content Coverage Observations"].value)
        self.assertIn("'Established'", by_title["Overall GEO Maturity Assessment"].value)

        # Complete-coverage wording (v2.3 Checkpoint C).
        self.assertTrue(gemini_coverage_complete(self.rows(), self.questions))
        self.assertIn("Structured Gemini results are recorded for all 40 questions", markdown)
        self.assertIn("- Structured Gemini results are recorded for all 40 buyer questions.", markdown)
        self.assertIn("40 row(s) were generated programmatically via Gemini.", markdown)
        for stale in ("partial", "Not all", "Complete the remaining", "Perplexity", "manually recorded"):
            self.assertNotIn(stale, markdown)
        self.assertIn("with a structured Gemini result for every question", findings_md)
        self.assertNotIn("partial", findings_md)
        self.assertNotIn("Perplexity", findings_md)


class ReportCoverageWordingTests(_BatchTestCase):
    """The partial/complete report wording follows structured Gemini
    coverage, not merely the presence of rows."""

    def reports(self) -> tuple[str, str]:
        out = self.tmp / "reports" / self.config.slug
        markdown = generate_report(self.questions_path, self.results_path, str(out / "audit_report.md"), FIXED_DAY,
                                   audit_config=self.config)
        _, findings_md = generate_geo_findings(self.questions_path, self.results_path, str(out / "GEO_FINDINGS.md"),
                                               FIXED_DAY, audit_config=self.config)
        return markdown, findings_md

    def assert_partial(self, markdown: str, findings_md: str) -> None:
        self.assertIn("This dataset is partial: it does not yet cover the full question library", markdown)
        self.assertIn("- This is a partial audit dataset.", markdown)
        self.assertIn("- Not all 40 buyer questions have Gemini results yet.", markdown)
        self.assertIn("Complete the remaining structured Gemini audit questions", markdown)
        self.assertIn("buyer questions — a partial dataset.", findings_md)

    def test_partial_gemini_only_run_keeps_partial_wording_without_perplexity(self) -> None:
        self.run_batch(limit=10)
        self.assertFalse(gemini_coverage_complete(self.rows(), self.questions))
        markdown, findings_md = self.reports()
        self.assert_partial(markdown, findings_md)
        self.assertNotIn("Perplexity", markdown)
        self.assertIn("10 row(s) were generated programmatically via Gemini.", markdown)
        self.assertIn("- Gemini rows were generated programmatically.", markdown)

    def test_one_raw_only_gemini_row_keeps_the_dataset_partial(self) -> None:
        self.run_batch()
        rows = self.rows()
        rows[-1] = {**rows[-1], "brand_cited": "", "brand_position": "", "competitors_cited": "",
                    "sources_cited": "", "sentiment": ""}  # a legacy answer-only row for PD08
        write_single_audit_result.write_results_atomically(self.results_path, rows)
        self.assertFalse(gemini_coverage_complete(self.rows(), self.questions))
        self.assert_partial(*self.reports())

    def test_perplexity_rows_do_not_count_towards_gemini_coverage(self) -> None:
        self.run_batch(limit=39)
        rows = self.rows()
        missing = self.questions[-1]
        perplexity = complete_row(question_id=missing["question_id"], question=missing["question"],
                                  funnel_stage=missing["buyer_journey_stage"], engine="Perplexity",
                                  run_date="2026-09-26")
        write_single_audit_result.write_results_atomically(self.results_path, rows + [perplexity])
        self.assertFalse(gemini_coverage_complete(self.rows(), self.questions))
        markdown, findings_md = self.reports()
        self.assert_partial(markdown, findings_md)
        self.assertIn("1 row(s) were manually recorded via Perplexity and 39 row(s)", markdown)
        self.assertIn("- Perplexity rows were manually recorded.", markdown)

    def test_without_question_rows_the_report_stays_partial(self) -> None:
        self.run_batch()
        from report_generator import generate_report_markdown
        markdown = generate_report_markdown(self.rows(), FIXED_DAY, 40, audit_config=self.config)
        self.assertIn("This dataset is partial", markdown)
        self.assertFalse(gemini_coverage_complete(self.rows(), []))


class CliTests(_BatchTestCase):
    def setUp(self) -> None:
        super().setUp()
        p = patch("audit_config.AUDITS_DIR", self.audits)
        p.start()
        self.addCleanup(p.stop)
        original_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, original_cwd)
        sleep = patch("run_structured_batch_audit.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sba.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_audit_flag_limit_and_startup_context(self) -> None:
        code, out, err = self.cli(["--audit", self.config.slug, "--limit", "2", "--delay", "0"])
        self.assertEqual(code, 0, err)
        self.assertIn(f"Audit: {self.config.slug} (Lumière & Fils Ltd)", out)
        self.assertIn(f"Questions: audits/{self.config.slug}/buyer_questions.csv", out)
        self.assertIn(f"Results: audits/{self.config.slug}/audit_results.csv", out)
        self.assertIn("Total questions: 40", out)
        self.assertIn("Needing work (A/B): 40; attempting 2 (limit 2)", out)
        self.assertIn("Completed this run: 2", out)
        self.assertNotIn("Supporting detail", out)  # raw answers are never printed
        self.assertEqual(len(self.rows()), 2)

    def test_explicit_paths_override_audit_paths(self) -> None:
        other_results = self.tmp / "elsewhere" / "audit_results.csv"
        other_results.parent.mkdir()
        write_single_audit_result.write_results_atomically(str(other_results), [])
        code, _, err = self.cli(["--audit", self.config.slug, "--results", str(other_results), "--limit", "1",
                                 "--delay", "0"])
        self.assertEqual(code, 0, err)
        self.assertEqual(len(load_existing_results(str(other_results))), 1)
        self.assertTrue((other_results.parent / "raw_responses" / "PA01__gemini.json").is_file())
        self.assertEqual(self.rows(), [])

    def test_failures_give_exit_1(self) -> None:
        self.answer_failures["PA01"] = GeminiClientError("Gemini API call failed: 403 PERMISSION_DENIED")
        code, out, _ = self.cli(["--audit", self.config.slug, "--limit", "1", "--delay", "0"])
        self.assertEqual(code, 1)
        self.assertIn("Failed this run: 1 - PA01", out)

    def test_preflight_and_argument_errors(self) -> None:
        for argv in (["--audit", "no-such-client"], ["--audit", self.config.slug, "--limit", "-1"],
                     ["--audit", self.config.slug, "--delay", "-1"]):
            with self.subTest(argv=argv):
                code, _, err = self.cli(argv)
                self.assertEqual(code, 1)
                self.assertTrue(err.startswith("Error: "), err)
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                sba.main(["--limit", "many"])
        self.assertEqual(ctx.exception.code, 2)
        self.mock_answer.assert_not_called()

    def test_no_unsupported_flags(self) -> None:
        for flag in ("--force", "--reprocess", "--parallel", "--provider"):
            with self.subTest(flag=flag):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        sba.main([flag])


if __name__ == "__main__":
    unittest.main()
