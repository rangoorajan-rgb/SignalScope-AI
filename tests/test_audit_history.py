"""Tests for src/audit_history.py - v2.4: immutable audit snapshots and
read-only listing (Checkpoint A), new runs (B) and comparison of two
snapshots (C).

Every audit is fictional, created with v2.2's create_audit_workspace in a
temporary directory, and its evidence is collected with the real v2.3
structured batch with both Gemini paths faked (the SDK is blocked). The
real audits/, reports/ and master template are verified unchanged after
every test, and no snapshots/ folder may appear under the real audits/.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import audit_history  # noqa: E402
import create_audit  # noqa: E402
import measurement_engine  # noqa: E402
from audit_history import (  # noqa: E402
    MANIFEST_FIELDS,
    MANIFEST_FILENAME,
    AuditHistoryError,
    SnapshotIntegrityError,
    build_hash_map,
    create_snapshot,
    created_at_for,
    hash_file,
    inspect_snapshot,
    list_snapshots,
    parse_run_id,
    run_id_for,
    verify_hash_map,
)
from audit_history import (  # noqa: E402
    STATE_COMPLETE,
    STATE_FRESH,
    STATE_IN_PROGRESS,
    STATE_RESET_INTERRUPTED,
    STATE_SNAPSHOTTED,
    active_run_state,
    start_new_run,
)
from audit_history import NotComparableError, compare_snapshots  # noqa: E402
from audit_history import SnapshotComparison, compute_snapshot_comparison  # noqa: E402
from report_generator import compute_brand_visibility  # noqa: E402
from run_structured_batch_audit import (  # noqa: E402
    STATE_NOT_STARTED,
    classify_question,
    evidence_path,
    run_structured_batch_audit,
)
from write_single_audit_result import RESULTS_SCHEMA  # noqa: E402
from version import SIGNALSCOPE_VERSION  # noqa: E402
from write_single_audit_result import load_existing_results  # noqa: E402

SLUG = "lumiere-veloria-tea"
BOOTS_SLUG = "boots-uk-health-beauty"
T1 = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(hours=1)
T3 = T1 + timedelta(days=30)
RUN_1 = "20261001T090000Z"
RUN_2 = "20261001T100000Z"

CREATION_DATA = {
    "slug": SLUG,
    "brand": "Lumière",
    "company_name": "Lumière & Fils Ltd",
    "report_subject": "Lumière & Fils Specialty Tea",
    "market": "Republic of Veloria",
    "category": "Specialty Tea Retail",
    "competitors": ["Brewvale", "O'Kettle & Co", "Steepwisé"],
    "question_library": "Veloria Tea GEO Library",
}

ANALYSIS_JSON = json.dumps({
    "brand_cited": "Y", "brand_position": 1, "competitors_cited": ["Brewvale"],
    "sources_cited": ["Leaf Journal"], "sentiment": "Positive",
})


def fake_answer(prompt: str) -> str:
    return f"For the question {prompt!r}: Lumière leads, ahead of Brewvale.\n" + "Supporting detail; " * 40


def tree(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


def production_snapshot() -> dict[str, bytes | None]:
    paths = [REPO_ROOT / "questions" / "buyer_questions_master.csv",
             *(REPO_ROOT / "audits").rglob("*"), *(REPO_ROOT / "reports").rglob("*")]
    return {str(p): (p.read_bytes() if p.is_file() else None) for p in sorted(paths)}


class _HistoryTestCase(unittest.TestCase):
    """A fictional audit in a temporary project root, Gemini fully faked."""

    def setUp(self) -> None:
        guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini call attempted"))
        guard.start()
        self.addCleanup(guard.stop)
        before = production_snapshot()

        def check() -> None:
            self.assertEqual(production_snapshot(), before, "production audits/reports/template changed")
            self.assertEqual(list((REPO_ROOT / "audits").glob("*/snapshots")), [])

        self.addCleanup(check)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.audits = self.root / "audits"
        self.audits.mkdir()
        created = create_audit.create_audit_workspace(
            CREATION_DATA, audits_dir=self.audits, reports_dir=self.root / "reports"
        )
        self.audit_dir = created.audit_dir
        self.config = created.config
        self.questions_path = str(created.questions_file)
        self.results_path = str(created.results_file)
        self.evidence_dir = self.audit_dir / "raw_responses"
        self.snapshots_dir = self.audit_dir / "snapshots"

        from audit_runner import load_questions
        self.questions = load_questions(self.questions_path)
        self.by_text = {q["question"]: q["question_id"] for q in self.questions}
        self.failing_analysis: set[str] = set()
        answer = patch("run_batch_audit.generate_response", side_effect=fake_answer)
        analysis = patch("response_analyzer.generate_response", side_effect=self._analysis)
        self.mock_answer = answer.start()
        self.mock_analysis = analysis.start()
        self.addCleanup(answer.stop)
        self.addCleanup(analysis.stop)

    def _analysis(self, prompt: str) -> str:
        question_id = next(qid for text, qid in self.by_text.items() if repr(text) in prompt)
        if question_id in self.failing_analysis:
            return '{"malformed": true}'
        return ANALYSIS_JSON

    def collect(self, limit=None) -> None:
        with redirect_stdout(io.StringIO()):
            run_structured_batch_audit(self.questions_path, self.results_path, 0, limit,
                                       sleep_fn=lambda s: None, audit_config=self.config)

    def snapshot(self, when=T1, allow_partial=False):
        return create_snapshot(SLUG, audits_dir=self.audits, allow_partial=allow_partial, now=lambda: when)

    def active_tree(self) -> dict[str, bytes | None]:
        return {k: v for k, v in tree(self.audit_dir).items() if not k.startswith("snapshots")}

    def staging_dirs(self) -> list[str]:
        return [p.name for p in self.snapshots_dir.iterdir() if p.name.startswith(".")] \
            if self.snapshots_dir.exists() else []


# --------------------------------------------------------------------------
# Run IDs and hashes
# --------------------------------------------------------------------------


class RunIdTests(unittest.TestCase):
    def test_run_id_is_utc_sortable_and_filename_safe(self) -> None:
        self.assertEqual(run_id_for(T1), RUN_1)
        plus_two = T1.astimezone(timezone(timedelta(hours=2)))
        self.assertEqual(run_id_for(plus_two), RUN_1)
        self.assertLess(run_id_for(T1), run_id_for(T2))
        self.assertEqual(created_at_for(RUN_1), "2026-10-01T09:00:00Z")
        self.assertEqual(parse_run_id(RUN_1), T1)

    def test_naive_time_rejected(self) -> None:
        with self.assertRaises(AuditHistoryError):
            run_id_for(datetime(2026, 10, 1, 9, 0, 0))

    def test_invalid_run_ids_rejected(self) -> None:
        for bad in ["2026-10-01", "20261001T090000", "20261001T090000z", " 20261001T090000Z", "../20261001T090000Z",
                    "20261001T090000Z/x", "20261301T090000Z", "20260230T090000Z", "baseline", "", None, 20261001]:
            with self.subTest(run_id=bad):
                with self.assertRaises(AuditHistoryError):
                    parse_run_id(bad)


class HashTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "a.txt").write_bytes(b"abc")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "b.txt").write_bytes(b"xyz")
        self.files = build_hash_map(self.root, ["sub/b.txt", "a.txt"])

    def test_hash_file_and_map(self) -> None:
        self.assertEqual(hash_file(self.root / "a.txt"), hashlib.sha256(b"abc").hexdigest())
        self.assertEqual(list(self.files), ["a.txt", "sub/b.txt"])
        self.assertEqual(verify_hash_map(self.root, self.files), [])

    def test_verification_detects_problems(self) -> None:
        cases = {
            "modified": (lambda: (self.root / "a.txt").write_bytes(b"abd"), self.files, "modified file a.txt"),
            "missing": (lambda: (self.root / "a.txt").unlink(), self.files, "missing file a.txt"),
            "undeclared": (lambda: (self.root / "extra.txt").write_bytes(b"!"), self.files, "undeclared file extra.txt"),
        }
        for name, (mutate, files, fragment) in cases.items():
            with self.subTest(case=name):
                self.setUp()
                mutate()
                self.assertTrue(any(fragment in p for p in verify_hash_map(self.root, self.files)), name)

    def test_bad_declarations(self) -> None:
        for files, fragment in [
            ({"a.txt": "ABC"}, "invalid SHA-256"),
            ({"../a.txt": "0" * 64}, "unsafe file path"),
            ({"/etc/x": "0" * 64}, "unsafe file path"),
            ({"sub\\b.txt": "0" * 64}, "unsafe file path"),
            ({MANIFEST_FILENAME: "0" * 64}, "must not hash itself"),
            ({}, "non-empty mapping"),
            ("not a map", "non-empty mapping"),
        ]:
            with self.subTest(files=files):
                self.assertTrue(any(fragment in p for p in verify_hash_map(self.root, files)))


# --------------------------------------------------------------------------
# Complete snapshot
# --------------------------------------------------------------------------


class CompleteSnapshotTests(_HistoryTestCase):
    def test_complete_40_question_snapshot(self) -> None:
        self.collect()
        before = self.active_tree()
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()

        snapshot = self.snapshot()

        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()
        self.assertEqual(snapshot.run_id, RUN_1)
        folder = self.snapshots_dir / RUN_1
        self.assertEqual(snapshot.path, folder)
        self.assertTrue(snapshot.is_valid, snapshot.problems)
        self.assertEqual(self.active_tree(), before)  # the current run is untouched
        for name in ("audit_config.json", "buyer_questions.csv", "audit_results.csv"):
            self.assertEqual((folder / name).read_bytes(), (self.audit_dir / name).read_bytes(), name)
        evidence = sorted(p.name for p in (folder / "raw_responses").iterdir())
        self.assertEqual(len(evidence), 40)
        for name in evidence:
            self.assertEqual((folder / "raw_responses" / name).read_bytes(), (self.evidence_dir / name).read_bytes())
        self.assertEqual(self.staging_dirs(), [])

        manifest = json.loads((folder / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(list(manifest), list(MANIFEST_FIELDS))
        self.assertEqual(manifest["format_version"], 1)
        self.assertEqual(manifest["audit_slug"], SLUG)
        self.assertEqual(manifest["run_id"], RUN_1)
        self.assertEqual(manifest["created_at"], "2026-10-01T09:00:00Z")
        self.assertEqual(manifest["signalscope_version"], SIGNALSCOPE_VERSION)
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual((manifest["question_count"], manifest["structurally_complete_count"]), (40, 40))
        self.assertEqual(manifest["requested_models"], ["gemini-2.5-flash"])
        self.assertEqual(list(manifest["files"]), sorted(manifest["files"]))
        self.assertNotIn(MANIFEST_FILENAME, manifest["files"])
        self.assertEqual(len(manifest["files"]), 3 + 40 + 2)
        self.assertEqual(verify_hash_map(folder, manifest["files"]), [])
        self.assertTrue((folder / MANIFEST_FILENAME).read_text(encoding="utf-8").endswith("}\n"))

        report = (folder / "reports" / "audit_report.md").read_text(encoding="utf-8")
        findings = (folder / "reports" / "GEO_FINDINGS.md").read_text(encoding="utf-8")
        self.assertIn("Structured Gemini results are recorded for all 40 questions", report)
        self.assertIn("- Report generation date: 2026-10-01", report)
        self.assertNotIn("partial", report)
        self.assertIn("with a structured Gemini result for every question", findings)
        self.assertEqual(sorted(p.name for p in (folder / "reports").iterdir()), ["GEO_FINDINGS.md", "audit_report.md"])

    def test_reports_use_the_snapshot_copies_not_top_level_files(self) -> None:
        self.collect()
        with patch("audit_history.generate_report", wraps=audit_history.generate_report) as spy:
            self.snapshot()
        questions_arg, results_arg = spy.call_args.args[:2]
        self.assertTrue(questions_arg.startswith(str(self.snapshots_dir)))
        self.assertTrue(results_arg.startswith(str(self.snapshots_dir)))
        self.assertEqual(spy.call_args.kwargs["audit_config"], self.config)

    def test_snapshot_is_independent_of_later_active_changes(self) -> None:
        self.collect()
        self.snapshot()
        (self.audit_dir / "buyer_questions.csv").write_text("changed later\n", encoding="utf-8")
        self.assertTrue(inspect_snapshot(self.snapshots_dir / RUN_1, slug=SLUG).is_valid)


# --------------------------------------------------------------------------
# Partial snapshots and pre-flight
# --------------------------------------------------------------------------


class PartialSnapshotTests(_HistoryTestCase):
    def prepare_partial(self) -> None:
        self.collect(limit=37)
        self.failing_analysis.add(self.questions[37]["question_id"])
        self.collect(limit=1)  # question 38: answer stored, analysis failed (state B)

    def test_partial_refused_without_flag_then_allowed(self) -> None:
        self.prepare_partial()
        before = self.active_tree()
        with self.assertRaises(AuditHistoryError) as ctx:
            self.snapshot()
        self.assertIn("--allow-partial", str(ctx.exception))
        self.assertIn("37 of 40", str(ctx.exception))
        self.assertFalse(self.snapshots_dir.exists())

        snapshot = self.snapshot(allow_partial=True)
        manifest = snapshot.manifest
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual((manifest["question_count"], manifest["structurally_complete_count"]), (40, 37))
        self.assertEqual(self.active_tree(), before)
        folder = snapshot.path
        self.assertEqual((folder / "audit_results.csv").read_bytes(), Path(self.results_path).read_bytes())
        stored = evidence_path(folder / "raw_responses", self.questions[37]["question_id"])
        self.assertTrue(stored.is_file())  # the unfinished answer is preserved exactly
        self.assertEqual(len(list((folder / "raw_responses").iterdir())), 38)
        report = (folder / "reports" / "audit_report.md").read_text(encoding="utf-8")
        self.assertIn("This dataset is partial", report)
        self.assertIn("a partial dataset", (folder / "reports" / "GEO_FINDINGS.md").read_text(encoding="utf-8"))

    def test_evidence_problem_always_blocks(self) -> None:
        self.collect(limit=37)
        bad = evidence_path(self.evidence_dir, self.questions[38]["question_id"])
        bad.write_text("{malformed", encoding="utf-8")
        for allow_partial in (False, True):
            with self.subTest(allow_partial=allow_partial):
                with self.assertRaises(SnapshotIntegrityError) as ctx:
                    self.snapshot(allow_partial=allow_partial)
                self.assertIn("evidence problems", str(ctx.exception))
        self.assertFalse(self.snapshots_dir.exists())

    def test_no_complete_results_refused(self) -> None:
        for allow_partial in (False, True):
            with self.subTest(allow_partial=allow_partial):
                with self.assertRaises(AuditHistoryError):
                    self.snapshot(allow_partial=allow_partial)
        self.assertFalse(self.snapshots_dir.exists())

    def test_unexpected_evidence_files_refused(self) -> None:
        self.collect()
        (self.evidence_dir / "notes.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(SnapshotIntegrityError):
            self.snapshot()
        (self.evidence_dir / "notes.json").unlink()
        (self.evidence_dir / "nested").mkdir()
        with self.assertRaises(SnapshotIntegrityError):
            self.snapshot()

    def test_leftover_temporary_evidence_file_is_not_copied(self) -> None:
        self.collect()
        (self.evidence_dir / ".PA01__gemini.json.abc.tmp").write_text("partial", encoding="utf-8")
        snapshot = self.snapshot()
        self.assertFalse(any(p.name.startswith(".") for p in (snapshot.path / "raw_responses").iterdir()))
        self.assertTrue(snapshot.is_valid)

    def test_unknown_audit_refused(self) -> None:
        with self.assertRaises(AuditHistoryError):
            create_snapshot("no-such-audit", audits_dir=self.audits, now=lambda: T1)


# --------------------------------------------------------------------------
# Immutability and duplicates
# --------------------------------------------------------------------------


class ImmutabilityTests(_HistoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.collect(limit=10)
        self.first = self.snapshot(allow_partial=True)
        self.first_bytes = tree(self.first.path)

    def test_run_id_collision_refused(self) -> None:
        self.collect(limit=5)
        with self.assertRaises(AuditHistoryError) as ctx:
            self.snapshot(when=T1, allow_partial=True)
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual(tree(self.first.path), self.first_bytes)
        self.assertEqual(self.staging_dirs(), [])

    def test_same_content_refused_as_already_snapshotted(self) -> None:
        with self.assertRaises(AuditHistoryError) as ctx:
            self.snapshot(when=T3, allow_partial=True)
        self.assertIn(f"already snapshotted as {RUN_1}", str(ctx.exception))
        self.assertEqual(sorted(p.name for p in self.snapshots_dir.iterdir()), [RUN_1])

    def test_later_snapshot_never_changes_earlier(self) -> None:
        self.collect(limit=5)
        second = self.snapshot(when=T2, allow_partial=True)
        self.assertEqual(second.run_id, RUN_2)
        self.assertEqual(tree(self.first.path), self.first_bytes)
        self.assertTrue(inspect_snapshot(self.first.path, slug=SLUG).is_valid)
        self.assertEqual(second.manifest["structurally_complete_count"], 15)

    def assert_tampered(self, mutate, fragment: str) -> None:
        mutate(self.first.path)
        info = inspect_snapshot(self.first.path, slug=SLUG)
        self.assertFalse(info.is_valid)
        self.assertTrue(any(fragment in p for p in info.problems), info.problems)

    def rewrite_manifest(self, **changes) -> None:
        path = self.first.path / MANIFEST_FILENAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(changes)
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def test_modified_file_detected(self) -> None:
        self.assert_tampered(lambda p: (p / "audit_results.csv").write_text("tampered", encoding="utf-8"), "modified")

    def test_deleted_and_added_files_detected(self) -> None:
        self.assert_tampered(lambda p: (p / "reports" / "GEO_FINDINGS.md").unlink(), "missing file")

    def test_added_file_detected(self) -> None:
        self.assert_tampered(lambda p: (p / "reports" / "extra.md").write_text("x", encoding="utf-8"), "undeclared")

    def test_manifest_tampering_detected(self) -> None:
        for changes, fragment in [
            ({"status": "complete"}, "does not match"),
            ({"structurally_complete_count": 11}, "does not match"),
            ({"created_at": "2026-10-02T09:00:00Z"}, "created_at"),
            ({"audit_slug": "other-audit"}, "audit_slug"),
            ({"format_version": 2}, "format_version"),
            ({"requested_models": ["b", "a"]}, "requested_models"),
            ({"signalscope_version": ""}, "signalscope_version"),
        ]:
            with self.subTest(changes=changes):
                original = (self.first.path / MANIFEST_FILENAME).read_bytes()
                self.rewrite_manifest(**changes)
                info = inspect_snapshot(self.first.path, slug=SLUG)
                self.assertFalse(info.is_valid)
                self.assertTrue(any(fragment in p for p in info.problems), info.problems)
                (self.first.path / MANIFEST_FILENAME).write_bytes(original)
        self.assertTrue(inspect_snapshot(self.first.path, slug=SLUG).is_valid)

    def test_malformed_or_missing_manifest(self) -> None:
        (self.first.path / MANIFEST_FILENAME).write_text("{broken", encoding="utf-8")
        self.assertIn("cannot be read", inspect_snapshot(self.first.path, slug=SLUG).problems[0])
        (self.first.path / MANIFEST_FILENAME).unlink()
        self.assertEqual(inspect_snapshot(self.first.path, slug=SLUG).problems, ["manifest is missing"])

    def test_folder_renamed_detected(self) -> None:
        renamed = self.first.path.with_name("20261002T090000Z")
        self.first.path.rename(renamed)
        self.assertTrue(any("does not match its folder" in p
                            for p in inspect_snapshot(renamed, slug=SLUG).problems))

    def test_tampered_snapshot_is_not_trusted_for_duplicate_detection(self) -> None:
        (self.first.path / "reports" / "audit_report.md").write_text("tampered", encoding="utf-8")
        second = self.snapshot(when=T2, allow_partial=True)  # same source content, but the old copy is untrusted
        self.assertTrue(second.is_valid)
        self.assertEqual(second.manifest["structurally_complete_count"], 10)


# --------------------------------------------------------------------------
# Failure and rollback
# --------------------------------------------------------------------------


class FailureTests(_HistoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.collect(limit=10)
        self.existing = self.snapshot(when=T1, allow_partial=True)
        self.existing_bytes = tree(self.existing.path)
        self.collect(limit=5)  # new active content for a second snapshot
        self.before = self.active_tree()

    def assert_clean_failure(self, exc_type, *patchers) -> None:
        for p in patchers:
            p.start()
        try:
            with self.assertRaises(exc_type):
                self.snapshot(when=T2, allow_partial=True)
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(self.active_tree(), self.before)
        self.assertFalse((self.snapshots_dir / RUN_2).exists())
        self.assertEqual(self.staging_dirs(), [])
        self.assertEqual(tree(self.existing.path), self.existing_bytes)

    def failing_copy_on(self, name: str):
        real = shutil.copyfile

        def copy(src, dst, *args, **kwargs):
            if Path(src).name == name or (name == "raw_responses" and Path(src).parent.name == "raw_responses"):
                raise OSError(f"simulated failure copying {name}")
            return real(src, dst, *args, **kwargs)

        return patch("audit_history.shutil.copyfile", side_effect=copy)

    def test_config_copy_failure(self) -> None:
        self.assert_clean_failure(OSError, self.failing_copy_on("audit_config.json"))

    def test_questions_copy_failure(self) -> None:
        self.assert_clean_failure(OSError, self.failing_copy_on("buyer_questions.csv"))

    def test_results_copy_failure(self) -> None:
        self.assert_clean_failure(OSError, self.failing_copy_on("audit_results.csv"))

    def test_evidence_copy_failure(self) -> None:
        self.assert_clean_failure(OSError, self.failing_copy_on("raw_responses"))

    def test_report_rendering_failure(self) -> None:
        self.assert_clean_failure(OSError, patch("audit_history._render_reports", side_effect=OSError("render failed")))

    def test_manifest_write_failure(self) -> None:
        self.assert_clean_failure(
            OSError, patch("audit_history._serialise_manifest", side_effect=OSError("manifest write failed"))
        )

    def test_hash_verification_failure(self) -> None:
        self.assert_clean_failure(
            SnapshotIntegrityError, patch("audit_history.verify_hash_map", return_value=["modified file x"])
        )

    def test_final_rename_failure(self) -> None:
        self.assert_clean_failure(OSError, patch("audit_history._publish", side_effect=OSError("rename failed")))

    def test_interrupt_leaves_no_snapshot(self) -> None:
        self.assert_clean_failure(KeyboardInterrupt, patch("audit_history._publish", side_effect=KeyboardInterrupt()))

    def test_first_snapshot_failure_leaves_no_snapshots_folder(self) -> None:
        shutil.rmtree(self.snapshots_dir)
        with patch("audit_history._publish", side_effect=OSError("rename failed")):
            with self.assertRaises(OSError):
                self.snapshot(when=T2, allow_partial=True)
        self.assertFalse(self.snapshots_dir.exists())


# --------------------------------------------------------------------------
# Boots (copy only)
# --------------------------------------------------------------------------


class BootsCopyTests(_HistoryTestCase):
    def test_boots_copy_needs_allow_partial(self) -> None:
        boots_audits = self.root / "boots-copy"
        shutil.copytree(REPO_ROOT / "audits" / BOOTS_SLUG, boots_audits / BOOTS_SLUG)
        with self.assertRaises(AuditHistoryError):
            create_snapshot(BOOTS_SLUG, audits_dir=boots_audits, now=lambda: T1)

        snapshot = create_snapshot(BOOTS_SLUG, audits_dir=boots_audits, allow_partial=True, now=lambda: T1)
        manifest = snapshot.manifest
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual((manifest["question_count"], manifest["structurally_complete_count"]), (40, 2))
        self.assertEqual(manifest["requested_models"], [])  # no raw evidence in the legacy data
        self.assertNotIn("raw_responses", [p.name for p in snapshot.path.iterdir()])
        self.assertEqual((snapshot.path / "audit_results.csv").read_bytes(),
                         (REPO_ROOT / "audits" / BOOTS_SLUG / "audit_results.csv").read_bytes())
        self.assertFalse((REPO_ROOT / "audits" / BOOTS_SLUG / "snapshots").exists())


# --------------------------------------------------------------------------
# Listing and CLI
# --------------------------------------------------------------------------


class ListTests(_HistoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.collect(limit=5)
        self.snapshot(when=T1, allow_partial=True)
        with patch("gemini_client.DEFAULT_MODEL", "gemini-test-b"):
            self.collect()
        self.snapshot(when=T2)
        p = patch("audit_config.AUDITS_DIR", self.audits)
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = audit_history.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_list_snapshots_function(self) -> None:
        (self.snapshots_dir / ".creating-20261003T000000Z-x").mkdir()  # staging is never listed
        snapshots = list_snapshots(SLUG, audits_dir=self.audits)
        self.assertEqual([s.run_id for s in snapshots], [RUN_1, RUN_2])
        self.assertTrue(all(s.is_valid for s in snapshots))
        first, second = (s.manifest for s in snapshots)
        self.assertEqual((first["status"], first["structurally_complete_count"]), ("partial", 5))
        self.assertEqual((second["status"], second["structurally_complete_count"]), ("complete", 40))
        self.assertEqual(first["requested_models"], ["gemini-2.5-flash"])
        self.assertEqual(second["requested_models"], ["gemini-2.5-flash", "gemini-test-b"])

    def test_list_cli_and_tampering(self) -> None:
        before = tree(self.audit_dir)
        code, out, err = self.run_cli(["list", "--audit", SLUG])
        self.assertEqual(code, 0, err)
        lines = [line for line in out.splitlines() if line.startswith("  2026")]
        self.assertEqual([line.split()[0] for line in lines], [RUN_1, RUN_2])
        self.assertIn("partial  5/40 complete", lines[0])
        self.assertIn("complete  40/40 complete", lines[1])
        self.assertIn(f"v{SIGNALSCOPE_VERSION}  integrity: OK", lines[1])
        self.assertIn("gemini-2.5-flash, gemini-test-b", lines[1])
        self.assertIn(f"Current run: snapshotted (40/40 structurally complete) - preserved as {RUN_2}", out)
        self.assertEqual(tree(self.audit_dir), before)  # list writes nothing

        (self.snapshots_dir / RUN_1 / "audit_results.csv").write_text("tampered", encoding="utf-8")
        code, out, _ = self.run_cli(["list", "--audit", SLUG])
        self.assertEqual(code, 1)
        self.assertIn(f"{RUN_1}  INVALID - not usable as historical evidence", out)
        self.assertNotIn(f"{RUN_1}  created", out)

    def test_snapshot_cli(self) -> None:
        self.collect()  # nothing new: still identical to RUN_2
        code, _, err = self.run_cli(["snapshot", "--audit", SLUG])
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("Error: "), err)
        self.assertIn("already snapshotted", err)
        self.assertNotIn("Traceback", err)

    def test_snapshot_cli_success(self) -> None:
        shutil.rmtree(self.snapshots_dir)
        with patch("audit_history._utc_now", return_value=T3):
            code, out, err = self.run_cli(["snapshot", "--audit", SLUG])
        self.assertEqual(code, 0, err)
        self.assertIn("Snapshot 20261031T090000Z created", out)
        self.assertIn("status: complete (40/40 structurally complete)", out)

    def test_argument_errors(self) -> None:
        for argv in ([], ["snapshot"], ["list"], ["new-run"], ["compare", "--audit", SLUG],
                     ["snapshot", "--audit", SLUG, "--force"], ["new-run", "--audit", SLUG, "--force"]):
            with self.subTest(argv=argv):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        audit_history.main(argv)
                self.assertEqual(ctx.exception.code, 2)

    def test_unknown_audit_is_an_error(self) -> None:
        code, _, err = self.run_cli(["snapshot", "--audit", "no-such-audit"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown audit", err)


# --------------------------------------------------------------------------
# Governance
# --------------------------------------------------------------------------


class GitignoreSnapshotTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git") and (REPO_ROOT / ".git").exists(), "git repository not available")
    def test_snapshot_confidentiality_rules(self) -> None:
        boots = f"audits/{BOOTS_SLUG}"
        expected = {
            f"{boots}/audit_config.json": False,
            f"{boots}/audit_results.csv": False,
            f"{boots}/buyer_questions.csv": False,
            f"reports/{BOOTS_SLUG}/audit_report.md": False,
            f"reports/{BOOTS_SLUG}/GEO_PROGRESS.md": False,
            f"{boots}/raw_responses/PA01__gemini.json": True,
            f"{boots}/snapshots/{RUN_1}/audit_results.csv": True,
            f"{boots}/snapshots/{RUN_1}/raw_responses/PA01__gemini.json": True,
            f"{boots}/snapshots/{RUN_1}/snapshot_manifest.json": True,
            f"{boots}/snapshots/.creating-{RUN_1}-x/audit_results.csv": True,
            f"{boots}/some/deeper/raw_responses/PA01__gemini.json": True,
            f"reports/{BOOTS_SLUG}/comparisons/{RUN_1}__{RUN_2}/GEO_PROGRESS.md": True,
            "audits/client-x/audit_results.csv": True,
            f"audits/client-x/snapshots/{RUN_1}/raw_responses/PA01__gemini.json": True,
            "src/audit_history.py": False,
        }
        for path, ignored in expected.items():
            with self.subTest(path=path):
                completed = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True)
                self.assertEqual(completed.returncode, 0 if ignored else 1, completed.stderr)

    def test_module_has_no_client_literals(self) -> None:
        source = Path(audit_history.__file__).read_text(encoding="utf-8")
        for marker in ["Boots", "Superdrug", "Amazon", "Holland & Barrett", "United Kingdom", BOOTS_SLUG]:
            self.assertNotIn(marker, source)


# ==========================================================================
# Checkpoint B - new runs
# ==========================================================================


class _NewRunTestCase(_HistoryTestCase):
    def new_run(self):
        return start_new_run(SLUG, audits_dir=self.audits)

    def state(self) -> str:
        return active_run_state(SLUG, audits_dir=self.audits).state

    def retirement_dirs(self) -> list[Path]:
        return sorted(self.snapshots_dir.glob(".retired-raw-*")) if self.snapshots_dir.exists() else []

    def method_bytes(self) -> dict[str, bytes]:
        return {n: (self.audit_dir / n).read_bytes() for n in ("audit_config.json", "buyer_questions.csv")}

    def assert_fresh(self) -> None:
        self.assertEqual(load_existing_results(self.results_path), [])
        self.assertEqual(Path(self.results_path).read_text(encoding="utf-8").splitlines(), [",".join(RESULTS_SCHEMA)])
        self.assertFalse(self.evidence_dir.exists())
        self.assertEqual(self.retirement_dirs(), [])
        self.assertEqual(self.state(), STATE_FRESH)

    def run_cli(self, argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with patch("audit_config.AUDITS_DIR", self.audits), redirect_stdout(out), redirect_stderr(err):
            code = audit_history.main(argv)
        return code, out.getvalue(), err.getvalue()


class NewRunTests(_NewRunTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.collect()
        self.run1 = self.snapshot(when=T1)
        self.run1_bytes = tree(self.run1.path)
        self.methodology = self.method_bytes()

    def test_successful_new_run(self) -> None:
        self.assertEqual(self.state(), STATE_SNAPSHOTTED)
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        result = self.new_run()
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()
        self.assertEqual((result.preserved_run_id, result.retired_evidence_files, result.recovered), (RUN_1, 40, False))
        self.assert_fresh()
        self.assertEqual(self.method_bytes(), self.methodology)
        self.assertEqual(tree(self.run1.path), self.run1_bytes)
        self.assertTrue(inspect_snapshot(self.run1.path, slug=SLUG).is_valid)
        for question in self.questions:
            state = classify_question(question, [], evidence_dir=self.evidence_dir, audit_slug=SLUG)
            self.assertEqual(state.state, STATE_NOT_STARTED)

    def test_run_two_collects_entirely_new_evidence(self) -> None:
        self.new_run()
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run two."
        self.collect()
        self.assertEqual(self.mock_answer.call_count, 40)
        self.assertEqual(self.mock_analysis.call_count, 40)
        self.assertEqual(len(load_existing_results(self.results_path)), 40)
        new_files = sorted(self.evidence_dir.iterdir())
        self.assertEqual(len(new_files), 40)
        for path in new_files:
            new = json.loads(path.read_text(encoding="utf-8"))["raw_response_text"]
            old = json.loads((self.run1.path / "raw_responses" / path.name).read_text(encoding="utf-8"))
            self.assertTrue(new.endswith("Run two."))
            self.assertNotEqual(new, old["raw_response_text"])
        self.assertEqual(tree(self.run1.path), self.run1_bytes)
        self.assertEqual(self.state(), STATE_COMPLETE)
        second = self.snapshot(when=T2)
        self.assertEqual(second.run_id, RUN_2)
        self.assertEqual(self.state(), STATE_SNAPSHOTTED)

    def test_already_fresh_is_refused(self) -> None:
        self.new_run()
        with self.assertRaises(AuditHistoryError) as ctx:
            self.new_run()
        self.assertIn("already fresh", str(ctx.exception))
        code, _, err = self.run_cli(["new-run", "--audit", SLUG])
        self.assertEqual(code, 1)
        self.assertIn("already fresh", err)

    def test_cli_new_run(self) -> None:
        code, out, err = self.run_cli(["new-run", "--audit", SLUG])
        self.assertEqual(code, 0, err)
        self.assertIn(f"previous run is preserved in snapshot {RUN_1}", out)
        self.assertIn("40 evidence file(s) removed", out)
        self.assert_fresh()


class NewRunRefusalTests(_NewRunTestCase):
    def assert_refused(self, exc_type, fragment: str) -> None:
        before = self.active_tree()
        snapshots_before = tree(self.snapshots_dir)
        with self.assertRaises(exc_type) as ctx:
            self.new_run()
        self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(self.active_tree(), before)
        self.assertEqual(tree(self.snapshots_dir), snapshots_before)

    def test_never_snapshotted(self) -> None:
        self.collect(limit=5)
        self.assert_refused(AuditHistoryError, "has not been snapshotted")

    def test_changed_after_snapshot(self) -> None:
        self.collect(limit=5)
        self.snapshot(allow_partial=True)
        self.collect(limit=3)
        self.assert_refused(AuditHistoryError, "differs from the latest snapshot")
        self.assertEqual(self.state(), STATE_IN_PROGRESS)
        code, _, err = self.run_cli(["new-run", "--audit", SLUG])
        self.assertEqual(code, 1)
        self.assertIn("snapshot the current run first", err)
        self.assertNotIn("Traceback", err)

    def test_config_changed_after_snapshot(self) -> None:
        self.collect()
        self.snapshot()
        config = self.audit_dir / "audit_config.json"
        config.write_bytes(config.read_bytes() + b" ")
        self.assert_refused(AuditHistoryError, "audit_config.json has changed")

    def test_tampered_latest_snapshot_refused(self) -> None:
        self.collect()
        snapshot = self.snapshot()
        (snapshot.path / "reports" / "audit_report.md").write_text("tampered", encoding="utf-8")
        self.assert_refused(SnapshotIntegrityError, "failed validation")

    def test_no_fallback_to_older_snapshot(self) -> None:
        self.collect(limit=5)
        self.snapshot(when=T1, allow_partial=True)
        self.collect()
        latest = self.snapshot(when=T2)
        (latest.path / "audit_results.csv").write_text("tampered", encoding="utf-8")
        self.assertTrue(inspect_snapshot(self.snapshots_dir / RUN_1, slug=SLUG).is_valid)
        self.assert_refused(SnapshotIntegrityError, f"latest snapshot {RUN_2} failed validation")

    def test_fresh_audit_refused(self) -> None:
        self.assert_refused(AuditHistoryError, "already fresh")


class PartialSnapshotNewRunTests(_NewRunTestCase):
    def test_new_run_after_deliberate_partial_snapshot(self) -> None:
        self.collect(limit=37)
        self.failing_analysis.add(self.questions[37]["question_id"])
        self.collect(limit=1)  # an answer stored without a row
        partial = self.snapshot(allow_partial=True)
        partial_bytes = tree(partial.path)
        result = self.new_run()
        self.assertEqual(result.retired_evidence_files, 38)
        self.assert_fresh()
        self.assertEqual(tree(partial.path), partial_bytes)
        self.assertEqual(partial.manifest["status"], "partial")


class ResetFailureTests(_NewRunTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.collect()
        self.run1 = self.snapshot()
        self.run1_bytes = tree(self.run1.path)
        self.methodology = self.method_bytes()
        self.results_before = Path(self.results_path).read_bytes()

    def assert_history_safe(self) -> None:
        self.assertEqual(tree(self.run1.path), self.run1_bytes)
        self.assertTrue(inspect_snapshot(self.run1.path, slug=SLUG).is_valid)
        self.assertEqual(self.method_bytes(), self.methodology)

    def retired_matches_snapshot(self) -> None:
        (retired,) = self.retirement_dirs()
        for path in retired.iterdir():
            self.assertEqual(path.read_bytes(), (self.run1.path / "raw_responses" / path.name).read_bytes())
        self.assertEqual(len(list(retired.iterdir())), 40)

    def interrupt_after_retirement(self) -> None:
        with patch("audit_history._write_fresh_results", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.new_run()

    def test_a_retirement_rename_fails(self) -> None:
        before = self.active_tree()
        with patch("audit_history._retire", side_effect=OSError("rename failed")):
            with self.assertRaises(OSError):
                self.new_run()
        self.assertEqual(self.active_tree(), before)
        self.assertEqual(self.retirement_dirs(), [])
        self.assert_history_safe()
        self.assertFalse(self.new_run().recovered)
        self.assert_fresh()

    def test_a_interrupt_before_retirement(self) -> None:
        before = self.active_tree()
        with patch("audit_history._retire", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.new_run()
        self.assertEqual(self.active_tree(), before)
        self.assert_history_safe()

    def test_b_results_write_fails_after_retirement_then_recovers(self) -> None:
        self.interrupt_after_retirement()
        self.assertEqual(Path(self.results_path).read_bytes(), self.results_before)
        self.assertFalse(self.evidence_dir.exists())
        self.retired_matches_snapshot()
        self.assert_history_safe()
        self.assertEqual(self.state(), STATE_RESET_INTERRUPTED)
        with self.assertRaises(AuditHistoryError) as ctx:
            self.snapshot(when=T2)
        self.assertIn("interrupted new-run", str(ctx.exception))

        result = self.new_run()
        self.assertTrue(result.recovered)
        self.assert_fresh()
        self.assert_history_safe()

    def test_b_interrupt_during_results_reset_then_recovers(self) -> None:
        with patch("audit_history._write_fresh_results", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.new_run()
        self.retired_matches_snapshot()
        code, out, err = self.run_cli(["new-run", "--audit", SLUG])
        self.assertEqual(code, 0, err)
        self.assertIn("Finished an interrupted new-run.", out)
        self.assert_fresh()

    def test_c_fresh_results_validation_fails_then_recovers(self) -> None:
        with patch("audit_history._validate_fresh_results", side_effect=SnapshotIntegrityError("not valid")):
            with self.assertRaises(SnapshotIntegrityError):
                self.new_run()
        self.retired_matches_snapshot()
        self.assert_history_safe()
        self.assertEqual(self.state(), STATE_RESET_INTERRUPTED)
        self.assertTrue(self.new_run().recovered)
        self.assert_fresh()

    def test_d_retirement_deletion_fails_then_recovers(self) -> None:
        with patch("audit_history._remove_retired", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                self.new_run()
        self.assertEqual(load_existing_results(self.results_path), [])
        self.retired_matches_snapshot()
        self.assert_history_safe()
        result = self.new_run()
        self.assertTrue(result.recovered)
        self.assertEqual(result.retired_evidence_files, 40)
        self.assert_fresh()

    def test_e_final_verification_fails(self) -> None:
        with patch("audit_history._verify_final_state", side_effect=SnapshotIntegrityError("not fresh")):
            with self.assertRaises(SnapshotIntegrityError):
                self.new_run()
        self.assert_history_safe()
        self.assertEqual(self.state(), STATE_FRESH)

    def test_retired_evidence_altered_is_never_deleted(self) -> None:
        self.interrupt_after_retirement()
        (retired,) = self.retirement_dirs()
        victim = sorted(retired.iterdir())[0]
        victim.write_text("altered", encoding="utf-8")
        with self.assertRaises(SnapshotIntegrityError) as ctx:
            self.new_run()
        self.assertIn("does not match snapshot", str(ctx.exception))
        self.assertTrue(retired.exists())
        self.assertEqual(victim.read_text(encoding="utf-8"), "altered")
        self.assertEqual(Path(self.results_path).read_bytes(), self.results_before)
        self.assert_history_safe()

    def test_retired_evidence_with_extra_file_refused(self) -> None:
        self.interrupt_after_retirement()
        (retired,) = self.retirement_dirs()
        (retired / "extra.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(SnapshotIntegrityError):
            self.new_run()
        self.assertTrue(retired.exists())

    def test_retired_folder_for_another_snapshot_refused(self) -> None:
        self.interrupt_after_retirement()
        (retired,) = self.retirement_dirs()
        retired.rename(retired.with_name(".retired-raw-20260101T000000Z-abcd"))
        with self.assertRaises(SnapshotIntegrityError) as ctx:
            self.new_run()
        self.assertIn("does not belong to the latest snapshot", str(ctx.exception))
        self.assertEqual(len(self.retirement_dirs()), 1)

    def test_multiple_retirement_folders_refused(self) -> None:
        self.interrupt_after_retirement()
        (retired,) = self.retirement_dirs()
        shutil.copytree(retired, retired.with_name(f".retired-raw-{RUN_1}-ffff"))
        with self.assertRaises(SnapshotIntegrityError) as ctx:
            self.new_run()
        self.assertIn("More than one retired evidence folder", str(ctx.exception))
        self.assertEqual(len(self.retirement_dirs()), 2)
        self.assert_history_safe()

    def test_new_evidence_during_interruption_refused(self) -> None:
        self.interrupt_after_retirement()
        self.evidence_dir.mkdir()
        (self.evidence_dir / "PA01__gemini.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(SnapshotIntegrityError):
            self.new_run()
        self.assertEqual(len(self.retirement_dirs()), 1)

    def test_results_changed_during_interruption_refused(self) -> None:
        self.interrupt_after_retirement()
        from write_single_audit_result import write_results_atomically
        write_results_atomically(self.results_path, load_existing_results(self.results_path)[:5])
        with self.assertRaises(SnapshotIntegrityError) as ctx:
            self.new_run()
        self.assertIn("matches neither", str(ctx.exception))
        self.assertEqual(len(self.retirement_dirs()), 1)
        self.assert_history_safe()


class MultiRunLifecycleTests(_NewRunTestCase):
    def test_three_runs(self) -> None:
        self.collect()
        run1 = self.snapshot(when=T1)
        run1_bytes = tree(run1.path)
        self.new_run()

        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run two."
        self.collect()
        run2 = self.snapshot(when=T2)
        run2_bytes = tree(run2.path)
        self.new_run()

        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run three."
        self.collect(limit=10)

        self.assertEqual(tree(run1.path), run1_bytes)
        self.assertEqual(tree(run2.path), run2_bytes)
        self.assertNotEqual(run1.run_id, run2.run_id)
        pa01 = "raw_responses/PA01__gemini.json"
        texts = [json.loads(p.read_text(encoding="utf-8"))["raw_response_text"]
                 for p in (run1.path / pa01, run2.path / pa01, self.audit_dir / pa01)]
        self.assertEqual(len(set(texts)), 3)
        self.assertTrue(texts[2].endswith("Run three."))
        self.assertEqual(len(load_existing_results(self.results_path)), 10)
        self.assertEqual(self.state(), STATE_IN_PROGRESS)

        snapshots = list_snapshots(SLUG, audits_dir=self.audits)
        self.assertEqual([s.run_id for s in snapshots], [RUN_1, RUN_2])
        self.assertTrue(all(s.is_valid for s in snapshots))
        code, out, _ = self.run_cli(["list", "--audit", SLUG])
        self.assertEqual(code, 0)
        self.assertIn("Current run: in progress / partial (10/40 structurally complete) - not snapshotted", out)


class ListStateTests(_NewRunTestCase):
    def summary(self) -> str:
        return audit_history._active_summary(SLUG, self.audits)

    def test_each_state_is_shown(self) -> None:
        self.assertIn("Current run: fresh", self.summary())
        self.collect(limit=3)
        self.assertIn("Current run: in progress / partial (3/40", self.summary())
        self.collect()
        self.assertIn("Current run: complete (40/40 structurally complete) - not snapshotted", self.summary())
        self.snapshot()
        self.assertIn(f"Current run: snapshotted (40/40 structurally complete) - preserved as {RUN_1}", self.summary())
        with patch("audit_history._write_fresh_results", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.new_run()
        before = tree(self.audit_dir)
        self.assertIn("Current run: reset interrupted - run new-run again", self.summary())
        self.assertEqual(tree(self.audit_dir), before)  # reading the state writes nothing
        self.new_run()
        self.assertIn("Current run: fresh", self.summary())

    def test_manual_rows_make_the_run_not_fresh(self) -> None:
        from write_single_audit_result import write_results_atomically
        row = {name: "" for name in RESULTS_SCHEMA}
        row.update({"run_date": "2026-09-01", "question_id": "PA01", "question": "Q",
                    "funnel_stage": "Problem Awareness", "engine": "Perplexity", "answer_snippet": "Manual."})
        write_results_atomically(self.results_path, [row])
        self.assertEqual(self.state(), STATE_IN_PROGRESS)


class BootsCopyNewRunTests(_NewRunTestCase):
    def test_boots_copy_partial_snapshot_then_new_run(self) -> None:
        boots_audits = self.root / "boots-copy"
        shutil.copytree(REPO_ROOT / "audits" / BOOTS_SLUG, boots_audits / BOOTS_SLUG)
        committed_results = (REPO_ROOT / "audits" / BOOTS_SLUG / "audit_results.csv").read_bytes()
        snapshot = create_snapshot(BOOTS_SLUG, audits_dir=boots_audits, allow_partial=True, now=lambda: T1)
        result = start_new_run(BOOTS_SLUG, audits_dir=boots_audits)
        self.assertEqual((result.retired_evidence_files, result.recovered), (0, False))
        copy_dir = boots_audits / BOOTS_SLUG
        self.assertEqual(load_existing_results(str(copy_dir / "audit_results.csv")), [])
        self.assertFalse((copy_dir / "raw_responses").exists())
        self.assertEqual(active_run_state(BOOTS_SLUG, audits_dir=boots_audits).state, STATE_FRESH)
        self.assertEqual((snapshot.path / "audit_results.csv").read_bytes(), committed_results)
        self.assertTrue(inspect_snapshot(snapshot.path, slug=BOOTS_SLUG).is_valid)
        self.assertFalse((REPO_ROOT / "audits" / BOOTS_SLUG / "snapshots").exists())


# ==========================================================================
# Checkpoint C - comparing two snapshots
# ==========================================================================

GEN_DATE = date(2026, 11, 2)
NOT_CITED_JSON = json.dumps({
    "brand_cited": "N", "brand_position": None, "competitors_cited": ["Brewvale", "Steepwisé"],
    "sources_cited": [], "sentiment": "Neutral",
})


def metric_rows(progress) -> list[tuple[str, str, str, str, str]]:
    return [(m.metric_name, m.before, m.after, m.difference, m.direction) for m in progress.metrics]


class _CompareTestCase(_NewRunTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.analysis_overrides: dict[str, str] = {}
        self.reports = self.root / "reports"
        self.comparisons = self.reports / SLUG / "comparisons"
        self.ids = [q["question_id"] for q in self.questions]

    def _analysis(self, prompt: str) -> str:
        question_id = next(qid for text, qid in self.by_text.items() if repr(text) in prompt)
        if question_id in self.analysis_overrides and question_id not in self.failing_analysis:
            return self.analysis_overrides[question_id]
        return super()._analysis(prompt)

    def run_and_snapshot(self, when, *, limit=None, allow_partial=False, new_run=True):
        self.collect(limit=limit)
        snapshot = self.snapshot(when=when, allow_partial=allow_partial)
        if new_run:
            self.new_run()
        return snapshot

    def compare(self, from_run=RUN_1, to_run=RUN_2, generated_at=GEN_DATE):
        return compare_snapshots(SLUG, from_run, to_run, audits_dir=self.audits, generated_at=generated_at)

    def output(self, from_run=RUN_1, to_run=RUN_2) -> Path:
        return self.comparisons / f"{from_run}__{to_run}" / "GEO_PROGRESS.md"

    def assert_refused(self, exc_type, fragment: str, from_run=RUN_1, to_run=RUN_2):
        snapshots_before, active_before = tree(self.snapshots_dir), self.active_tree()
        with self.assertRaises(exc_type) as ctx:
            self.compare(from_run, to_run)
        self.assertIn(fragment, str(ctx.exception))
        self.assertFalse(self.comparisons.exists(), "a refused comparison wrote output")
        self.assertEqual(tree(self.snapshots_dir), snapshots_before)
        self.assertEqual(self.active_tree(), active_before)
        return ctx.exception

    def run_cli(self, argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with patch("audit_config.AUDITS_DIR", self.audits), redirect_stdout(out), redirect_stderr(err):
            code = audit_history.main(argv)
        return code, out.getvalue(), err.getvalue()

    def edit_config(self, **changes) -> None:
        path = self.audit_dir / "audit_config.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(changes)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def edit_questions(self, mutate) -> None:
        path = Path(self.questions_path)
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        mutate(rows)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        from audit_runner import load_questions
        self.questions = load_questions(self.questions_path)
        self.by_text = {q["question"]: q["question_id"] for q in self.questions}

    def spy_compare_audits(self):
        spy = patch("audit_history.compare_audits", wraps=measurement_engine.compare_audits)
        mock = spy.start()
        self.addCleanup(spy.stop)
        return mock

    def assert_metric_inputs(self, spy, shared: list[str]) -> None:
        spy.assert_called_once()
        from_rows, to_rows, total = spy.call_args.args
        self.assertEqual([r["question_id"] for r in from_rows], shared)
        self.assertEqual([r["question_id"] for r in to_rows], shared)
        self.assertEqual(total, len(shared))
        self.assertTrue(all(r["engine"] == "Gemini" for r in from_rows + to_rows))
        self.assertEqual(
            {k: spy.call_args.kwargs[k] for k in ("brand", "market", "category")},
            {"brand": self.config.brand, "market": self.config.market, "category": self.config.category},
        )


class CompareFullRunTests(_CompareTestCase):
    """Run 1: 40 complete. Run 2: 40 complete, brand not cited for the 16
    Problem Awareness and Solution Discovery questions."""

    def setUp(self) -> None:
        super().setUp()
        self.run1 = self.run_and_snapshot(T1)
        self.analysis_overrides = {qid: NOT_CITED_JSON for qid in self.ids if qid[:2] in ("PA", "SD")}
        self.run2 = self.run_and_snapshot(T2, new_run=False)

    def test_full_40_vs_40(self) -> None:
        snapshots_before, active_before = tree(self.snapshots_dir), self.active_tree()
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        spy = self.spy_compare_audits()

        result = self.compare()

        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()
        self.assert_metric_inputs(spy, self.ids)
        for snapshot in (self.run1, self.run2):
            self.assertTrue(inspect_snapshot(snapshot.path, slug=SLUG).is_valid)
        self.assertEqual((result.from_run, result.to_run), (RUN_1, RUN_2))
        self.assertEqual((result.from_complete, result.from_total, result.to_complete, result.to_total), (40, 40, 40, 40))
        self.assertEqual(result.shared_question_count, 40)
        self.assertEqual(list(result.shared_question_ids), self.ids)
        self.assertEqual(metric_rows(result.progress), [
            ("Brand Visibility", "100.0%", "60.0%", "-40.0pp", "Declined"),
            ("Brand Mention Frequency", "40", "24", "-16", "Declined"),
            ("Competitor Mention Change", "40", "56", "+16", "Informational"),
            ("Sentiment Change (Positive Rate)", "100.0%", "60.0%", "-40.0pp", "Declined"),
            ("Authority Source Change", "100.0%", "60.0%", "-40.0pp", "Declined"),
            ("Funnel Stage Coverage", "5 of 5", "5 of 5", "+0", "No Change"),
            ("Overall GEO Maturity", "Established", "Established", "No change in tier", "No Change"),
        ])
        # Exactly what the existing engine gives for the two snapshots' own rows.
        expected = measurement_engine.compare_audits(
            load_existing_results(str(self.run1.path / "audit_results.csv")),
            load_existing_results(str(self.run2.path / "audit_results.csv")),
            40, brand=self.config.brand, market=self.config.market, category=self.config.category,
            generated_at=GEN_DATE,
        )
        self.assertEqual(result.progress, expected)
        self.assertIsNone(result.requested_model_warning)
        self.assertIsNone(result.version_warning)

        self.assertEqual(result.output_path, self.output())
        self.assertEqual(sorted(p.name for p in self.output().parent.iterdir()), ["GEO_PROGRESS.md"])
        report = self.output().read_text(encoding="utf-8")
        self.assertTrue(report.startswith(f"# SignalScope AI GEO Progress Report — {self.config.report_subject}\n"))
        for line in (f"- From run (earlier): {RUN_1}", f"- To run (later): {RUN_2}",
                     "- From coverage: 40 / 40 structurally complete Gemini questions (100.0%)",
                     "- To coverage: 40 / 40 structurally complete Gemini questions (100.0%)",
                     "- Shared complete questions used: 40",
                     "- From run (shared questions): 40 row(s), 40 unique question(s)",
                     "| Brand Visibility | 100.0% | 60.0% | -40.0pp | Declined |",
                     "- Report generation date: 2026-11-02"):
            self.assertIn(line, report)
        self.assertNotIn("Warning", report)
        self.assertNotIn("Unequal coverage", report)

        self.assertEqual(tree(self.snapshots_dir), snapshots_before)
        self.assertEqual(self.active_tree(), active_before)
        self.assertEqual(self.state(), STATE_SNAPSHOTTED)
        self.assertEqual([p for p in self.snapshots_dir.rglob("*") if "comparisons" in p.name], [])

    def test_cli_compare(self) -> None:
        code, out, err = self.run_cli(["compare", "--audit", SLUG, "--from-run", RUN_1, "--to-run", RUN_2])
        self.assertEqual(code, 0, err)
        self.assertIn(f"from run {RUN_1} to run {RUN_2}", out)
        self.assertIn("from coverage: 40/40 structurally complete", out)
        self.assertIn("shared complete questions used: 40", out)
        self.assertNotIn("Warning", out)
        self.assertIn(str(self.output()), out)
        self.assertTrue(self.output().is_file())

    def test_rerun_replaces_the_same_output(self) -> None:
        self.compare()
        first = self.output().read_bytes()
        self.compare()
        self.assertEqual(self.output().read_bytes(), first)
        self.compare(generated_at=date(2026, 12, 1))
        later = self.output().read_text(encoding="utf-8")
        self.assertIn("- Report generation date: 2026-12-01", later)
        self.assertEqual(later.replace("2026-12-01", "2026-11-02").encode("utf-8"), first)
        self.assertEqual(sorted(p.name for p in self.output().parent.iterdir()), ["GEO_PROGRESS.md"])

    def test_write_failure_leaves_no_output(self) -> None:
        self.compare()
        previous = self.output().read_bytes()
        with patch("audit_history.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.compare(generated_at=date(2026, 12, 1))
        self.assertEqual(self.output().read_bytes(), previous)
        self.assertEqual(sorted(p.name for p in self.output().parent.iterdir()), ["GEO_PROGRESS.md"])

    def test_direction_and_run_id_checks(self) -> None:
        exc = self.assert_refused(AuditHistoryError, "directional", RUN_2, RUN_1)
        self.assertIn("must be earlier", str(exc))
        self.assert_refused(AuditHistoryError, "same run", RUN_1, RUN_1)
        self.assert_refused(AuditHistoryError, "Invalid run ID", "2026-10-01", RUN_2)
        self.assert_refused(AuditHistoryError, "Invalid run ID", RUN_1, "latest")
        self.assert_refused(AuditHistoryError, f"No snapshot {run_id_for(T3)}", RUN_1, run_id_for(T3))
        self.compare(RUN_1, RUN_2)  # the right way round succeeds

        code, _, err = self.run_cli(["compare", "--audit", SLUG, "--from-run", RUN_2, "--to-run", RUN_1])
        self.assertEqual(code, 1)
        self.assertIn("from-run", err)
        self.assertNotIn("Traceback", err)

    def test_argument_errors(self) -> None:
        base = ["compare", "--audit", SLUG]
        for argv in (base, base + ["--from-run", RUN_1], base + ["--to-run", RUN_2],
                     base + ["--from-run", RUN_1, "--to-run", RUN_2, "--force"],
                     base + ["--from-run", RUN_1, "--to-run", RUN_2, "--provider", "gemini"]):
            with self.subTest(argv=argv):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        audit_history.main(argv)
                self.assertEqual(ctx.exception.code, 2)
        code, _, err = self.run_cli(["compare", "--audit", "../x", "--from-run", RUN_1, "--to-run", RUN_2])
        self.assertEqual(code, 1)
        self.assertIn("Invalid audit slug", err)

    def test_tampered_snapshot_refused(self) -> None:
        with (self.run2.path / "audit_results.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        exc = self.assert_refused(SnapshotIntegrityError, f"Snapshot {RUN_2} (to run) failed validation")
        self.assertIn("modified file audit_results.csv", str(exc))
        (self.run1.path / "raw_responses" / "PA01__gemini.json").write_text("{}", encoding="utf-8")
        self.assert_refused(SnapshotIntegrityError, f"Snapshot {RUN_1} (from run) failed validation")

    def test_list_snapshot_and_new_run_unaffected(self) -> None:
        self.compare()
        code, out, _ = self.run_cli(["list", "--audit", SLUG])
        self.assertEqual(code, 0)
        self.assertIn(f"Current run: snapshotted (40/40 structurally complete) - preserved as {RUN_2}", out)
        with self.assertRaises(AuditHistoryError):
            self.snapshot(when=T3)  # already snapshotted, as before
        self.assertEqual(self.new_run().preserved_run_id, RUN_2)
        self.assert_fresh()
        self.compare()  # the snapshots still compare after the reset


class CompareCoverageTests(_CompareTestCase):
    def test_unequal_coverage_uses_only_shared_questions(self) -> None:
        last_ten = self.ids[30:]
        self.analysis_overrides = {qid: NOT_CITED_JSON for qid in last_ten}
        run1 = self.run_and_snapshot(T1)
        self.analysis_overrides = {}
        self.run_and_snapshot(T2, limit=30, allow_partial=True, new_run=False)
        spy = self.spy_compare_audits()

        result = self.compare()

        self.assert_metric_inputs(spy, self.ids[:30])
        self.assertEqual((result.from_complete, result.from_total, result.to_complete, result.to_total), (40, 40, 30, 40))
        self.assertEqual(list(result.shared_question_ids), self.ids[:30])
        self.assertEqual((result.progress.baseline_row_count, result.progress.followup_row_count), (30, 30))
        # Run 1 over all 40 questions has 75% visibility; the 10 questions
        # missing from run 2 are excluded from BOTH sides.
        all_run1 = load_existing_results(str(run1.path / "audit_results.csv"))
        self.assertEqual(compute_brand_visibility(all_run1)["rate"], 75.0)
        self.assertEqual(metric_rows(result.progress), [
            ("Brand Visibility", "100.0%", "100.0%", "+0.0pp", "No Change"),
            ("Brand Mention Frequency", "30", "30", "+0", "No Change"),
            ("Competitor Mention Change", "30", "30", "+0", "Informational"),
            ("Sentiment Change (Positive Rate)", "100.0%", "100.0%", "+0.0pp", "No Change"),
            ("Authority Source Change", "100.0%", "100.0%", "+0.0pp", "No Change"),
            ("Funnel Stage Coverage", "4 of 5", "4 of 5", "+0", "No Change"),
            ("Overall GEO Maturity", "Established", "Established", "No change in tier", "No Change"),
        ])
        report = self.output().read_text(encoding="utf-8")
        for line in ("- From coverage: 40 / 40 structurally complete Gemini questions (100.0%)",
                     "- To coverage: 30 / 40 structurally complete Gemini questions (75.0%)",
                     "- Shared complete questions used: 30",
                     "> **Unequal coverage.**"):
            self.assertIn(line, report)

    def test_partial_runs_with_different_completion_sets(self) -> None:
        self.run_and_snapshot(T1, limit=20, allow_partial=True)  # PA01-VC04
        self.failing_analysis.update(self.ids[:8])  # PA01-PA08: answer stored, no row
        run2 = self.run_and_snapshot(T2, allow_partial=True, new_run=False)
        self.assertEqual(run2.manifest["structurally_complete_count"], 32)  # SD01-PD08
        spy = self.spy_compare_audits()

        result = self.compare()

        shared = [f"SD0{i}" for i in range(1, 9)] + [f"VC0{i}" for i in range(1, 5)]
        self.assertEqual(list(result.shared_question_ids), shared)
        self.assert_metric_inputs(spy, shared)
        self.assertEqual((result.from_complete, result.to_complete, result.shared_question_count), (20, 32, 12))
        self.assertEqual((result.progress.baseline_unique_questions, result.progress.followup_unique_questions), (12, 12))
        self.assertIn(("Funnel Stage Coverage", "2 of 5", "2 of 5", "+0", "No Change"), metric_rows(result.progress))

    def test_zero_overlap_refused(self) -> None:
        self.run_and_snapshot(T1, limit=8, allow_partial=True)  # PA01-PA08 only
        self.failing_analysis.update(self.ids[:8])
        self.run_and_snapshot(T2, allow_partial=True, new_run=False)  # everything except PA
        self.assert_refused(AuditHistoryError, "No question is structurally complete in both runs")

    def test_perplexity_and_incomplete_rows_are_ignored(self) -> None:
        self.run_and_snapshot(T1)
        by_id = {q["question_id"]: q for q in self.questions}

        def row(qid, engine, **values):
            q = by_id[qid]
            base = {name: "" for name in RESULTS_SCHEMA}
            base.update({"run_date": "2026-10-01", "question_id": qid, "question": q["question"],
                         "funnel_stage": q["buyer_journey_stage"], "engine": engine,
                         "answer_snippet": "Manual answer."}, **values)
            return base

        from write_single_audit_result import write_results_atomically
        write_results_atomically(self.results_path, [
            row("PA01", "Perplexity", brand_cited="N", sentiment="Negative"),  # manual, other engine
            row("PD08", "Gemini", brand_cited="N"),  # structurally incomplete (no sentiment)
        ])
        run2 = self.run_and_snapshot(T2, allow_partial=True, new_run=False)
        self.assertEqual(run2.manifest["structurally_complete_count"], 39)
        spy = self.spy_compare_audits()

        result = self.compare()

        self.assert_metric_inputs(spy, self.ids[:39])
        self.assertEqual((result.to_complete, result.shared_question_count), (39, 39))
        self.assertEqual(metric_rows(result.progress)[:4], [
            ("Brand Visibility", "100.0%", "100.0%", "+0.0pp", "No Change"),
            ("Brand Mention Frequency", "39", "39", "+0", "No Change"),
            ("Competitor Mention Change", "39", "39", "+0", "Informational"),
            ("Sentiment Change (Positive Rate)", "100.0%", "100.0%", "+0.0pp", "No Change"),
        ])


class CompareComparabilityTests(_CompareTestCase):
    """Run 2 is collected after the current config or question file is
    edited, so each snapshot is valid but the pair may not be comparable."""

    def second_run(self, edit) -> None:
        self.run_and_snapshot(T1, limit=5, allow_partial=True)
        edit()
        self.run_and_snapshot(T2, limit=5, allow_partial=True, new_run=False)

    def assert_not_comparable(self, edit, fragment: str) -> None:
        self.second_run(edit)
        exc = self.assert_refused(NotComparableError, fragment)
        self.assertTrue(any(fragment in p for p in exc.problems), exc.problems)

    def test_brand_changed(self) -> None:
        self.assert_not_comparable(lambda: self.edit_config(brand="Lumiere Tea"), "brand differs")

    def test_market_changed(self) -> None:
        self.assert_not_comparable(lambda: self.edit_config(market="Veloria North"), "market differs")

    def test_category_changed(self) -> None:
        self.assert_not_comparable(lambda: self.edit_config(category="Tea Subscriptions"), "category differs")

    def test_competitor_replaced(self) -> None:
        competitors = ["Brewvale", "O'Kettle & Co", "Leafline"]
        self.assert_not_comparable(lambda: self.edit_config(competitors=competitors), "competitors differ")

    def test_competitors_reordered(self) -> None:
        reordered = list(reversed(CREATION_DATA["competitors"]))
        self.assert_not_comparable(lambda: self.edit_config(competitors=reordered), "competitor order differs")

    def test_display_only_fields_may_differ(self) -> None:
        self.second_run(lambda: self.edit_config(
            company_name="Lumière Holdings", report_subject="Lumière Holdings Tea", question_library="Renamed Library"
        ))
        result = self.compare()
        self.assertEqual(result.shared_question_count, 5)
        self.assertTrue(result.output_path.read_text(encoding="utf-8").startswith(
            "# SignalScope AI GEO Progress Report — Lumière Holdings Tea\n"))

    def test_question_text_changed(self) -> None:
        def edit():
            self.edit_questions(lambda rows: rows[0].update(question=rows[0]["question"] + " Today?"))
        self.assert_not_comparable(edit, "PA01 question text differs")

    def test_question_id_changed(self) -> None:
        self.assert_not_comparable(lambda: self.edit_questions(lambda rows: rows[0].update(question_id="PA99")),
                                   "questions only in the from run: PA01")

    def test_buyer_stage_changed(self) -> None:
        def edit():
            self.edit_questions(lambda rows: rows[0].update(buyer_journey_stage="Solution Discovery"))
        self.assert_not_comparable(edit, "PA01 buyer_journey_stage differs")

    def test_question_added(self) -> None:
        def add(rows):
            rows.append(dict(rows[-1], question_id="PD09", question="Which tea retailer would you buy from?"))
        self.assert_not_comparable(lambda: self.edit_questions(add), "questions only in the to run: PD09")

    def test_question_removed(self) -> None:
        self.assert_not_comparable(lambda: self.edit_questions(lambda rows: rows.pop()),
                                   "questions only in the from run: PD08")

    def test_questions_reordered(self) -> None:
        def swap(rows):
            rows[0], rows[1] = rows[1], rows[0]
        self.assert_not_comparable(lambda: self.edit_questions(swap), "question order differs")

    def test_intent_and_notes_may_differ(self) -> None:
        self.second_run(lambda: self.edit_questions(lambda rows: rows[0].update(intent="Changed.", notes="Changed.")))
        self.assertEqual(self.compare().shared_question_count, 5)


class CompareWarningTests(_CompareTestCase):
    def test_requested_model_warning(self) -> None:
        self.run_and_snapshot(T1, limit=5, allow_partial=True)
        with patch("gemini_client.DEFAULT_MODEL", "gemini-test-model-b"):
            run2 = self.run_and_snapshot(T2, limit=5, allow_partial=True, new_run=False)
        self.assertEqual(run2.manifest["requested_models"], ["gemini-test-model-b"])

        result = self.compare()

        self.assertIn("The requested Gemini model set differs between these runs", result.requested_model_warning)
        self.assertIn("does not attribute any change", result.requested_model_warning)
        self.assertIsNone(result.version_warning)
        report = self.output().read_text(encoding="utf-8")
        self.assertIn("> **Warning:** The requested Gemini model set differs between these runs", report)
        self.assertIn("gemini-test-model-b", report)
        self.assertNotIn("caused", report)
        code, out, _ = self.run_cli(["compare", "--audit", SLUG, "--from-run", RUN_1, "--to-run", RUN_2])
        self.assertEqual(code, 0)
        self.assertIn("Warning: The requested Gemini model set differs", out)

    def test_signalscope_version_warning(self) -> None:
        self.run_and_snapshot(T1, limit=5, allow_partial=True)
        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run two."
        with patch("audit_history.SIGNALSCOPE_VERSION", "2.4.1"):
            run2 = self.run_and_snapshot(T2, limit=5, allow_partial=True, new_run=False)
        self.assertEqual(run2.manifest["signalscope_version"], "2.4.1")

        result = self.compare()

        self.assertIn("different SignalScope versions", result.version_warning)
        self.assertIn(f"from run: {SIGNALSCOPE_VERSION}; to run: 2.4.1", result.version_warning)
        self.assertNotIn("invalid", result.version_warning.lower())
        self.assertIsNone(result.requested_model_warning)
        self.assertIn("> **Warning:** These runs were created with different SignalScope versions",
                      self.output().read_text(encoding="utf-8"))

    def test_no_model_warning_when_neither_run_recorded_models(self) -> None:
        # Legacy-style runs: complete rows without stored answers.
        self.collect(limit=5)
        shutil.rmtree(self.evidence_dir)
        self.snapshot(when=T1, allow_partial=True)
        self.new_run()
        self.collect(limit=6)
        shutil.rmtree(self.evidence_dir)
        run2 = self.snapshot(when=T2, allow_partial=True)
        self.assertEqual(run2.manifest["requested_models"], [])
        result = self.compare()
        self.assertIsNone(result.requested_model_warning)
        self.assertEqual(result.shared_question_count, 5)


class RenderRunContextTests(unittest.TestCase):
    def setUp(self) -> None:
        row = {name: "" for name in RESULTS_SCHEMA}
        row.update({"question_id": "PA01", "funnel_stage": "Problem Awareness", "engine": "Gemini",
                    "brand_cited": "Y", "sentiment": "Positive"})
        self.progress = measurement_engine.compare_audits([row], [row], 1, generated_at=GEN_DATE)

    def test_default_render_is_unchanged(self) -> None:
        default = measurement_engine.render_markdown(self.progress)
        self.assertEqual(measurement_engine.render_markdown(self.progress, run_context=None), default)
        self.assertNotIn("Run Comparison", default)
        self.assertIn("- Baseline audit: 1 row(s), 1 unique question(s)", default)

    def test_context_block(self) -> None:
        context = measurement_engine.RunComparisonContext(RUN_1, RUN_2, 40, 40, 30, 40, 30,
                                                          requested_model_warning="Models differ.")
        text = measurement_engine.render_markdown(self.progress, run_context=context)
        self.assertIn("## Run Comparison", text)
        self.assertIn("- To coverage: 30 / 40 structurally complete Gemini questions (75.0%)", text)
        self.assertIn("> **Warning:** Models differ.", text)
        self.assertIn("- To run (shared questions): 1 row(s), 1 unique question(s)", text)
        self.assertNotIn("Baseline audit", text)



class ModelProvenanceTests(_CompareTestCase):
    """requested_models in a manifest must equal the models recorded in the
    snapshot's own evidence; signalscope_version stays recorded metadata."""

    MISMATCH = "manifest requested_models"

    def evidence_models(self, snapshot) -> list[str]:
        evidence = snapshot.path / "raw_responses"
        if not evidence.exists():
            return []
        return sorted({json.loads(p.read_text(encoding="utf-8"))["requested_model"] for p in evidence.iterdir()})

    def set_manifest_models(self, snapshot, models) -> None:
        path = snapshot.path / MANIFEST_FILENAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["requested_models"] = models
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def assert_model_mismatch(self, snapshot, models) -> None:
        self.set_manifest_models(snapshot, models)
        info = inspect_snapshot(snapshot.path, slug=SLUG)
        self.assertFalse(info.is_valid)
        self.assertEqual(len(info.problems), 1, info.problems)
        self.assertIn(f"{self.MISMATCH} {models!r} does not match the snapshot evidence", info.problems[0])

    def evidence_snapshot(self):
        self.collect(limit=5)
        return self.snapshot(when=T1, allow_partial=True)

    def test_a_valid_model_provenance(self) -> None:
        snapshot = self.evidence_snapshot()
        self.assertEqual(self.evidence_models(snapshot), ["gemini-2.5-flash"])
        self.assertEqual(snapshot.manifest["requested_models"], self.evidence_models(snapshot))
        self.assertTrue(inspect_snapshot(snapshot.path, slug=SLUG).is_valid)

    def test_b_false_model_value(self) -> None:
        snapshot = self.evidence_snapshot()
        evidence_before = tree(snapshot.path / "raw_responses")
        self.assert_model_mismatch(snapshot, ["gemini-other-model"])
        self.assertEqual(tree(snapshot.path / "raw_responses"), evidence_before)

    def test_c_false_empty_list(self) -> None:
        self.assert_model_mismatch(self.evidence_snapshot(), [])

    def test_d_false_extra_model(self) -> None:
        self.assert_model_mismatch(self.evidence_snapshot(), ["gemini-2.5-flash", "gemini-other-model"])

    def test_e_no_evidence_snapshot_with_empty_list_is_valid(self) -> None:
        self.collect(limit=5)
        shutil.rmtree(self.evidence_dir)  # legacy-style: complete rows without stored answers
        snapshot = self.snapshot(when=T1, allow_partial=True)
        self.assertFalse((snapshot.path / "raw_responses").exists())
        self.assertEqual(snapshot.manifest["requested_models"], [])
        self.assertTrue(inspect_snapshot(snapshot.path, slug=SLUG).is_valid)
        self.assert_model_mismatch(snapshot, ["gemini-2.5-flash"])  # and a claimed model is still refused

    def test_f_compare_refuses_tampered_model_provenance(self) -> None:
        self.run_and_snapshot(T1, limit=5, allow_partial=True)
        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run two."
        run2 = self.run_and_snapshot(T2, limit=5, allow_partial=True, new_run=False)
        self.compare()  # untampered: comparable, no model warning
        shutil.rmtree(self.comparisons)
        self.set_manifest_models(run2, ["gemini-other-model"])
        exc = self.assert_refused(SnapshotIntegrityError, f"Snapshot {RUN_2} (to run) failed validation")
        self.assertIn("does not match the snapshot evidence", str(exc))

    def test_signalscope_version_remains_recorded_metadata(self) -> None:
        snapshot = self.evidence_snapshot()
        path = snapshot.path / MANIFEST_FILENAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["signalscope_version"] = "2.4.9"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.assertTrue(inspect_snapshot(snapshot.path, slug=SLUG).is_valid)  # format-checked only, as before


# ==========================================================================
# v2.6 - read-only comparison computation
# ==========================================================================


def _assert_same_refusal(test, from_run, to_run) -> None:
    """compute_snapshot_comparison and compare_snapshots refuse with the
    same exception and message, and nothing is written."""
    with test.assertRaises(AuditHistoryError) as computed:
        compute_snapshot_comparison(SLUG, from_run, to_run, audits_dir=test.audits, generated_at=GEN_DATE)
    with test.assertRaises(AuditHistoryError) as compared:
        test.compare(from_run, to_run)
    test.assertIs(type(computed.exception), type(compared.exception))
    test.assertEqual(str(computed.exception), str(compared.exception))
    test.assertFalse(test.comparisons.exists())


class ComputeSnapshotComparisonTests(_CompareTestCase):
    """The same full 40-vs-40 pair as CompareFullRunTests."""

    def setUp(self) -> None:
        super().setUp()
        self.run1 = self.run_and_snapshot(T1)
        self.analysis_overrides = {qid: NOT_CITED_JSON for qid in self.ids if qid[:2] in ("PA", "SD")}
        self.run2 = self.run_and_snapshot(T2, new_run=False)

    def compute(self, from_run=RUN_1, to_run=RUN_2):
        return compute_snapshot_comparison(SLUG, from_run, to_run, audits_dir=self.audits, generated_at=GEN_DATE)

    def test_a_structured_result(self) -> None:
        result = self.compute()
        self.assertIsInstance(result, SnapshotComparison)
        self.assertEqual((result.audit_slug, result.from_run, result.to_run), (SLUG, RUN_1, RUN_2))
        self.assertEqual((result.from_total, result.from_complete, result.to_total, result.to_complete), (40, 40, 40, 40))
        self.assertEqual((list(result.shared_question_ids), result.shared_question_count), (self.ids, 40))
        self.assertIsNone(result.requested_model_warning)
        self.assertIsNone(result.version_warning)
        self.assertEqual(metric_rows(result.progress), [
            ("Brand Visibility", "100.0%", "60.0%", "-40.0pp", "Declined"),
            ("Brand Mention Frequency", "40", "24", "-16", "Declined"),
            ("Competitor Mention Change", "40", "56", "+16", "Informational"),
            ("Sentiment Change (Positive Rate)", "100.0%", "60.0%", "-40.0pp", "Declined"),
            ("Authority Source Change", "100.0%", "60.0%", "-40.0pp", "Declined"),
            ("Funnel Stage Coverage", "5 of 5", "5 of 5", "+0", "No Change"),
            ("Overall GEO Maturity", "Established", "Established", "No change in tier", "No Change"),
        ])
        self.assertEqual(result.progress.generated_at, GEN_DATE)
        self.assertEqual(result.context, measurement_engine.RunComparisonContext(RUN_1, RUN_2, 40, 40, 40, 40, 40))
        self.assertEqual((result.config.slug, result.config.brand, result.config.report_subject),
                         (SLUG, self.config.brand, self.config.report_subject))
        self.assertEqual((result.from_snapshot.run_id, result.to_snapshot.run_id), (RUN_1, RUN_2))
        self.assertTrue(result.from_snapshot.is_valid and result.to_snapshot.is_valid)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.audit_slug = "other"  # type: ignore[misc]

    def test_b_computing_writes_nothing(self) -> None:
        before = tree(self.root)
        self.compute()
        self.assertEqual(tree(self.root), before)
        self.assertFalse(self.comparisons.exists())
        self.assertEqual([p for p in self.root.rglob("*") if p.suffix == ".tmp"], [])

    def test_c_no_gemini_and_no_env(self) -> None:
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        forbidden = AssertionError("Gemini or .env must not be touched by a comparison")
        with patch("gemini_client.generate_response", side_effect=forbidden), \
                patch("gemini_client._load_dotenv", side_effect=forbidden), \
                patch("recommendation_engine.generate_response", side_effect=forbidden):
            result = self.compute()
        self.assertEqual(result.shared_question_count, 40)
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()

    def test_d_same_refusals_as_the_report_path(self) -> None:
        _assert_same_refusal(self, RUN_2, RUN_1)  # wrong direction
        _assert_same_refusal(self, RUN_1, RUN_1)  # same run
        _assert_same_refusal(self, "2026-10-01", RUN_2)  # invalid run ID
        _assert_same_refusal(self, RUN_1, run_id_for(T3))  # missing snapshot
        with (self.run2.path / "audit_results.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        _assert_same_refusal(self, RUN_1, RUN_2)  # tampered snapshot

    def test_e_compare_writes_exactly_the_rendered_computation(self) -> None:
        computed = self.compute()
        result = self.compare()
        expected = measurement_engine.render_markdown(computed.progress, audit_config=computed.config, run_context=computed.context)
        self.assertEqual(result.output_path.read_text(encoding="utf-8"), expected)
        self.assertEqual(
            (result.audit_slug, result.from_run, result.to_run, result.from_total, result.from_complete,
             result.to_total, result.to_complete, result.shared_question_ids, result.requested_model_warning,
             result.version_warning, result.progress),
            (computed.audit_slug, computed.from_run, computed.to_run, computed.from_total, computed.from_complete,
             computed.to_total, computed.to_complete, computed.shared_question_ids,
             computed.requested_model_warning, computed.version_warning, computed.progress),
        )

    def test_f_compare_revalidates_immediately_before_writing(self) -> None:
        # The snapshot changes after the comparison was computed (and
        # validated) but before the report is written: nothing is written.
        for snapshot, run_id, side in ((self.run2, RUN_2, "to"), (self.run1, RUN_1, "from")):
            with self.subTest(side=side):
                real_render = audit_history.render_markdown
                results = snapshot.path / "audit_results.csv"
                original = results.read_bytes()

                def render_then_tamper(*args, **kwargs):
                    text = real_render(*args, **kwargs)
                    results.write_bytes(original + b"\n")
                    return text

                with patch("audit_history.render_markdown", side_effect=render_then_tamper), \
                        patch("audit_history._write_report_atomically") as write:
                    with self.assertRaises(SnapshotIntegrityError) as ctx:
                        self.compare()
                self.assertIn(f"Snapshot {run_id} ({side} run) changed during the comparison", str(ctx.exception))
                write.assert_not_called()
                self.assertFalse(self.comparisons.exists())
                results.write_bytes(original)
        self.assertTrue(self.compare().output_path.is_file())  # untouched snapshots still compare


class ComputeComparabilityTests(_CompareTestCase):
    """Refusals that need their own snapshot pairs."""

    def second_run(self, edit) -> None:
        self.run_and_snapshot(T1, limit=5, allow_partial=True)
        edit()
        self.run_and_snapshot(T2, limit=5, allow_partial=True, new_run=False)

    def test_core_config_changed(self) -> None:
        self.second_run(lambda: self.edit_config(brand="Lumiere Tea"))
        _assert_same_refusal(self, RUN_1, RUN_2)

    def test_competitors_reordered(self) -> None:
        self.second_run(lambda: self.edit_config(competitors=list(reversed(CREATION_DATA["competitors"]))))
        _assert_same_refusal(self, RUN_1, RUN_2)

    def test_question_text_changed(self) -> None:
        self.second_run(lambda: self.edit_questions(lambda rows: rows[0].update(question=rows[0]["question"] + "?")))
        _assert_same_refusal(self, RUN_1, RUN_2)

    def test_questions_reordered(self) -> None:
        def swap(rows):
            rows[0], rows[1] = rows[1], rows[0]
        self.second_run(lambda: self.edit_questions(swap))
        _assert_same_refusal(self, RUN_1, RUN_2)

    def test_zero_shared_questions(self) -> None:
        self.run_and_snapshot(T1, limit=8, allow_partial=True)
        self.failing_analysis.update(self.ids[:8])
        self.run_and_snapshot(T2, allow_partial=True, new_run=False)
        _assert_same_refusal(self, RUN_1, RUN_2)


if __name__ == "__main__":
    unittest.main()
