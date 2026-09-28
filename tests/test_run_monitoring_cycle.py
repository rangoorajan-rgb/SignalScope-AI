"""Tests for src/run_monitoring_cycle.py - v2.5: the monitoring planner, the
per-audit OS lock and --dry-run (Checkpoint A), and executing a cycle -
new-run, chunked collection with the spend breaker, and complete-run
snapshots (Checkpoint B), and the previous -> new comparison that completes
a recurring cycle (Checkpoint C).

Every audit is fictional, created with v2.2's create_audit_workspace in a
temporary directory; evidence is collected with the real v2.3 structured
batch with both Gemini paths faked, and the Gemini SDK is blocked. The API
key is never read from the real .env. The real audits/, reports/ and
master template are verified unchanged after every test, and no
.monitoring.lock may appear under the real audits/.
"""

from __future__ import annotations

import csv
import errno
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import create_audit  # noqa: E402
import run_monitoring_cycle  # noqa: E402
from audit_history import (  # noqa: E402
    STATE_COMPLETE,
    STATE_FRESH,
    STATE_IN_PROGRESS,
    STATE_RESET_INTERRUPTED,
    STATE_SNAPSHOTTED,
    NotComparableError,
    active_run_state,
    compare_snapshots,
    create_snapshot,
    inspect_snapshot,
    run_id_for,
    start_new_run,
)
from gemini_client import GeminiClientError  # noqa: E402
from run_monitoring_cycle import (  # noqa: E402
    CHUNK_SIZE,
    EXIT_ALREADY_RUNNING,
    EXIT_INCOMPLETE,
    EXIT_OK,
    EXIT_OPERATOR_ACTION,
    OUTCOME_INCOMPLETE,
    OUTCOME_NOT_DUE,
    OUTCOME_OPERATOR_ACTION,
    OUTCOME_READY,
    OUTCOME_COMPLETED,
    STEP_COLLECT,
    STEP_COMPARE,
    STEP_NEW_RUN,
    STEP_RECOVER_NEW_RUN,
    STEP_SNAPSHOT,
    STEP_SNAPSHOT_WHEN_COMPLETE,
    AuditLock,
    MonitoringError,
    MonitoringLockError,
    MonitoringLockHeld,
    is_due,
    is_retryable_failure,
    lock_path,
    plan_cycle,
    probe_lock,
)
from run_monitoring_cycle import run_monitoring_cycle as execute_cycle  # noqa: E402
from run_structured_batch_audit import evidence_path, run_structured_batch_audit  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, load_existing_results, write_results_atomically  # noqa: E402

SLUG = "lumiere-veloria-tea"
OTHER_SLUG = "brewvale-kettle-supplies"
BOOTS_SLUG = "boots-uk-health-beauty"
T1 = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(hours=1)
T3 = T1 + timedelta(hours=2)
RUN_1 = "20260601T090000Z"
RUN_2 = "20260601T100000Z"
INTERVAL = 30
SECRET = "test-secret-key-must-never-be-printed"

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


class _ProductionGuard(unittest.TestCase):
    """Blocks the Gemini SDK, keeps the real .env out of reach, and checks
    that nothing in the real project changes."""

    def setUp(self) -> None:
        guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini call attempted"))
        guard.start()
        self.addCleanup(guard.stop)
        before = production_snapshot()

        def check() -> None:
            self.assertEqual(production_snapshot(), before, "production audits/reports/template changed")
            self.assertEqual(list((REPO_ROOT / "audits").glob("*/.monitoring.lock")), [])

        self.addCleanup(check)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GEMINI_API_KEY", None)
        dotenv = patch("gemini_client.ENV_FILE", self.root / "absent.env")
        dotenv.start()
        self.addCleanup(dotenv.stop)


class _MonitoringTestCase(_ProductionGuard):
    """A fictional audit in a temporary project root, Gemini fully faked."""

    def setUp(self) -> None:
        super().setUp()
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
        self.lock_file = self.audit_dir / ".monitoring.lock"

        from audit_runner import load_questions
        self.questions = load_questions(self.questions_path)
        self.by_text = {q["question"]: q["question_id"] for q in self.questions}
        answer = patch("run_batch_audit.generate_response", side_effect=fake_answer)
        analysis = patch("response_analyzer.generate_response", side_effect=self._analysis)
        self.mock_answer = answer.start()
        self.mock_analysis = analysis.start()
        self.addCleanup(answer.stop)
        self.addCleanup(analysis.stop)

    def _analysis(self, prompt: str) -> str:
        return ANALYSIS_JSON

    # -- lifecycle helpers (the released v2.3/v2.4 functions) --

    def collect(self, limit=None, suffix: str = "") -> None:
        if suffix:
            self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + suffix
        with redirect_stdout(io.StringIO()):
            run_structured_batch_audit(self.questions_path, self.results_path, 0, limit,
                                       sleep_fn=lambda s: None, audit_config=self.config)

    def snapshot(self, when=T1, allow_partial=False):
        return create_snapshot(SLUG, audits_dir=self.audits, allow_partial=allow_partial, now=lambda: when)

    def new_run(self):
        return start_new_run(SLUG, audits_dir=self.audits)

    def compare(self, from_run=RUN_1, to_run=RUN_2):
        return compare_snapshots(SLUG, from_run, to_run, audits_dir=self.audits)

    def two_snapshots(self) -> None:
        self.collect()
        self.snapshot(when=T1)
        self.new_run()
        self.collect(suffix="Run two.")
        self.snapshot(when=T2)

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

    # -- planning helpers --

    def plan(self, now=T3, key=True, interval=INTERVAL):
        self.key_check = Mock(return_value=key)
        return plan_cycle(SLUG, interval, audits_dir=self.audits, now=lambda: now, api_key_present=self.key_check)

    def assert_operator_action(self, plan, fragment: str) -> None:
        self.assertEqual(plan.outcome, OUTCOME_OPERATOR_ACTION, plan)
        self.assertEqual(plan.exit_code, EXIT_OPERATOR_ACTION)
        self.assertEqual(plan.steps, ())
        self.assertTrue(any(fragment in r for r in plan.reasons), plan.reasons)

    def run_cli(self, argv, now=T3, key: str | None = None) -> tuple[int, str, str]:
        if key is not None:
            os.environ["GEMINI_API_KEY"] = key
        out, err = io.StringIO(), io.StringIO()
        with patch("audit_config.AUDITS_DIR", self.audits), patch("run_monitoring_cycle._utc_now", lambda: now), \
                redirect_stdout(out), redirect_stderr(err):
            code = run_monitoring_cycle.main(argv)
        return code, out.getvalue(), err.getvalue()

    def dry_run(self, now=T3, key: str | None = None) -> tuple[int, str, str, dict]:
        code, out, err = self.run_cli(["--audit", SLUG, "--interval-days", str(INTERVAL), "--dry-run"], now, key)
        return code, out, err, json.loads(out.strip().splitlines()[-1])


# --------------------------------------------------------------------------
# Start-state matrix
# --------------------------------------------------------------------------


class StartStateTests(_MonitoringTestCase):
    def test_state_f_blocks_before_everything(self) -> None:
        self.collect(limit=3)
        evidence_path(self.evidence_dir, self.questions[5]["question_id"]).write_text("{malformed", encoding="utf-8")
        plan = self.plan()
        self.assert_operator_action(plan, "Evidence integrity problems")
        self.assertEqual(plan.integrity_problems, 1)
        self.assertFalse(plan.requires_collection)
        self.key_check.assert_not_called()

    def test_no_baseline_snapshot(self) -> None:
        self.assert_operator_action(self.plan(), "snapshot the baseline run manually")
        self.collect(limit=5)  # evidence but still no snapshot
        plan = self.plan()
        self.assert_operator_action(plan, "No snapshot exists")
        self.assertFalse(plan.requires_collection)
        self.key_check.assert_not_called()

    def test_invalid_latest_snapshot_has_no_fallback(self) -> None:
        self.two_snapshots()
        with (self.snapshots_dir / RUN_2 / "audit_results.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        plan = self.plan()
        self.assert_operator_action(plan, f"latest snapshot {RUN_2} failed validation")
        self.assertEqual((plan.latest_snapshot, plan.previous_snapshot), (RUN_2, RUN_1))
        self.assertTrue(any("never skipped" in r for r in plan.reasons))

    def test_reset_interrupted(self) -> None:
        self.collect()
        self.snapshot()
        with patch("audit_history._write_fresh_results", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.new_run()
        plan = self.plan()
        self.assertEqual(plan.active_state, STATE_RESET_INTERRUPTED)
        self.assertEqual(plan.outcome, OUTCOME_READY)
        self.assertEqual(plan.steps, (STEP_RECOVER_NEW_RUN, STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE))
        self.assertTrue(plan.requires_collection and plan.requires_api_key)

    def test_fresh_after_new_run(self) -> None:
        self.collect()
        self.snapshot()
        self.new_run()
        plan = self.plan()
        self.assertEqual((plan.active_state, plan.outcome), (STATE_FRESH, OUTCOME_READY))
        self.assertEqual(plan.steps, (STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE))
        self.assertTrue(plan.requires_collection and plan.requires_api_key and plan.api_key_present)
        self.key_check.assert_called_once()

    def test_in_progress_with_actionable_questions(self) -> None:
        self.collect()
        self.snapshot()
        self.new_run()
        self.collect(limit=5, suffix="Run two.")
        plan = self.plan()
        self.assertEqual((plan.active_state, plan.outcome), (STATE_IN_PROGRESS, OUTCOME_READY))
        self.assertEqual(plan.steps, (STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE))
        self.assertIn("35 question(s) can still be collected", plan.reasons[0])

    def test_partial_with_nothing_actionable_needs_the_operator(self) -> None:
        self.collect()
        self.snapshot()
        self.new_run()
        self.collect(limit=39, suffix="Run two.")
        last = self.questions[39]
        legacy = {name: "" for name in RESULTS_SCHEMA}
        legacy.update({"run_date": "2026-06-02", "question_id": last["question_id"], "question": last["question"],
                       "funnel_stage": last["buyer_journey_stage"], "engine": "Gemini", "brand_cited": "N",
                       "answer_snippet": "Legacy answer."})  # structurally incomplete: never reprocessed
        write_results_atomically(self.results_path, load_existing_results(self.results_path) + [legacy])
        plan = self.plan()
        self.assertEqual(plan.active_state, STATE_IN_PROGRESS)
        self.assert_operator_action(plan, "no question can be collected automatically")
        self.assertTrue(any("--allow-partial" in r and "never accepts" in r for r in plan.reasons))
        self.assertFalse(plan.requires_collection)
        self.key_check.assert_not_called()

    def test_complete_unsnapshotted_needs_no_key(self) -> None:
        self.collect()
        self.snapshot()
        self.new_run()
        self.collect(suffix="Run two.")
        plan = self.plan(key=False)
        self.assertEqual((plan.active_state, plan.outcome), (STATE_COMPLETE, OUTCOME_READY))
        self.assertEqual(plan.steps, (STEP_SNAPSHOT, STEP_COMPARE))
        self.assertFalse(plan.requires_collection or plan.requires_api_key)
        self.key_check.assert_not_called()

    def test_complete_run_identical_to_an_older_snapshot(self) -> None:
        self.two_snapshots()
        self.new_run()
        self.mock_answer.side_effect = fake_answer
        self.collect()  # the same answers as run 1, on the same date
        self.assert_operator_action(self.plan(), f"identical to snapshot {RUN_1}")

    def test_snapshotted_with_missing_comparison_needs_no_key(self) -> None:
        self.two_snapshots()
        plan = self.plan(key=False)
        self.assertEqual((plan.active_state, plan.outcome), (STATE_SNAPSHOTTED, OUTCOME_READY))
        self.assertEqual(plan.steps, (STEP_COMPARE,))
        self.assertEqual((plan.previous_snapshot, plan.latest_snapshot), (RUN_1, RUN_2))
        self.key_check.assert_not_called()

    def test_invalid_previous_snapshot_blocks_the_comparison(self) -> None:
        self.two_snapshots()
        (self.snapshots_dir / RUN_1 / "reports" / "audit_report.md").write_text("tampered", encoding="utf-8")
        self.assert_operator_action(self.plan(), f"previous snapshot {RUN_1} failed validation")

    def test_new_baseline_after_methodology_change_expects_no_comparison(self) -> None:
        self.collect()
        self.snapshot()
        self.new_run()
        self.edit_config(brand="Lumiere Tea")
        self.collect(limit=5, suffix="Run two.")
        self.snapshot(when=T2, allow_partial=True)
        plan = self.plan()
        self.assertEqual(plan.outcome, OUTCOME_NOT_DUE)
        self.assertTrue(any("starts a new baseline" in r for r in plan.reasons))

    def test_baseline_only_single_snapshot(self) -> None:
        self.collect()
        self.snapshot()
        plan = self.plan(now=T1 + timedelta(days=1), key=False)
        self.assertEqual((plan.active_state, plan.outcome, plan.exit_code), (STATE_SNAPSHOTTED, OUTCOME_NOT_DUE, EXIT_OK))
        self.assertIsNone(plan.previous_snapshot)
        self.assertTrue(any("is the baseline" in r for r in plan.reasons))
        self.key_check.assert_not_called()
        due = self.plan(now=T1 + timedelta(days=INTERVAL))
        self.assertEqual(due.outcome, OUTCOME_READY)
        self.assertEqual(due.steps, (STEP_NEW_RUN, STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE))

    def test_snapshotted_comparison_present_not_due_then_due(self) -> None:
        self.two_snapshots()
        self.compare()
        plan = self.plan(now=T2 + timedelta(days=1), key=False)
        self.assertEqual((plan.outcome, plan.due, plan.exit_code), (OUTCOME_NOT_DUE, False, EXIT_OK))
        self.assertEqual(plan.steps, ())
        self.key_check.assert_not_called()
        due = self.plan(now=T2 + timedelta(days=INTERVAL))
        self.assertEqual((due.outcome, due.due), (OUTCOME_READY, True))
        self.assertEqual(due.steps, (STEP_NEW_RUN, STEP_COLLECT, STEP_SNAPSHOT_WHEN_COMPLETE, STEP_COMPARE))
        self.assertTrue(due.requires_collection and due.requires_api_key)

    def test_sequential_duplicate_trigger_is_not_due(self) -> None:
        # The state right after a completed cycle: new snapshot, comparison made.
        self.two_snapshots()
        self.compare()
        plan = self.plan(now=T2 + timedelta(minutes=1))
        self.assertEqual(plan.outcome, OUTCOME_NOT_DUE)
        self.assertFalse(plan.requires_collection)
        self.key_check.assert_not_called()

    def test_unreadable_audit_is_operator_action(self) -> None:
        (self.audit_dir / "audit_config.json").write_text("{broken", encoding="utf-8")
        self.assert_operator_action(self.plan(), "cannot be inspected")

    def test_planning_writes_nothing(self) -> None:
        self.two_snapshots()
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        for prepare in (lambda: None, self.compare):
            prepare()
            before = tree(self.root)
            for now in (T2, T2 + timedelta(days=INTERVAL)):
                self.plan(now=now)
            self.assertEqual(tree(self.root), before)
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()


# --------------------------------------------------------------------------
# Methodology pre-check
# --------------------------------------------------------------------------


class MethodologyPrecheckTests(_MonitoringTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.collect()
        self.snapshot()
        self.new_run()  # fresh: the next step would be a paid collection

    def assert_blocked(self, fragment: str) -> None:
        plan = self.plan()
        self.assert_operator_action(plan, "differs from the latest snapshot")
        self.assertTrue(any(fragment in d for d in plan.methodology_differences), plan.methodology_differences)
        self.key_check.assert_not_called()

    def test_brand_change(self) -> None:
        self.edit_config(brand="Lumiere Tea")
        self.assert_blocked("brand differs")

    def test_competitor_order_change(self) -> None:
        self.edit_config(competitors=list(reversed(CREATION_DATA["competitors"])))
        self.assert_blocked("competitor order differs")

    def test_question_text_change(self) -> None:
        self.edit_questions(lambda rows: rows[0].update(question=rows[0]["question"] + " Today?"))
        self.assert_blocked("PA01 question text differs")

    def test_question_order_change(self) -> None:
        def swap(rows):
            rows[0], rows[1] = rows[1], rows[0]
        self.edit_questions(swap)
        self.assert_blocked("question order differs")

    def test_display_only_changes_are_allowed(self) -> None:
        self.edit_config(company_name="Lumière Holdings", report_subject="Lumière Holdings Tea",
                         question_library="Renamed Library")
        self.edit_questions(lambda rows: rows[0].update(intent="Changed.", notes="Changed."))
        plan = self.plan()
        self.assertEqual(plan.outcome, OUTCOME_READY)
        self.assertEqual(plan.methodology_differences, ())

    def test_change_made_after_the_snapshot(self) -> None:
        # Complete run whose config changed after collection: still refused.
        self.collect(suffix="Run two.")
        self.edit_config(market="Veloria North")
        plan = self.plan()
        self.assertEqual(plan.active_state, STATE_COMPLETE)
        self.assertTrue(any("market differs" in d for d in plan.methodology_differences))
        self.assertEqual(plan.outcome, OUTCOME_OPERATOR_ACTION)


# --------------------------------------------------------------------------
# API key ordering
# --------------------------------------------------------------------------


class ApiKeyOrderingTests(_MonitoringTestCase):
    def test_a_due_cycle_without_a_key_stops_before_new_run(self) -> None:
        self.two_snapshots()
        self.compare()
        before = tree(self.root)
        plan = self.plan(now=T2 + timedelta(days=INTERVAL), key=False)
        self.assert_operator_action(plan, "no Gemini API key is configured")
        self.assertTrue(plan.requires_collection and plan.requires_api_key)
        self.assertIs(plan.api_key_present, False)
        self.assertNotIn(STEP_NEW_RUN, plan.steps)
        self.assertEqual(tree(self.root), before)

    def test_fresh_collection_without_a_key(self) -> None:
        self.collect()
        self.snapshot()
        self.new_run()
        self.assert_operator_action(self.plan(key=False), "no Gemini API key is configured")

    def test_b_complete_snapshot_needs_no_key(self) -> None:
        self.collect()
        self.snapshot()
        self.new_run()
        self.collect(suffix="Run two.")
        plan = self.plan(key=False)
        self.assertEqual((plan.outcome, plan.steps), (OUTCOME_READY, (STEP_SNAPSHOT, STEP_COMPARE)))
        self.key_check.assert_not_called()

    def test_c_missing_comparison_needs_no_key(self) -> None:
        self.two_snapshots()
        plan = self.plan(key=False)
        self.assertEqual((plan.outcome, plan.steps), (OUTCOME_READY, (STEP_COMPARE,)))
        self.key_check.assert_not_called()

    def test_d_not_due_needs_no_key(self) -> None:
        self.two_snapshots()
        self.compare()
        plan = self.plan(now=T2 + timedelta(days=2), key=False)
        self.assertEqual(plan.outcome, OUTCOME_NOT_DUE)
        self.key_check.assert_not_called()

    def test_key_presence_reads_the_configured_source_without_calling_gemini(self) -> None:
        self.assertFalse(run_monitoring_cycle.gemini_api_key_present())
        env_file = self.root / "test.env"
        env_file.write_text(f"GEMINI_API_KEY={SECRET}\n", encoding="utf-8")
        with patch("gemini_client.ENV_FILE", env_file):
            self.assertIs(run_monitoring_cycle.gemini_api_key_present(), True)


# --------------------------------------------------------------------------
# Due calculation
# --------------------------------------------------------------------------


class DueTests(_MonitoringTestCase):
    def test_boundaries(self) -> None:
        interval = timedelta(days=INTERVAL)
        self.assertFalse(is_due(T1, T1 + interval - timedelta(seconds=1), INTERVAL))
        self.assertTrue(is_due(T1, T1 + interval, INTERVAL))
        self.assertTrue(is_due(T1, T1 + interval + timedelta(days=5), INTERVAL))
        self.assertFalse(is_due(T1, T1 + timedelta(hours=23), 1))
        self.assertTrue(is_due(T1, T1 + timedelta(days=1), 1))
        self.assertFalse(is_due(T1, T1 - timedelta(days=1), 1))  # clock earlier than the snapshot

    def test_utc_offsets_are_compared_as_instants(self) -> None:
        plus_two = timezone(timedelta(hours=2))
        self.assertTrue(is_due(T1, (T1 + timedelta(days=1)).astimezone(plus_two), 1))

    def test_invalid_intervals(self) -> None:
        for bad in (0, -1, True, 1.5, "30", None):
            with self.subTest(bad=bad):
                with self.assertRaises(MonitoringError):
                    is_due(T1, T2, bad)
                with self.assertRaises(MonitoringError):
                    plan_cycle(SLUG, bad, audits_dir=self.audits, now=lambda: T2)

    def test_naive_times_refused(self) -> None:
        naive = datetime(2026, 7, 1, 9, 0, 0)
        with self.assertRaises(MonitoringError):
            is_due(T1, naive, 1)
        with self.assertRaises(MonitoringError):
            is_due(naive, T2, 1)
        with self.assertRaises(MonitoringError):
            plan_cycle(SLUG, INTERVAL, audits_dir=self.audits, now=lambda: naive)

    def test_plan_boundary_from_the_snapshot_run_id(self) -> None:
        self.collect()
        self.snapshot(when=T1)
        exact = T1 + timedelta(days=INTERVAL)
        self.assertEqual(self.plan(now=exact - timedelta(seconds=1)).outcome, OUTCOME_NOT_DUE)
        self.assertEqual(self.plan(now=exact).outcome, OUTCOME_READY)
        self.assertEqual(self.plan(now=exact + timedelta(days=90)).steps[0], STEP_NEW_RUN)  # one cycle, no catch-up


# --------------------------------------------------------------------------
# Dry-run CLI
# --------------------------------------------------------------------------


class DryRunTests(_MonitoringTestCase):
    def test_first_run_needs_a_manual_baseline(self) -> None:
        before = tree(self.root)
        code, out, _, summary = self.dry_run(key=SECRET)
        self.assertEqual(code, EXIT_OPERATOR_ACTION)
        self.assertIn("snapshot the baseline run manually", out)
        self.assertEqual((summary["outcome"], summary["exit_code"]), (OUTCOME_OPERATOR_ACTION, 1))
        self.assertFalse(summary["requires_collection"])
        self.assertEqual(tree(self.root), before)
        self.assertFalse(self.lock_file.exists())
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()

    def test_dry_run_writes_nothing_in_any_state(self) -> None:
        def reset_interrupted():
            self.collect()
            self.snapshot()
            with patch("audit_history._write_fresh_results", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    self.new_run()

        scenarios = {
            "fresh": lambda: (self.collect(), self.snapshot(), self.new_run()),
            "reset interrupted": reset_interrupted,
            "comparison missing": self.two_snapshots,
            "due": lambda: (self.two_snapshots(), self.compare()),
        }
        for name, prepare in scenarios.items():
            with self.subTest(state=name):
                shutil.rmtree(self.audit_dir)
                shutil.rmtree(self.root / "reports", ignore_errors=True)
                self.setUp_audit_again()
                prepare()
                self.mock_answer.reset_mock()
                self.mock_analysis.reset_mock()
                before = tree(self.root)
                self.dry_run(now=T2 + timedelta(days=INTERVAL), key=SECRET)
                self.assertEqual(tree(self.root), before)
                self.assertFalse(self.lock_file.exists())
                self.mock_answer.assert_not_called()
                self.mock_analysis.assert_not_called()

    def setUp_audit_again(self) -> None:
        create_audit.create_audit_workspace(CREATION_DATA, audits_dir=self.audits, reports_dir=self.root / "reports")
        self.mock_answer.side_effect = fake_answer

    def test_due_cycle_report_and_summary(self) -> None:
        self.two_snapshots()
        self.compare()
        code, out, err, summary = self.dry_run(now=T2 + timedelta(days=INTERVAL), key=SECRET)
        self.assertEqual(code, EXIT_OK, err)
        for line in ("DRY RUN - no Gemini call, no file change.", f"Audit: {SLUG}", "Current run: snapshotted",
                     "Evidence integrity problems: 0", f"Latest snapshot: {RUN_2}", f"Previous snapshot: {RUN_1}",
                     f"Due (interval {INTERVAL} day(s)): yes", "Methodology: no differences found",
                     "Collection required: yes", "Gemini API key: configured",
                     "Monitoring lock held by another process: no",
                     "Planned actions: new-run -> collect -> snapshot when complete -> compare",
                     "Outcome: ready (exit code 0)"):
            self.assertIn(line, out)
        self.assertEqual(summary, {
            "audit_slug": SLUG, "mode": "dry-run", "outcome": OUTCOME_READY,
            "action": "new-run -> collect -> snapshot when complete -> compare",
            "active_state": STATE_SNAPSHOTTED, "due": True, "requires_collection": True,
            "latest_snapshot": RUN_2, "previous_snapshot": RUN_1, "lock_held": False, "exit_code": 0,
        })
        self.assertNotIn(SECRET, out + err)

    def test_missing_key_reported_without_value(self) -> None:
        self.two_snapshots()
        self.compare()
        code, out, _, summary = self.dry_run(now=T2 + timedelta(days=INTERVAL))
        self.assertEqual(code, EXIT_OPERATOR_ACTION)
        self.assertIn("Gemini API key: NOT configured", out)
        self.assertEqual(summary["action"], "none")

    def test_not_due_is_success(self) -> None:
        self.two_snapshots()
        self.compare()
        code, out, _, summary = self.dry_run(now=T2 + timedelta(days=1))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual((summary["outcome"], summary["due"]), (OUTCOME_NOT_DUE, False))
        self.assertNotIn("Gemini API key", out)

    def test_lock_held_reports_already_running(self) -> None:
        self.two_snapshots()
        self.compare()
        with AuditLock(self.lock_file) as lock:
            lock.acquire(SLUG)
            before = tree(self.root)
            code, out, _, summary = self.dry_run(now=T2 + timedelta(days=INTERVAL), key=SECRET)
            self.assertEqual(tree(self.root), before)
        self.assertEqual(code, EXIT_ALREADY_RUNNING)
        self.assertIn("Monitoring lock held by another process: yes", out)
        self.assertEqual((summary["outcome"], summary["lock_held"], summary["exit_code"]), ("already running", True, 3))

    def test_existing_unlocked_lock_file_is_probed_without_change(self) -> None:
        self.two_snapshots()
        self.lock_file.write_text('{"audit_slug": "old"}\n', encoding="utf-8")
        before = tree(self.root)
        code, _, _, summary = self.dry_run(key=SECRET)
        self.assertEqual(tree(self.root), before)
        self.assertIs(summary["lock_held"], False)
        self.assertEqual(code, EXIT_OK)

    def test_unprovable_lock_fails_closed(self) -> None:
        self.two_snapshots()
        self.lock_file.write_text("", encoding="utf-8")
        with patch("run_monitoring_cycle._os_try_lock", side_effect=OSError(errno.EINVAL, "not supported")):
            code, _, err, summary = self.dry_run(key=SECRET)
        self.assertEqual(code, EXIT_OPERATOR_ACTION)
        self.assertIn("Could not lock", err)
        self.assertIsNone(summary["lock_held"])

    def test_argument_errors(self) -> None:
        for argv in ([], ["--audit", SLUG], ["--interval-days", "30"], ["--audit", SLUG, "--interval-days", "0"],
                     ["--audit", SLUG, "--interval-days", "-3"], ["--audit", SLUG, "--interval-days", "abc"],
                     ["--audit", SLUG, "--interval-days", "1.5"],
                     ["--audit", SLUG, "--interval-days", "30", "--force"]):
            with self.subTest(argv=argv):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        run_monitoring_cycle.main(argv)
                self.assertEqual(ctx.exception.code, 2)

    def test_invalid_and_unknown_audits(self) -> None:
        code, _, err = self.run_cli(["--audit", "../x", "--interval-days", "30", "--dry-run"])
        self.assertEqual(code, EXIT_OPERATOR_ACTION)
        self.assertIn("Invalid audit slug", err)
        code, out, _ = self.run_cli(["--audit", "no-such-audit", "--interval-days", "30", "--dry-run"])
        self.assertEqual(code, EXIT_OPERATOR_ACTION)
        self.assertIn("Unknown audit", out)
        self.assertFalse((self.audits / "no-such-audit").exists())


# --------------------------------------------------------------------------
# Per-audit lock
# --------------------------------------------------------------------------


class LockTests(_ProductionGuard):
    def setUp(self) -> None:
        super().setUp()
        self.audits = self.root / "audits"
        for slug in (SLUG, OTHER_SLUG):
            (self.audits / slug).mkdir(parents=True)
        self.path = lock_path(SLUG, audits_dir=self.audits)

    def test_path(self) -> None:
        self.assertEqual(self.path, self.audits / SLUG / ".monitoring.lock")
        with self.assertRaises(MonitoringError):
            lock_path("../escape", audits_dir=self.audits)

    def test_a_same_audit_second_acquisition_fails(self) -> None:
        with AuditLock(self.path) as first:
            first.acquire(SLUG)
            with self.assertRaises(MonitoringLockHeld):
                AuditLock(self.path).acquire(SLUG)
            self.assertTrue(probe_lock(self.path))

    def test_b_release_then_reacquire(self) -> None:
        first = AuditLock(self.path)
        first.acquire(SLUG)
        first.release()
        self.assertFalse(first.held)
        self.assertTrue(self.path.exists())
        self.assertFalse(probe_lock(self.path))
        with AuditLock(self.path) as second:
            second.acquire(SLUG)
            self.assertTrue(second.held)
        self.assertFalse(probe_lock(self.path))

    def test_c_killed_process_releases_the_lock(self) -> None:
        code = (
            "import sys, time; sys.path.insert(0, {src!r}); import run_monitoring_cycle as m; "
            "lock = m.AuditLock({path!r}); lock.acquire({slug!r}); print('locked', flush=True); time.sleep(120)"
        ).format(src=str(SRC_DIR), path=str(self.path), slug=SLUG)
        process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            self.assertTrue(probe_lock(self.path))
            with self.assertRaises(MonitoringLockHeld):
                AuditLock(self.path).acquire(SLUG)
        finally:
            process.kill()
            process.wait(timeout=60)
            process.stdout.close()
        self.assertTrue(self.path.exists())  # the file stays; only the OS lock is gone
        with AuditLock(self.path) as lock:
            lock.acquire(SLUG)
            self.assertTrue(lock.held)

    def test_d_existing_unlocked_file_is_reused(self) -> None:
        self.path.write_text("left over from an earlier cycle\n", encoding="utf-8")
        with AuditLock(self.path) as lock:
            lock.acquire(SLUG)
            metadata = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["audit_slug"], SLUG)

    def test_e_different_audits_do_not_block_each_other(self) -> None:
        other = lock_path(OTHER_SLUG, audits_dir=self.audits)
        with AuditLock(self.path) as first, AuditLock(other) as second:
            first.acquire(SLUG)
            second.acquire(OTHER_SLUG)
            self.assertTrue(first.held and second.held)

    def test_f_metadata_is_diagnostic_and_holds_no_secret(self) -> None:
        os.environ["GEMINI_API_KEY"] = SECRET
        with AuditLock(self.path) as lock:
            lock.acquire(SLUG)
            text = self.path.read_text(encoding="utf-8")
        metadata = json.loads(text)
        self.assertEqual(set(metadata), {"audit_slug", "started_at", "process_id", "hostname", "signalscope_version"})
        self.assertEqual(metadata["process_id"], os.getpid())
        self.assertNotIn(SECRET, text)

    def test_g_metadata_and_age_are_never_used_to_decide(self) -> None:
        # Metadata claiming a live owner does not block an unheld lock...
        self.path.write_text(json.dumps({"process_id": os.getpid(), "started_at": "2099-01-01T00:00:00Z"}),
                             encoding="utf-8")
        with AuditLock(self.path) as lock:
            lock.acquire(SLUG)
            # ...and an ancient-looking held lock still blocks.
            os.utime(self.path, (0, 0))
            with self.assertRaises(MonitoringLockHeld):
                AuditLock(self.path).acquire(SLUG)
        source = Path(run_monitoring_cycle.__file__).read_text(encoding="utf-8")
        for forbidden in ("os.kill", "getmtime", "st_mtime", "unlink", "remove("):
            self.assertNotIn(forbidden, source)

    def test_lock_failure_fails_closed(self) -> None:
        with patch("run_monitoring_cycle._os_try_lock", side_effect=OSError(errno.EINVAL, "unsupported")):
            with self.assertRaises(MonitoringLockError):
                AuditLock(self.path).acquire(SLUG)
            self.path.write_text("", encoding="utf-8")
            with self.assertRaises(MonitoringLockError):
                probe_lock(self.path)
        with AuditLock(self.path) as lock:  # the failed attempt left no open handle behind
            lock.acquire(SLUG)
        with self.assertRaises(MonitoringLockError):
            AuditLock(self.audits / "missing-audit" / ".monitoring.lock").acquire("missing-audit")

    def test_probe_never_creates_the_file(self) -> None:
        self.assertFalse(probe_lock(self.path))
        self.assertFalse(self.path.exists())


# --------------------------------------------------------------------------
# Governance
# --------------------------------------------------------------------------


class GovernanceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git") and (REPO_ROOT / ".git").exists(), "git repository not available")
    def test_lock_file_is_never_tracked(self) -> None:
        expected = {
            f"audits/{BOOTS_SLUG}/.monitoring.lock": True,
            "audits/client-x/.monitoring.lock": True,
            f"audits/{BOOTS_SLUG}/audit_config.json": False,
            f"audits/{BOOTS_SLUG}/buyer_questions.csv": False,
            f"audits/{BOOTS_SLUG}/audit_results.csv": False,
            f"reports/{BOOTS_SLUG}/GEO_PROGRESS.md": False,
            "src/run_monitoring_cycle.py": False,
        }
        for path, ignored in expected.items():
            with self.subTest(path=path):
                completed = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True)
                self.assertEqual(completed.returncode, 0 if ignored else 1, completed.stderr)

    def test_module_has_no_client_literals(self) -> None:
        source = Path(run_monitoring_cycle.__file__).read_text(encoding="utf-8")
        for marker in ["Boots", "Superdrug", "Amazon", "Holland & Barrett", "United Kingdom", BOOTS_SLUG]:
            self.assertNotIn(marker, source)


# ==========================================================================
# Checkpoint B - executing a cycle (new-run, collection, complete snapshot)
# ==========================================================================

DUE = T1 + timedelta(days=INTERVAL)
RUN_DUE = "20260701T090000Z"
RETRYABLE = "Gemini API call failed: 503 UNAVAILABLE. The model is overloaded."
PERMANENT = "Gemini API call failed: 401 UNAUTHENTICATED. API key not valid."


def without_lock(snapshot: dict[str, bytes | None]) -> dict[str, bytes | None]:
    return {k: v for k, v in snapshot.items() if not k.endswith(".monitoring.lock")}


class _ExecutorTestCase(_MonitoringTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.failing_analysis: set[str] = set()
        self.ids = [q["question_id"] for q in self.questions]
        self.text_of = {q["question_id"]: q["question"] for q in self.questions}

    def _analysis(self, prompt: str) -> str:
        question_id = next((qid for text, qid in self.by_text.items() if repr(text) in prompt), None)
        if question_id in self.failing_analysis:
            return '{"malformed": true, "note": "error 500 in the text must not look retryable"'
        return ANALYSIS_JSON

    def cycle(self, now=T3, key=True, slug=SLUG):
        self.key_check = Mock(return_value=key)
        with redirect_stdout(io.StringIO()):
            return execute_cycle(slug, INTERVAL, audits_dir=self.audits, now=lambda: now,
                                 api_key_present=self.key_check, sleep_fn=lambda s: None,
                                 request_delay_seconds=0)

    def baseline(self) -> None:
        self.collect()
        self.snapshot(when=T1)
        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run two."
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()

    def state(self) -> str:
        return active_run_state(SLUG, audits_dir=self.audits).state

    def answer_calls_for(self, question_id: str) -> int:
        return sum(1 for c in self.mock_answer.call_args_list if c.args[0] == self.text_of[question_id])

    def snapshot_ids(self) -> list[str]:
        return sorted(p.name for p in self.snapshots_dir.iterdir() if not p.name.startswith("."))

    def assert_lock_free(self) -> None:
        self.assertFalse(probe_lock(self.lock_file))

    def failing_answers(self, failing_ids, message):
        def answer(prompt: str) -> str:
            question_id = next(qid for qid, text in self.text_of.items() if text == prompt)
            if question_id in failing_ids:
                raise GeminiClientError(message)
            return fake_answer(prompt) + "Run two."
        self.mock_answer.side_effect = answer


class ExecutorLifecycleTests(_ExecutorTestCase):
    def test_happy_path_due_cycle(self) -> None:
        self.baseline()
        baseline_bytes = tree(self.snapshots_dir / RUN_1)
        calls = []
        real_batch = run_monitoring_cycle.run_structured_batch_audit

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            self.assertTrue(probe_lock(self.lock_file), "the lock must be held during collection")
            return real_batch(*args, **kwargs)

        with patch("run_monitoring_cycle.run_structured_batch_audit", side_effect=spy):
            result = self.cycle(now=DUE)

        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK), result.reasons)
        self.assertEqual(result.new_snapshot, RUN_DUE)
        self.assertEqual(self.mock_answer.call_count, 40)
        self.assertEqual(self.mock_analysis.call_count, 40)
        self.assertEqual(len(calls), 8)
        self.assertTrue(all(args[3] == CHUNK_SIZE for args, _ in calls))
        self.assertEqual(result.actions_taken[0], f"new-run (previous run preserved in snapshot {RUN_1})")
        self.assertEqual(result.actions_taken[-2:], (f"snapshot {RUN_DUE} created",
                                                     f"comparison {RUN_1} -> {RUN_DUE} created"))
        self.assertEqual(tree(self.snapshots_dir / RUN_1), baseline_bytes)
        self.assertTrue(inspect_snapshot(self.snapshots_dir / RUN_DUE, slug=SLUG).is_valid)
        self.assertEqual(result.final_state, STATE_SNAPSHOTTED)
        for path in (self.snapshots_dir / RUN_DUE / "raw_responses").iterdir():
            text = json.loads(path.read_text(encoding="utf-8"))["raw_response_text"]
            self.assertTrue(text.endswith("Run two."))  # a fresh answer, never baseline evidence
        comparison = self.root / "reports" / SLUG / "comparisons" / f"{RUN_1}__{RUN_DUE}" / "GEO_PROGRESS.md"
        self.assertEqual(result.comparison_path, comparison)
        self.assertTrue(comparison.is_file())
        self.key_check.assert_called()
        self.assert_lock_free()

    def test_batch_receives_absolute_audit_paths(self) -> None:
        self.baseline()
        self.new_run()
        seen = []
        real_batch = run_monitoring_cycle.run_structured_batch_audit

        def spy(*args, **kwargs):
            seen.append(args[:2])
            return real_batch(*args, **kwargs)

        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        cwd = os.getcwd()
        os.chdir(elsewhere.name)
        try:
            with patch("run_monitoring_cycle.run_structured_batch_audit", side_effect=spy):
                result = self.cycle()
        finally:
            os.chdir(cwd)
        self.assertEqual(result.exit_code, EXIT_OK, result.reasons)
        expected = (str(self.audit_dir.resolve() / "buyer_questions.csv"),
                    str(self.audit_dir.resolve() / "audit_results.csv"))
        self.assertTrue(seen and all(paths == expected for paths in seen))
        self.assertTrue(Path(seen[0][0]).is_absolute())
        self.assertEqual(list(Path(elsewhere.name).iterdir()), [])

    def test_resume_17_of_40_without_new_run(self) -> None:
        self.baseline()
        self.new_run()
        self.collect(limit=17)
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        result = self.cycle()
        self.assertEqual(result.exit_code, EXIT_OK, result.reasons)
        self.assertNotIn("new-run", " ".join(result.actions_taken))
        self.assertEqual(self.mock_answer.call_count, 23)
        self.assertEqual(self.mock_analysis.call_count, 23)
        self.assertEqual(sum(self.answer_calls_for(q) for q in self.ids[:17]), 0)
        self.assertEqual(self.snapshot_ids(), [RUN_1, run_id_for(T3)])

    def test_state_b_is_analysed_from_stored_evidence(self) -> None:
        self.baseline()
        self.new_run()
        stored = self.ids[2]
        self.failing_analysis.add(stored)
        self.collect(limit=3)  # PA03's answer is stored, its analysis failed
        self.failing_analysis.clear()
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        result = self.cycle()
        self.assertEqual(result.exit_code, EXIT_OK, result.reasons)
        self.assertEqual(self.answer_calls_for(stored), 0)
        self.assertEqual(self.mock_answer.call_count, 37)
        self.assertEqual(self.mock_analysis.call_count, 38)

    def test_complete_run_is_snapshotted_without_a_key_or_gemini(self) -> None:
        self.baseline()
        self.new_run()
        self.collect()
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        result = self.cycle(key=False)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK))
        self.assertEqual(result.new_snapshot, run_id_for(T3))
        self.key_check.assert_not_called()
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()

    def test_due_without_a_key_changes_nothing(self) -> None:
        self.baseline()
        before = tree(self.root)
        result = self.cycle(now=DUE, key=False)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION))
        self.assertEqual(result.actions_taken, ())
        self.assertEqual(without_lock(tree(self.root)), before)
        self.assertEqual(result.final_state, STATE_SNAPSHOTTED)
        self.mock_answer.assert_not_called()
        self.assert_lock_free()

    def test_not_due_does_nothing(self) -> None:
        self.baseline()
        before = tree(self.root)
        result = self.cycle(now=T1 + timedelta(days=2))
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_NOT_DUE, EXIT_OK))
        self.assertEqual(without_lock(tree(self.root)), before)
        self.mock_answer.assert_not_called()

    def test_reset_interrupted_is_recovered_then_collected(self) -> None:
        self.baseline()
        baseline_bytes = tree(self.snapshots_dir / RUN_1)
        with patch("audit_history._write_fresh_results", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.new_run()
        result = self.cycle()
        self.assertEqual(result.exit_code, EXIT_OK, result.reasons)
        self.assertTrue(result.actions_taken[0].startswith("finished interrupted new-run"))
        self.assertEqual(self.mock_answer.call_count, 40)
        self.assertEqual(sorted(self.snapshots_dir.glob(".retired-raw-*")), [])
        self.assertEqual(tree(self.snapshots_dir / RUN_1), baseline_bytes)
        for path in (self.snapshots_dir / result.new_snapshot / "raw_responses").iterdir():
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["raw_response_text"].endswith("Run two."))

    def test_duplicate_of_an_older_snapshot_is_refused(self) -> None:
        self.two_snapshots()
        self.new_run()
        self.mock_answer.side_effect = fake_answer
        self.collect()
        snapshots_before = tree(self.snapshots_dir)
        self.mock_answer.reset_mock()
        result = self.cycle()
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertTrue(any("identical to snapshot" in r for r in result.reasons))
        self.assertEqual(tree(self.snapshots_dir), snapshots_before)
        self.mock_answer.assert_not_called()

    def test_rebaseline_runs_from_the_latest_snapshot_without_comparing(self) -> None:
        self.collect()
        self.snapshot(when=T1)
        self.new_run()
        self.edit_config(brand="Lumiere Tea")
        self.collect(suffix="Rebaselined.")
        self.snapshot(when=T2)
        self.assertEqual(self.cycle(now=T2 + timedelta(days=1)).outcome, OUTCOME_NOT_DUE)
        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run three."
        self.mock_answer.reset_mock()
        result = self.cycle(now=T2 + timedelta(days=INTERVAL))
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK), result.reasons)
        self.assertEqual(result.actions_taken[0], f"new-run (previous run preserved in snapshot {RUN_2})")
        self.assertEqual(self.mock_answer.call_count, 40)
        new = run_id_for(T2 + timedelta(days=INTERVAL))
        self.assertEqual(sorted(p.name for p in (self.root / "reports" / SLUG / "comparisons").iterdir()),
                         [f"{RUN_2}__{new}"])

    def test_snapshot_is_always_requested_with_allow_partial_false(self) -> None:
        self.baseline()
        self.new_run()
        self.collect()  # complete, not snapshotted
        self.mock_answer.reset_mock()
        with patch("run_monitoring_cycle.create_snapshot", wraps=run_monitoring_cycle.create_snapshot) as spy:
            result = self.cycle(key=False)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK), result.reasons)
        spy.assert_called_once()
        self.assertEqual(spy.call_args.args, (SLUG,))
        self.assertEqual(Path(spy.call_args.kwargs["audits_dir"]), self.audits)
        self.assertIs(spy.call_args.kwargs["allow_partial"], False)
        self.assertFalse(any(c.kwargs.get("allow_partial") is not False for c in spy.call_args_list))
        self.assertTrue(inspect_snapshot(self.snapshots_dir / result.new_snapshot, slug=SLUG).is_valid)
        self.mock_answer.assert_not_called()

    def test_cycle_replans_after_new_run(self) -> None:
        # The key disappears while new-run runs: the plan made after the
        # reset must see it and stop before any collection.
        self.baseline()
        baseline_bytes = tree(self.snapshots_dir / RUN_1)
        key = {"present": True}
        real_new_run = run_monitoring_cycle.start_new_run

        def reset_then_lose_key(*args, **kwargs):
            outcome = real_new_run(*args, **kwargs)
            key["present"] = False
            return outcome

        with patch("run_monitoring_cycle.start_new_run", side_effect=reset_then_lose_key),                 redirect_stdout(io.StringIO()):
            result = execute_cycle(SLUG, INTERVAL, audits_dir=self.audits, now=lambda: DUE,
                                   api_key_present=lambda: key["present"], sleep_fn=lambda s: None,
                                   request_delay_seconds=0)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION))
        self.assertEqual(result.actions_taken, (f"new-run (previous run preserved in snapshot {RUN_1})",))
        self.assertTrue(any("no Gemini API key is configured" in r for r in result.reasons), result.reasons)
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()
        self.assertEqual(self.snapshot_ids(), [RUN_1])
        self.assertEqual(tree(self.snapshots_dir / RUN_1), baseline_bytes)
        self.assertEqual((result.final_state, self.state()), (STATE_FRESH, STATE_FRESH))
        self.assertFalse((self.root / "reports" / SLUG / "comparisons").exists())
        self.assert_lock_free()

    def test_collected_run_identical_to_the_latest_snapshot_is_refused(self) -> None:
        self.baseline()
        self.mock_answer.side_effect = fake_answer  # exactly the baseline's answers, on the same date
        result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertTrue(any(f"already snapshotted as {RUN_1}" in r for r in result.reasons), result.reasons)
        self.assertEqual(self.snapshot_ids(), [RUN_1])

    def test_methodology_change_blocks_before_new_run(self) -> None:
        self.baseline()
        self.edit_config(competitors=list(reversed(CREATION_DATA["competitors"])))  # after the snapshot
        result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertEqual(result.actions_taken, ())
        self.mock_answer.assert_not_called()


class CircuitBreakerTests(_ExecutorTestCase):
    def test_retryable_outage_stops_after_one_unproductive_chunk_then_resumes(self) -> None:
        self.baseline()
        self.failing_answers(set(self.ids[5:]), RETRYABLE)
        result = self.cycle(now=DUE)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_INCOMPLETE, EXIT_INCOMPLETE), result.reasons)
        # Chunk 1: 5 answers. Chunk 2: 5 questions x 3 attempts, no progress -> stop.
        self.assertEqual(self.mock_answer.call_count, 5 + 15)
        self.assertEqual(self.snapshot_ids(), [RUN_1])
        self.assertEqual(result.final_state, STATE_IN_PROGRESS)
        self.assert_lock_free()

        # The next (healthy) trigger resumes: no call for the 5 completed questions.
        self.failing_answers(set(), RETRYABLE)
        self.mock_answer.reset_mock()
        resumed = self.cycle(now=DUE + timedelta(days=1))
        self.assertEqual(resumed.exit_code, EXIT_OK, resumed.reasons)
        self.assertNotIn("new-run", " ".join(resumed.actions_taken))
        self.assertEqual(self.mock_answer.call_count, 35)
        self.assertEqual(sum(self.answer_calls_for(q) for q in self.ids[:5]), 0)

    def test_permanent_failure_stops_with_operator_action(self) -> None:
        self.baseline()
        self.failing_answers(set(self.ids), PERMANENT)
        result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertEqual(self.mock_answer.call_count, 5)  # not retried, no second chunk
        self.assertEqual(self.snapshot_ids(), [RUN_1])
        self.assertTrue(any("401" in r for r in result.reasons))

    def test_malformed_analysis_is_never_classified_as_retryable(self) -> None:
        self.baseline()
        self.failing_analysis.update(self.ids)
        result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertEqual(self.mock_answer.call_count, 5)  # answers stored once (A -> B is progress)
        self.assertEqual(self.mock_analysis.call_count, 10)  # re-analysed once, then the breaker trips
        self.assertEqual(self.snapshot_ids(), [RUN_1])

    def test_one_failing_question_does_not_stop_the_others(self) -> None:
        self.baseline()
        stubborn = self.ids[7]
        self.failing_answers({stubborn}, "Gemini API call failed: 400 INVALID_ARGUMENT")
        result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertEqual(self.mock_answer.call_count - self.answer_calls_for(stubborn), 39)
        self.assertLessEqual(self.answer_calls_for(stubborn), 10)
        self.assertEqual(self.snapshot_ids(), [RUN_1])
        self.assertEqual(result.final_state, STATE_IN_PROGRESS)

    def test_partial_with_nothing_left_is_not_snapshotted(self) -> None:
        self.baseline()
        self.new_run()
        last = self.questions[39]
        legacy = {name: "" for name in RESULTS_SCHEMA}
        legacy.update({"run_date": "2026-06-02", "question_id": last["question_id"], "question": last["question"],
                       "funnel_stage": last["buyer_journey_stage"], "engine": "Gemini", "brand_cited": "N",
                       "answer_snippet": "Legacy answer."})
        write_results_atomically(self.results_path, [legacy])
        result = self.cycle()
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertEqual(self.mock_answer.call_count, 39)
        self.assertTrue(any("--allow-partial" in r for r in result.reasons))
        self.assertEqual(self.snapshot_ids(), [RUN_1])

    def test_state_f_during_collection_stops_without_snapshot(self) -> None:
        self.baseline()
        real_batch = run_monitoring_cycle.run_structured_batch_audit
        victim = self.ids[30]

        def corrupting(*args, **kwargs):
            result = real_batch(*args, **kwargs)
            evidence_path(self.evidence_dir, victim).write_text("{malformed", encoding="utf-8")
            return result

        with patch("run_monitoring_cycle.run_structured_batch_audit", side_effect=corrupting):
            result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertTrue(any("integrity" in r for r in result.reasons))
        self.assertEqual(self.mock_answer.call_count, 5)
        self.assertEqual(self.snapshot_ids(), [RUN_1])

    def test_classifier_uses_the_released_error_messages(self) -> None:
        import response_analyzer
        from gemini_client import generate_response

        class FakeModels:
            def __init__(self, message):
                self.message = message

            def generate_content(self, **kwargs):
                raise RuntimeError(self.message)

        def failure(message, call):
            client = Mock()
            client.models = FakeModels(message)
            with patch("gemini_client.genai.Client", return_value=client), \
                    patch.dict(os.environ, {"GEMINI_API_KEY": SECRET}):
                try:
                    call()
                except Exception as exc:  # noqa: BLE001 - the recorded failure text is under test
                    return str(exc)
            self.fail("no failure raised")

        answer = lambda: generate_response("question")  # noqa: E731
        with patch("response_analyzer.generate_response", generate_response):
            analysis = lambda: response_analyzer.analyze_response("answer", "Brand", [])  # noqa: E731
            self.assertTrue(is_retryable_failure(failure("429 RESOURCE_EXHAUSTED", analysis)))
            self.assertFalse(is_retryable_failure(failure("401 UNAUTHENTICATED", analysis)))
        self.assertTrue(is_retryable_failure(failure("503 UNAVAILABLE", answer)))
        self.assertFalse(is_retryable_failure(failure("403 PERMISSION_DENIED", answer)))
        self.assertFalse(is_retryable_failure("Gemini analysis returned malformed JSON: error 500\nRaw response: '500'"))
        self.assertFalse(is_retryable_failure("GEMINI_API_KEY is not set."))


class CrashResumeTests(_ExecutorTestCase):
    def test_a_crash_after_new_run_before_collection(self) -> None:
        self.baseline()
        with patch("run_monitoring_cycle.run_structured_batch_audit", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cycle(now=DUE)
        self.assert_lock_free()
        self.assertEqual(self.state(), STATE_FRESH)
        result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OK, result.reasons)
        self.assertNotIn("new-run", " ".join(result.actions_taken))
        self.assertEqual(self.mock_answer.call_count, 40)

    def test_d_crash_after_collection_before_snapshot(self) -> None:
        self.baseline()
        with patch("run_monitoring_cycle.create_snapshot", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cycle(now=DUE)
        self.assertEqual(self.state(), STATE_COMPLETE)
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        result = self.cycle(now=DUE, key=False)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK))
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()

    def test_e_after_a_completed_cycle_nothing_repeats(self) -> None:
        self.baseline()
        self.assertEqual(self.cycle(now=DUE).exit_code, EXIT_OK)
        self.mock_answer.reset_mock()
        before = tree(self.root)
        result = self.cycle(now=DUE + timedelta(minutes=1))
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_NOT_DUE, EXIT_OK))
        self.assertEqual(result.actions_taken, ())
        self.assertEqual(without_lock(tree(self.root)), without_lock(before))
        self.assertEqual(self.snapshot_ids(), [RUN_1, RUN_DUE])
        self.mock_answer.assert_not_called()


class ExecutorLockTests(_ExecutorTestCase):
    def test_second_executor_for_the_same_audit_gets_exit_3(self) -> None:
        self.baseline()
        nested = []
        real_batch = run_monitoring_cycle.run_structured_batch_audit

        def spy(*args, **kwargs):
            if not nested:
                nested.append(self.cycle(now=DUE))
            return real_batch(*args, **kwargs)

        with patch("run_monitoring_cycle.run_structured_batch_audit", side_effect=spy):
            result = self.cycle(now=DUE)
        self.assertEqual((nested[0].outcome, nested[0].exit_code), ("already running", EXIT_ALREADY_RUNNING))
        self.assertEqual(nested[0].actions_taken, ())
        self.assertEqual(result.exit_code, EXIT_OK)
        self.assert_lock_free()

    def test_lock_held_elsewhere_changes_nothing(self) -> None:
        self.baseline()
        with AuditLock(self.lock_file) as other:
            other.acquire(SLUG)
            before = tree(self.root)
            result = self.cycle(now=DUE)
            self.assertEqual(tree(self.root), before)
        self.assertEqual(result.exit_code, EXIT_ALREADY_RUNNING)
        self.mock_answer.assert_not_called()

    def test_lock_released_after_exception(self) -> None:
        self.baseline()
        with patch("run_monitoring_cycle.start_new_run", side_effect=RuntimeError("unexpected")):
            with self.assertRaises(RuntimeError):
                self.cycle(now=DUE)
        self.assert_lock_free()

    def test_different_audits_run_independently(self) -> None:
        other_data = {**CREATION_DATA, "slug": OTHER_SLUG, "brand": "Kettlecraft"}
        other = create_audit.create_audit_workspace(other_data, audits_dir=self.audits,
                                                    reports_dir=self.root / "reports")
        with redirect_stdout(io.StringIO()):
            run_structured_batch_audit(str(other.questions_file), str(other.results_file), 0, None,
                                       sleep_fn=lambda s: None, audit_config=other.config)
        create_snapshot(OTHER_SLUG, audits_dir=self.audits, now=lambda: T1)
        self.baseline()
        inner = []
        real_batch = run_monitoring_cycle.run_structured_batch_audit

        def spy(*args, **kwargs):
            if not inner and SLUG in args[0]:
                inner.append(self.cycle(now=DUE, slug=OTHER_SLUG))  # while this audit's lock is held
            return real_batch(*args, **kwargs)

        with patch("run_monitoring_cycle.run_structured_batch_audit", side_effect=spy):
            result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OK, result.reasons)
        self.assertEqual((inner[0].exit_code, inner[0].new_snapshot), (EXIT_OK, RUN_DUE), inner[0].reasons)


class RunCliTests(_ExecutorTestCase):
    def run_summary(self, out: str) -> dict:
        return json.loads(out.strip().splitlines()[-1])

    def test_cli_not_due(self) -> None:
        self.baseline()
        code, out, _ = self.run_cli(["--audit", SLUG, "--interval-days", "30"], now=T1 + timedelta(days=1))
        summary = self.run_summary(out)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual((summary["mode"], summary["outcome"], summary["exit_code"]), ("run", OUTCOME_NOT_DUE, 0))

    def test_cli_complete_run_is_snapshotted(self) -> None:
        self.baseline()
        self.new_run()
        self.collect()
        code, out, err = self.run_cli(["--audit", SLUG, "--interval-days", "30"], key=SECRET)
        summary = self.run_summary(out)
        self.assertEqual(code, EXIT_OK, err)
        self.assertEqual(summary["outcome"], OUTCOME_COMPLETED)
        self.assertRegex(summary["new_snapshot"], r"^\d{8}T\d{6}Z$")
        self.assertEqual(set(summary), {"audit_slug", "mode", "outcome", "action", "active_state", "final_state",
                                        "latest_snapshot", "new_snapshot", "comparison", "requires_collection",
                                        "exit_code"})
        self.assertTrue(Path(summary["comparison"]).is_file())
        self.assertIn(f"{RUN_1}__{summary['new_snapshot']}", summary["comparison"])
        self.assertNotIn(SECRET, out + err)

    def test_cli_already_running(self) -> None:
        self.baseline()
        with AuditLock(self.lock_file) as other:
            other.acquire(SLUG)
            code, out, _ = self.run_cli(["--audit", SLUG, "--interval-days", "30"], now=DUE, key=SECRET)
        self.assertEqual(code, EXIT_ALREADY_RUNNING)
        self.assertEqual(self.run_summary(out)["exit_code"], 3)
        self.mock_answer.assert_not_called()

    def test_cli_first_run_needs_a_baseline(self) -> None:
        code, out, _ = self.run_cli(["--audit", SLUG, "--interval-days", "30"], key=SECRET)
        self.assertEqual(code, EXIT_OPERATOR_ACTION)
        self.assertIn("snapshot the baseline run manually", out)
        self.mock_answer.assert_not_called()


# ==========================================================================
# Checkpoint C - comparison and the complete recurring lifecycle
# ==========================================================================

DUE_2 = DUE + timedelta(days=INTERVAL)
RUN_DUE_2 = "20260731T090000Z"


class ComparisonLifecycleTests(_ExecutorTestCase):
    def comparison(self, earlier: str, later: str) -> Path:
        return self.root / "reports" / SLUG / "comparisons" / f"{earlier}__{later}" / "GEO_PROGRESS.md"

    def comparison_dirs(self) -> list[str]:
        folder = self.root / "reports" / SLUG / "comparisons"
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def spies(self, names=("start_new_run", "run_structured_batch_audit", "create_snapshot", "compare_snapshots")):
        """Wrap the mutating steps so a test can prove none of them ran."""
        spies = {}
        for name in names:
            patcher = patch(f"run_monitoring_cycle.{name}", wraps=getattr(run_monitoring_cycle, name))
            spies[name] = patcher.start()
            self.addCleanup(patcher.stop)
        return spies

    def assert_nothing_ran(self, spies) -> None:
        for name, spy in spies.items():
            with self.subTest(step=name):
                spy.assert_not_called()

    # -- the full cycle and the duplicate trigger --

    def test_full_cycle_compares_the_baseline_with_the_new_snapshot(self) -> None:
        self.baseline()
        baseline_bytes = tree(self.snapshots_dir / RUN_1)
        real_compare = run_monitoring_cycle.compare_snapshots
        seen = []

        def compare_spy(*args, **kwargs):
            seen.append(args)
            self.assertTrue(probe_lock(self.lock_file), "the lock must be held during the comparison")
            return real_compare(*args, **kwargs)

        with patch("run_monitoring_cycle.compare_snapshots", side_effect=compare_spy):
            result = self.cycle(now=DUE)

        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK), result.reasons)
        self.assertEqual(seen, [(SLUG, RUN_1, RUN_DUE)])  # previous -> new, never reversed
        expected = self.comparison(RUN_1, RUN_DUE)
        self.assertEqual(result.comparison_path, expected)
        self.assertTrue(expected.is_file())
        report = expected.read_text(encoding="utf-8")
        self.assertIn(f"- From run (earlier): {RUN_1}", report)
        self.assertIn(f"- To run (later): {RUN_DUE}", report)
        self.assertEqual(self.comparison_dirs(), [f"{RUN_1}__{RUN_DUE}"])
        self.assertEqual((self.mock_answer.call_count, self.mock_analysis.call_count), (40, 40))
        self.assertEqual(tree(self.snapshots_dir / RUN_1), baseline_bytes)
        self.assertTrue(inspect_snapshot(self.snapshots_dir / RUN_DUE, slug=SLUG).is_valid)
        self.assertEqual(result.actions_taken[-1], f"comparison {RUN_1} -> {RUN_DUE} created")
        self.assertEqual(result.final_state, STATE_SNAPSHOTTED)
        self.assert_lock_free()

    def test_immediate_duplicate_trigger_does_nothing(self) -> None:
        self.baseline()
        self.assertEqual(self.cycle(now=DUE).exit_code, EXIT_OK)
        report_bytes = self.comparison(RUN_1, RUN_DUE).read_bytes()
        before = tree(self.root)
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        spies = self.spies()
        result = self.cycle(now=DUE + timedelta(minutes=1))
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_NOT_DUE, EXIT_OK))
        self.assert_nothing_ran(spies)
        self.key_check.assert_not_called()
        self.mock_answer.assert_not_called()
        self.assertEqual(self.comparison(RUN_1, RUN_DUE).read_bytes(), report_bytes)
        self.assertEqual(without_lock(tree(self.root)), without_lock(before))

    def test_multi_cycle_history(self) -> None:
        self.baseline()
        self.assertEqual(self.cycle(now=DUE).exit_code, EXIT_OK)
        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run three."
        self.mock_answer.reset_mock()
        third = self.cycle(now=DUE_2)
        self.assertEqual((third.exit_code, third.new_snapshot), (EXIT_OK, RUN_DUE_2), third.reasons)
        self.assertEqual(self.mock_answer.call_count, 40)
        self.assertEqual(self.snapshot_ids(), [RUN_1, RUN_DUE, RUN_DUE_2])
        for run_id in self.snapshot_ids():
            self.assertTrue(inspect_snapshot(self.snapshots_dir / run_id, slug=SLUG).is_valid)
        self.assertEqual(self.comparison_dirs(), [f"{RUN_1}__{RUN_DUE}", f"{RUN_DUE}__{RUN_DUE_2}"])  # no 1 -> 3
        for path in (self.snapshots_dir / RUN_DUE_2 / "raw_responses").iterdir():
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["raw_response_text"].endswith("Run three."))
        self.assertEqual(self.cycle(now=DUE_2 + timedelta(minutes=1)).outcome, OUTCOME_NOT_DUE)

    # -- comparison-only recovery --

    def test_comparison_only_recovery_needs_no_key(self) -> None:
        self.two_snapshots()
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        with patch("run_monitoring_cycle.start_new_run") as new_run, \
                patch("run_monitoring_cycle.create_snapshot") as snapshot:
            result = self.cycle(key=False)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK), result.reasons)
        self.assertEqual(result.actions_taken, (f"comparison {RUN_1} -> {RUN_2} created",))
        self.assertIsNone(result.new_snapshot)
        self.assertTrue(self.comparison(RUN_1, RUN_2).is_file())
        new_run.assert_not_called()
        snapshot.assert_not_called()
        self.key_check.assert_not_called()
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()

        report_bytes = self.comparison(RUN_1, RUN_2).read_bytes()
        spies = self.spies()
        again = self.cycle(key=False)
        self.assertEqual((again.outcome, again.exit_code), (OUTCOME_NOT_DUE, EXIT_OK))
        self.assert_nothing_ran(spies)
        self.assertEqual(self.comparison(RUN_1, RUN_2).read_bytes(), report_bytes)

    def test_crash_after_snapshot_before_comparison(self) -> None:
        self.baseline()
        with patch("run_monitoring_cycle.compare_snapshots", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cycle(now=DUE)
        self.assert_lock_free()
        self.assertEqual(self.snapshot_ids(), [RUN_1, RUN_DUE])
        self.assertEqual(self.comparison_dirs(), [])
        self.assertEqual(self.state(), STATE_SNAPSHOTTED)
        self.mock_answer.reset_mock()
        result = self.cycle(now=DUE, key=False)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK), result.reasons)
        self.assertEqual(result.actions_taken, (f"comparison {RUN_1} -> {RUN_DUE} created",))
        self.assertEqual(self.snapshot_ids(), [RUN_1, RUN_DUE])
        self.mock_answer.assert_not_called()

    def test_operator_accepted_partial_snapshot_is_compared(self) -> None:
        self.baseline()
        self.new_run()
        self.collect(limit=30)
        self.snapshot(when=T2, allow_partial=True)  # the operator's decision, not automation's
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        result = self.cycle(key=False)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK), result.reasons)
        report = self.comparison(RUN_1, RUN_2).read_text(encoding="utf-8")
        self.assertIn("- To coverage: 30 / 40 structurally complete Gemini questions (75.0%)", report)
        self.assertIn("- Shared complete questions used: 30", report)
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()

    # -- refusals: evidence is never rolled back, nothing is recollected --

    def test_zero_shared_questions_is_refused_by_the_comparison(self) -> None:
        self.collect(limit=8)  # PA01-PA08 only
        self.snapshot(when=T1, allow_partial=True)
        self.new_run()
        self.failing_analysis.update(self.ids[:8])  # PA answers stored but never analysed
        self.collect(suffix="Run two.")
        self.snapshot(when=T2, allow_partial=True)
        snapshots_before = tree(self.snapshots_dir)
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        for _ in range(2):  # the next trigger stays in the same state; nothing is recollected
            result = self.cycle(key=False)
            self.assertEqual((result.outcome, result.exit_code), (OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION))
            self.assertTrue(any("No question is structurally complete in both runs" in r for r in result.reasons),
                            result.reasons)
        self.assertEqual(tree(self.snapshots_dir), snapshots_before)
        self.assertEqual(self.comparison_dirs(), [])
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()

    def test_comparison_refused_after_a_new_snapshot_keeps_the_snapshot(self) -> None:
        self.baseline()
        refusal = NotComparableError("The two runs do not use the same question library:", ["simulated refusal"])
        with patch("run_monitoring_cycle.compare_snapshots", side_effect=refusal):
            result = self.cycle(now=DUE)
            self.assertEqual((result.outcome, result.exit_code), (OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION))
            self.assertEqual(result.new_snapshot, RUN_DUE)
            self.assertTrue(any("was refused or failed" in r and "simulated refusal" in r for r in result.reasons))
            self.assertTrue(inspect_snapshot(self.snapshots_dir / RUN_DUE, slug=SLUG).is_valid)
            self.mock_answer.reset_mock()
            spies = self.spies(("start_new_run", "run_structured_batch_audit", "create_snapshot"))
            again = self.cycle(now=DUE)
        self.assertEqual(again.exit_code, EXIT_OPERATOR_ACTION)
        self.assert_nothing_ran(spies)  # no new-run, collection or duplicate snapshot
        self.mock_answer.assert_not_called()
        self.assertEqual(self.snapshot_ids(), [RUN_1, RUN_DUE])

    def test_comparison_write_failure_is_retried_as_comparison_only(self) -> None:
        self.baseline()
        with patch("audit_history._write_report_atomically", side_effect=OSError("disk full")):
            result = self.cycle(now=DUE)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_OPERATOR_ACTION, EXIT_OPERATOR_ACTION))
        self.assertTrue(any("disk full" in r for r in result.reasons))
        self.assertEqual(self.snapshot_ids(), [RUN_1, RUN_DUE])
        self.assertFalse(self.comparison(RUN_1, RUN_DUE).exists())
        self.assertEqual(self.state(), STATE_SNAPSHOTTED)
        self.mock_answer.reset_mock()
        retry = self.cycle(now=DUE, key=False)
        self.assertEqual((retry.outcome, retry.exit_code), (OUTCOME_COMPLETED, EXIT_OK), retry.reasons)
        self.assertEqual(retry.actions_taken, (f"comparison {RUN_1} -> {RUN_DUE} created",))
        self.mock_answer.assert_not_called()

    def test_snapshot_tampered_before_its_comparison_is_refused(self) -> None:
        self.baseline()
        real_snapshot = run_monitoring_cycle.create_snapshot

        def snapshot_then_tamper_previous(*args, **kwargs):
            info = real_snapshot(*args, **kwargs)
            (self.snapshots_dir / RUN_1 / "reports" / "audit_report.md").write_text("tampered", encoding="utf-8")
            return info

        with patch("run_monitoring_cycle.create_snapshot", side_effect=snapshot_then_tamper_previous), \
                patch("run_monitoring_cycle.compare_snapshots") as compare:
            result = self.cycle(now=DUE)
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertTrue(any(f"previous snapshot {RUN_1} failed validation" in r for r in result.reasons))
        compare.assert_not_called()  # no derived report from invalid history
        self.assertTrue(inspect_snapshot(self.snapshots_dir / RUN_DUE, slug=SLUG).is_valid)
        self.assertEqual(self.comparison_dirs(), [])

    def test_invalid_previous_snapshot_blocks_without_fallback(self) -> None:
        self.collect()
        self.snapshot(when=T1 - timedelta(days=1))  # an older, valid snapshot
        self.new_run()
        self.two_snapshots_after_first()
        (self.snapshots_dir / RUN_1 / "reports" / "audit_report.md").write_text("tampered", encoding="utf-8")
        self.mock_answer.reset_mock()
        spies = self.spies()
        result = self.cycle(key=False)
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertTrue(any(f"previous snapshot {RUN_1} failed validation" in r for r in result.reasons))
        self.assert_nothing_ran(spies)
        self.assertEqual(self.comparison_dirs(), [])
        self.mock_answer.assert_not_called()

    def two_snapshots_after_first(self) -> None:
        self.collect(suffix="Run one.")
        self.snapshot(when=T1)
        self.new_run()
        self.collect(suffix="Run two.")
        self.snapshot(when=T2)

    def test_invalid_latest_snapshot_blocks(self) -> None:
        self.two_snapshots()
        with (self.snapshots_dir / RUN_2 / "audit_results.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        self.mock_answer.reset_mock()
        spies = self.spies()
        result = self.cycle(now=T2 + timedelta(days=INTERVAL))
        self.assertEqual(result.exit_code, EXIT_OPERATOR_ACTION)
        self.assertTrue(any(f"latest snapshot {RUN_2} failed validation" in r for r in result.reasons))
        self.assert_nothing_ran(spies)
        self.assertEqual(self.comparison_dirs(), [])
        self.mock_answer.assert_not_called()

    # -- re-baseline --

    def test_rebaseline_history_never_compares_across_the_break(self) -> None:
        self.collect()
        self.snapshot(when=T1)  # A: methodology 1
        self.new_run()
        self.edit_config(brand="Lumiere Tea")
        self.collect(suffix="Rebaselined.")
        self.snapshot(when=T2)  # B: methodology 2, a manual re-baseline
        self.mock_answer.reset_mock()
        spies = self.spies()
        not_due = self.cycle(now=T2 + timedelta(days=1))
        self.assertEqual((not_due.outcome, not_due.exit_code), (OUTCOME_NOT_DUE, EXIT_OK))
        self.assert_nothing_ran(spies)
        self.mock_answer.side_effect = lambda prompt: fake_answer(prompt) + "Run three."
        later = T2 + timedelta(days=INTERVAL)
        result = self.cycle(now=later)
        self.assertEqual((result.outcome, result.exit_code), (OUTCOME_COMPLETED, EXIT_OK), result.reasons)
        c_run = run_id_for(later)
        self.assertEqual(self.comparison_dirs(), [f"{RUN_2}__{c_run}"])  # B -> C only: never A -> B or A -> C
        self.assertEqual([c.args for c in spies["compare_snapshots"].call_args_list], [(SLUG, RUN_2, c_run)])


class RunCliComparisonTests(_ExecutorTestCase):
    def test_cli_comparison_only_recovery(self) -> None:
        self.two_snapshots()
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        code, out, err = self.run_cli(["--audit", SLUG, "--interval-days", "30"])
        summary = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, EXIT_OK, err)
        expected = self.root / "reports" / SLUG / "comparisons" / f"{RUN_1}__{RUN_2}" / "GEO_PROGRESS.md"
        self.assertEqual((summary["outcome"], summary["comparison"]), (OUTCOME_COMPLETED, str(expected)))
        self.assertIsNone(summary["new_snapshot"])
        self.assertIn(f"Comparison: {expected}", out)
        self.assertTrue(expected.is_file())
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()


if __name__ == "__main__":
    unittest.main()
