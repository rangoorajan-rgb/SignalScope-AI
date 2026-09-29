"""Tests for src/readonly_api.py - v2.6 Checkpoint D2: the transport-
independent read-only resource layer.

Fictional audits are created with create_audit_workspace in temporary
directories and collected with the real structured batch, with both Gemini
paths faked and the SDK blocked. Every resource call runs with the Gemini
entry points, the .env loader, the key check and every mutating engine
function patched to fail, and the whole temporary tree is compared (path,
size and SHA-256) before and after the call. The real audits/, reports/ and
master template are verified unchanged after every test.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import create_audit  # noqa: E402
import readonly_api  # noqa: E402
from audit_history import compute_snapshot_comparison, create_snapshot, list_snapshots, start_new_run  # noqa: E402
from geo_findings_analyzer import compute_findings  # noqa: E402
from readonly_api import (  # noqa: E402
    READONLY_API_CONTRACT_VERSION,
    ReadonlyApiError,
    get_audit,
    get_audits,
    get_comparison,
    get_current_run,
    get_health,
    get_monitoring_plan,
    get_snapshot,
    get_snapshots,
)
from report_generator import compute_brand_visibility, compute_sentiment_summary  # noqa: E402
from run_monitoring_cycle import AuditLock  # noqa: E402
from run_structured_batch_audit import (  # noqa: E402
    STATE_LABELS,
    STATE_NOT_STARTED,
    classify_question,
    evidence_path,
    run_structured_batch_audit,
)
from version import SIGNALSCOPE_VERSION  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, load_existing_results, write_results_atomically  # noqa: E402

SLUG = "lumiere-veloria-tea"
BOOTS_SLUG = "boots-uk-health-beauty"
T1 = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(hours=1)
RUN_1 = "20260601T090000Z"
RUN_2 = "20260601T100000Z"
GEN_DATE = date(2026, 11, 2)

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
CITED_JSON = json.dumps({
    "brand_cited": "Y", "brand_position": 1, "competitors_cited": ["Brewvale", "Steepwisé"],
    "sources_cited": ["Leaf Journal"], "sentiment": "Positive",
})
NOT_CITED_JSON = json.dumps({
    "brand_cited": "N", "brand_position": None, "competitors_cited": ["Brewvale"],
    "sources_cited": [], "sentiment": "Neutral",
})

# -- the frozen contract: exact key sets --
HEALTH_KEYS = {"status", "signalscope_version", "contract_version", "read_only"}
CURRENT_RUN_KEYS = {"readable", "error", "state", "detail", "question_count", "structurally_complete_count",
                    "coverage_percent", "result_row_count", "evidence_problem_count", "requested_models"}
SNAPSHOT_KEYS = {"run_id", "valid", "problems", "created_at", "status", "signalscope_version", "question_count",
                 "structurally_complete_count", "requested_models"}
ROW_BASIS_KEYS = {"total_rows", "rows_by_engine", "unique_questions"}
METRICS_KEYS = {"brand_visibility", "brand_mention_frequency", "positive_sentiment", "authority_sources",
                "funnel_stage_coverage", "geo_maturity"}
METRIC_BLOCK_KEYS = {
    "brand_visibility": {"rate_percent", "cited", "not_cited", "considered", "excluded"},
    "positive_sentiment": {"rate_percent", "positive", "neutral", "negative", "excluded"},
    "authority_sources": {"distinct_count", "rows_with_sources_percent"},
    "funnel_stage_coverage": {"stages_covered", "stages_total", "rows_per_stage"},
    "geo_maturity": {"tier"},
}
FINDING_KEYS = {"title", "value", "evidence", "confidence"}
QUESTION_KEYS = {"question_id", "buyer_journey_stage", "question", "state_code", "state_label", "detail",
                 "gemini_result"}
GEMINI_RESULT_KEYS = {"run_date", "brand_cited", "brand_position", "competitors_cited", "sources_cited",
                      "sentiment", "answer_snippet"}
AUDIT_LIST_KEYS = {"slug", "brand", "company_name", "market", "category", "competitors", "current_run",
                   "latest_snapshot", "snapshot_count"}
AUDIT_DETAIL_KEYS = {"slug", "brand", "company_name", "report_subject", "market", "category", "competitors",
                     "question_library", "current_run", "latest_snapshot"}
CURRENT_KEYS = {"slug", "current_run", "row_basis", "metrics", "findings", "questions"}
SNAPSHOT_DETAIL_KEYS = {"slug", "snapshot", "is_latest", "row_basis", "metrics", "findings"}
COMPARISON_KEYS = {"slug", "from_run", "to_run", "comparable", "from", "to", "unequal_coverage",
                   "shared_question_count", "shared_question_ids", "warnings", "metrics", "overall_assessment",
                   "generated_at"}
NOT_COMPARABLE_KEYS = {"slug", "from_run", "to_run", "comparable", "problems"}
COMPARISON_METRIC_KEYS = {"metric_name", "before", "after", "difference", "direction"}
PLAN_KEYS = {"slug", "interval_days", "plan_outcome", "outcome", "planned_steps", "active_state", "latest_snapshot",
             "previous_snapshot", "due", "requires_collection", "integrity_problems", "methodology_differences",
             "reasons", "api_key_check", "lock_held"}

BAD_SLUGS = ["..", "%2e%2e", "..%2f", "a/b", "a\\b", "../boots-uk-health-beauty", "Lumiere", "a--b", "-a", "a-",
             "", " ", None, 5]
# Otherwise valid under the released slug grammar, just long (no length rule exists).
LONG_SLUG = "long-" + "a" * 50 + "-" + "b" * 50  # 106 characters
BAD_RUN_IDS = ["2026-06-01", "20261301T090000Z", "20260230T090000Z", "20260601T250000Z", "latest",
               "../20260601T090000Z", "20260601T090000Z/..", "20260601T090000z", "", None, 20260601]
BAD_INTERVALS = [0, -1, 1.5, True, False, "30", None]

# Everything a read-only resource must never touch.
FORBIDDEN = (
    "gemini_client.generate_response",
    "gemini_client._load_dotenv",
    "response_analyzer.analyze_response",
    "run_structured_batch_audit.run_structured_batch_audit",
    "run_monitoring_cycle.gemini_api_key_present",
    "run_monitoring_cycle.run_monitoring_cycle",
    "audit_history.compare_snapshots",
    "audit_history.create_snapshot",
    "audit_history.start_new_run",
    "audit_history._write_report_atomically",
)


def tree_state(root: Path) -> dict[str, tuple]:
    """Every path under root with its size and SHA-256 (directories: None)."""
    if not root.exists():
        return {}
    state = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            data = p.read_bytes()
            state[p.relative_to(root).as_posix()] = (len(data), hashlib.sha256(data).hexdigest())
        else:
            state[p.relative_to(root).as_posix()] = None
    return state


def production_state() -> dict:
    paths = [REPO_ROOT / "questions" / "buyer_questions_master.csv",
             *(REPO_ROOT / "audits").rglob("*"), *(REPO_ROOT / "reports").rglob("*")]
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in sorted(paths)}


def assert_json_safe(test: unittest.TestCase, value) -> None:
    """Only dict/list/str/int/float/bool/None, and json.dumps with no custom encoder."""
    def walk(v):
        if isinstance(v, dict):
            for k, item in v.items():
                test.assertIsInstance(k, str)
                walk(item)
        elif isinstance(v, list):
            for item in v:
                walk(item)
        else:
            test.assertTrue(v is None or isinstance(v, (str, int, float, bool)), f"not JSON-safe: {v!r}")
    walk(value)
    json.dumps(value)


class _GuardedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini client"))
        guard.start()
        self.addCleanup(guard.stop)
        before = production_state()

        def check() -> None:
            self.assertEqual(production_state(), before, "production audits/reports/template changed")
            self.assertEqual(list((REPO_ROOT / "audits").glob("*/.monitoring.lock")), [])

        self.addCleanup(check)

    def forbid(self) -> ExitStack:
        stack = ExitStack()
        for target in FORBIDDEN:
            stack.enter_context(patch(target, side_effect=AssertionError(f"{target} must not be called")))
        return stack

    def assert_api_error(self, status: int, code: str, call, *args, **kwargs) -> ReadonlyApiError:
        with self.forbid():
            with self.assertRaises(ReadonlyApiError) as ctx:
                call(*args, **kwargs)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (status, code), ctx.exception)
        self.assertIsInstance(ctx.exception.message, str)
        self.assertNotIn("Traceback", ctx.exception.message)
        return ctx.exception


class _ReadonlyTestCase(_GuardedTestCase):
    """A fictional audit in a temporary project root, Gemini fully faked."""

    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.audits = self.root / "audits"
        self.audits.mkdir()
        created = create_audit.create_audit_workspace(CREATION_DATA, audits_dir=self.audits,
                                                      reports_dir=self.root / "reports")
        self.audit_dir = created.audit_dir
        self.config = created.config
        self.questions_path = str(created.questions_file)
        self.results_path = str(created.results_file)
        self.evidence_dir = self.audit_dir / "raw_responses"
        self.snapshots_dir = self.audit_dir / "snapshots"
        from audit_runner import load_questions
        self.questions = load_questions(self.questions_path)
        self.ids = [q["question_id"] for q in self.questions]
        self.by_text = {q["question"]: q["question_id"] for q in self.questions}
        self.not_cited: set[str] = set()
        self.failing: set[str] = set()
        self.suffix = ""
        answer = patch("run_batch_audit.generate_response", side_effect=self._answer)
        analysis = patch("response_analyzer.generate_response", side_effect=self._analysis)
        self.mock_answer, self.mock_analysis = answer.start(), analysis.start()
        self.addCleanup(answer.stop)
        self.addCleanup(analysis.stop)

    def _answer(self, prompt: str) -> str:
        return f"For the question {prompt!r}: Lumière leads, ahead of Brewvale.\n" + "Supporting detail; " * 40 \
            + self.suffix

    def _analysis(self, prompt: str) -> str:
        question_id = next((qid for text, qid in self.by_text.items() if repr(text) in prompt), None)
        if question_id in self.failing:
            return '{"malformed": true'
        return NOT_CITED_JSON if question_id in self.not_cited else CITED_JSON

    def collect(self, limit=None, suffix="") -> None:
        self.suffix = suffix
        with redirect_stdout(io.StringIO()):
            run_structured_batch_audit(self.questions_path, self.results_path, 0, limit,
                                       sleep_fn=lambda s: None, audit_config=self.config)

    def snapshot(self, when=T1, allow_partial=False):
        return create_snapshot(SLUG, audits_dir=self.audits, allow_partial=allow_partial, now=lambda: when)

    def two_snapshots(self, second_limit=None) -> None:
        self.collect()
        self.snapshot(when=T1)
        start_new_run(SLUG, audits_dir=self.audits)
        self.not_cited = {q for q in self.ids if q.startswith("PA")}
        self.collect(limit=second_limit, suffix="Run two.")
        self.snapshot(when=T2, allow_partial=second_limit is not None)
        self.not_cited = set()

    def edit_config(self, **changes) -> None:
        path = self.audit_dir / "audit_config.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(changes)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def call(self, fn, *args, **kwargs):
        """Call a resource with every forbidden path patched and prove the
        whole temporary tree is unchanged and the result JSON-safe."""
        before = tree_state(self.root)
        self.mock_answer.reset_mock()
        self.mock_analysis.reset_mock()
        with self.forbid():
            result = fn(*args, **kwargs)
        self.assertEqual(tree_state(self.root), before, f"{fn.__name__} changed the filesystem")
        self.mock_answer.assert_not_called()
        self.mock_analysis.assert_not_called()
        assert_json_safe(self, result)
        return result

    def assert_metrics_shape(self, metrics: dict) -> None:
        self.assertEqual(set(metrics), METRICS_KEYS)
        for block, keys in METRIC_BLOCK_KEYS.items():
            self.assertEqual(set(metrics[block]), keys, block)
        self.assertIsInstance(metrics["brand_mention_frequency"], int)


# --------------------------------------------------------------------------
# Health and the error model
# --------------------------------------------------------------------------


class HealthAndErrorTests(_GuardedTestCase):
    def test_health(self) -> None:
        with self.forbid():
            health = get_health()
        self.assertEqual(health, {"status": "ok", "signalscope_version": SIGNALSCOPE_VERSION,
                                  "contract_version": READONLY_API_CONTRACT_VERSION, "read_only": True})
        self.assertEqual(set(health), HEALTH_KEYS)
        self.assertEqual(READONLY_API_CONTRACT_VERSION, 1)
        assert_json_safe(self, health)

    def test_error_carries_only_status_code_and_message(self) -> None:
        error = ReadonlyApiError(404, "unknown_audit", "Unknown audit 'x'.")
        self.assertIsInstance(error, Exception)
        self.assertEqual((error.status, error.code, error.message), (404, "unknown_audit", "Unknown audit 'x'."))
        self.assertEqual(str(error), "404 unknown_audit: Unknown audit 'x'.")
        with self.assertRaises(Exception):
            error.status = 500  # frozen

    def test_no_trend_or_bare_findings_resource_and_no_writers(self) -> None:
        self.assertFalse(hasattr(readonly_api, "get_trend"))
        self.assertFalse(hasattr(readonly_api, "get_findings"))
        # Code identifiers only (imports, names, attributes), not documentation.
        tree = ast.parse(Path(readonly_api.__file__).read_text(encoding="utf-8"))
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.alias):
                used.add(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == "GEMINI_API_KEY":
                used.add(node.value)
        for forbidden in ("compare_snapshots", "create_snapshot", "start_new_run", "run_structured_batch_audit",
                          "run_monitoring_cycle", "gemini_api_key_present", "_load_dotenv", "generate_response",
                          "environ", "getenv", "GEMINI_API_KEY", "asdict", "write_text", "write_bytes", "open",
                          "mkdir", "unlink", "rmtree"):
            with self.subTest(identifier=forbidden):
                self.assertNotIn(forbidden, used)


# --------------------------------------------------------------------------
# Audits
# --------------------------------------------------------------------------


class AuditResourceTests(_ReadonlyTestCase):
    def test_audit_list_reports_invalid_folders_and_latest_without_fallback(self) -> None:
        (self.audits / "broken-audit").mkdir()
        (self.audits / "broken-audit" / "audit_config.json").write_text("{broken", encoding="utf-8")
        (self.audits / "Bad_Folder").mkdir()
        (self.audits / ".hidden").mkdir()
        listing = self.call(get_audits, audits_dir=self.audits)
        self.assertEqual(set(listing), {"audits", "invalid_audits"})
        self.assertEqual([a["slug"] for a in listing["audits"]], [SLUG])
        self.assertEqual([i["folder"] for i in listing["invalid_audits"]], ["Bad_Folder", "broken-audit"])
        for invalid in listing["invalid_audits"]:
            self.assertEqual(set(invalid), {"folder", "error"})
            self.assertTrue(invalid["error"])
        entry = listing["audits"][0]
        self.assertEqual(set(entry), AUDIT_LIST_KEYS)
        self.assertEqual(set(entry["current_run"]), CURRENT_RUN_KEYS)
        self.assertEqual((entry["latest_snapshot"], entry["snapshot_count"]), (None, 0))
        self.assertEqual(entry["competitors"], CREATION_DATA["competitors"])

        self.two_snapshots(second_limit=5)
        with (self.snapshots_dir / RUN_2 / "audit_results.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        entry = self.call(get_audits, audits_dir=self.audits)["audits"][0]
        self.assertEqual(entry["snapshot_count"], 2)
        self.assertEqual(set(entry["latest_snapshot"]), SNAPSHOT_KEYS)
        self.assertEqual((entry["latest_snapshot"]["run_id"], entry["latest_snapshot"]["valid"]), (RUN_2, False))

    def test_missing_audits_root_is_empty(self) -> None:
        listing = self.call(get_audits, audits_dir=self.root / "no-audits-here")
        self.assertEqual(listing, {"audits": [], "invalid_audits": []})

    def test_audit_detail(self) -> None:
        detail = self.call(get_audit, SLUG, audits_dir=self.audits)
        self.assertEqual(set(detail), AUDIT_DETAIL_KEYS)
        self.assertEqual(
            {k: detail[k] for k in ("slug", "brand", "company_name", "report_subject", "market", "category",
                                    "question_library")},
            {k: CREATION_DATA[k] for k in ("slug", "brand", "company_name", "report_subject", "market", "category",
                                           "question_library")})
        self.assertEqual(detail["competitors"], CREATION_DATA["competitors"])
        self.assertEqual((detail["current_run"]["state"], detail["current_run"]["readable"]), ("fresh", True))
        self.assertIsNone(detail["latest_snapshot"])

    def test_audit_detail_errors(self) -> None:
        self.assert_api_error(404, "unknown_audit", get_audit, "no-such-audit", audits_dir=self.audits)
        (self.audits / "broken-audit").mkdir()
        (self.audits / "broken-audit" / "audit_config.json").write_text("{broken", encoding="utf-8")
        self.assert_api_error(404, "not_found", get_audit, "broken-audit", audits_dir=self.audits)


# --------------------------------------------------------------------------
# Current run
# --------------------------------------------------------------------------


class CurrentRunResourceTests(_ReadonlyTestCase):
    def test_fresh_run_has_no_metrics(self) -> None:
        result = self.call(get_current_run, SLUG, audits_dir=self.audits)
        self.assertEqual(set(result), CURRENT_KEYS)
        self.assertEqual(set(result["current_run"]), CURRENT_RUN_KEYS)
        self.assertEqual(result["current_run"]["state"], "fresh")
        self.assertEqual(result["current_run"]["coverage_percent"], 0.0)
        self.assertEqual(result["row_basis"], {"total_rows": 0, "rows_by_engine": {}, "unique_questions": 0})
        self.assertIsNone(result["metrics"])
        self.assertEqual(result["findings"], [])
        self.assertEqual([q["question_id"] for q in result["questions"]], self.ids)
        self.assertTrue(all(q["state_code"] == STATE_NOT_STARTED and q["gemini_result"] is None
                            for q in result["questions"]))

    def test_collected_run_uses_all_rows_and_backend_states(self) -> None:
        self.not_cited = {"PA02", "PA03"}
        self.collect(limit=6)  # PA01-PA06 complete with evidence
        self.failing = {"PA07"}
        self.collect(limit=1)  # PA07: answer stored, analysis failed (state B)
        rows = load_existing_results(self.results_path)
        manual = {name: "" for name in RESULTS_SCHEMA}
        manual.update({"run_date": "2026-06-02", "question_id": "PA01", "question": self.questions[0]["question"],
                       "funnel_stage": "Problem Awareness", "engine": "Perplexity", "brand_cited": "Y",
                       "sentiment": "Negative", "sources_cited": "Tea Weekly; Leaf Journal",
                       "answer_snippet": "Manual answer."})
        write_results_atomically(self.results_path, rows + [manual])
        rows = load_existing_results(self.results_path)

        result = self.call(get_current_run, SLUG, audits_dir=self.audits)
        current = result["current_run"]
        self.assertEqual((current["state"], current["structurally_complete_count"], current["question_count"]),
                         ("in progress / partial", 6, 40))
        self.assertEqual(current["coverage_percent"], 15.0)
        self.assertEqual((current["result_row_count"], current["evidence_problem_count"]), (7, 0))
        self.assertEqual(current["requested_models"], ["gemini-2.5-flash"])
        self.assertEqual(result["row_basis"], {"total_rows": 7, "rows_by_engine": {"Gemini": 6, "Perplexity": 1},
                                               "unique_questions": 6})

        metrics = result["metrics"]
        self.assert_metrics_shape(metrics)
        visibility = compute_brand_visibility(rows)  # all rows, including the Perplexity row
        self.assertEqual(metrics["brand_visibility"], {"rate_percent": visibility["rate"], "cited": 5,
                                                       "not_cited": 2, "considered": 7, "excluded": 0})
        self.assertEqual(metrics["brand_mention_frequency"], 5)
        sentiment = compute_sentiment_summary(rows)
        self.assertEqual({k: metrics["positive_sentiment"][k] for k in ("positive", "neutral", "negative")},
                         {k: sentiment[k] for k in ("positive", "neutral", "negative")})
        self.assertEqual(metrics["authority_sources"]["distinct_count"], 2)
        self.assertEqual(metrics["funnel_stage_coverage"]["stages_covered"], 1)
        self.assertEqual(metrics["funnel_stage_coverage"]["rows_per_stage"]["Problem Awareness"], 7)
        self.assertEqual(metrics["funnel_stage_coverage"]["stages_total"], 5)
        self.assertEqual(metrics["geo_maturity"], {"tier": "Early"})
        expected_findings = compute_findings(rows, 40, audit_config=self.config)
        self.assertEqual([(f["title"], f["value"], f["evidence"], f["confidence"]) for f in result["findings"]],
                         [(f.title, f.value, f.evidence, f.confidence) for f in expected_findings])
        self.assertTrue(all(set(f) == FINDING_KEYS for f in result["findings"]))

        questions = result["questions"]
        self.assertEqual([q["question_id"] for q in questions], self.ids)
        for q, question_row in zip(questions, self.questions):
            self.assertEqual(set(q), QUESTION_KEYS)
            state = classify_question(question_row, rows, evidence_dir=self.evidence_dir, audit_slug=SLUG)
            self.assertEqual((q["state_code"], q["state_label"], q["detail"]),
                             (state.state, STATE_LABELS[state.state], state.detail))
        first = questions[0]["gemini_result"]
        self.assertEqual(set(first), GEMINI_RESULT_KEYS)
        self.assertEqual((first["brand_cited"], first["brand_position"], first["sentiment"]), ("Y", 1, "Positive"))
        self.assertEqual(first["competitors_cited"], ["Brewvale", "Steepwisé"])
        self.assertEqual(first["sources_cited"], ["Leaf Journal"])
        self.assertIsNone(questions[1]["gemini_result"]["brand_position"])
        self.assertIsNone(questions[6]["gemini_result"])  # state B: answer stored, no row
        dumped = json.dumps(result)
        stored = json.loads(evidence_path(self.evidence_dir, "PA01").read_text(encoding="utf-8"))
        self.assertNotIn(stored["raw_response_text"], dumped)  # never the full raw answer
        self.assertNotIn("raw_responses", dumped)
        self.assertNotIn("raw_response_text", dumped)

    def test_reset_interrupted_has_no_metrics(self) -> None:
        self.collect()
        self.snapshot()
        with patch("audit_history._write_fresh_results", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                start_new_run(SLUG, audits_dir=self.audits)
        result = self.call(get_current_run, SLUG, audits_dir=self.audits)
        self.assertEqual(result["current_run"]["state"], "reset interrupted")
        self.assertIsNone(result["metrics"])
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["row_basis"]["total_rows"], 40)

    def test_unreadable_current_run(self) -> None:
        Path(self.results_path).write_text("not,the,schema\n", encoding="utf-8")
        result = self.call(get_current_run, SLUG, audits_dir=self.audits)
        self.assertIs(result["current_run"]["readable"], False)
        self.assertTrue(result["current_run"]["error"])
        self.assertEqual({k: result[k] for k in ("row_basis", "metrics", "findings", "questions")},
                         {"row_basis": None, "metrics": None, "findings": [], "questions": []})

    def test_unknown_audit(self) -> None:
        self.assert_api_error(404, "unknown_audit", get_current_run, "no-such-audit", audits_dir=self.audits)


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------


class SnapshotResourceTests(_ReadonlyTestCase):
    def test_no_snapshots(self) -> None:
        self.assertEqual(self.call(get_snapshots, SLUG, audits_dir=self.audits), {"slug": SLUG, "snapshots": []})

    def test_snapshot_list_uses_each_snapshots_own_rows(self) -> None:
        self.two_snapshots(second_limit=5)
        result = self.call(get_snapshots, SLUG, audits_dir=self.audits)
        self.assertEqual(set(result), {"slug", "snapshots"})
        entries = result["snapshots"]
        self.assertEqual([e["run_id"] for e in entries], [RUN_1, RUN_2])
        for entry, info in zip(entries, list_snapshots(SLUG, audits_dir=self.audits)):
            self.assertEqual(set(entry), SNAPSHOT_KEYS | {"metrics"})
            self.assert_metrics_shape(entry["metrics"])
            rows = load_existing_results(str(info.path / "audit_results.csv"))
            self.assertEqual(entry["metrics"]["brand_visibility"]["rate_percent"],
                             compute_brand_visibility(rows)["rate"])
        self.assertEqual((entries[0]["status"], entries[0]["structurally_complete_count"]), ("complete", 40))
        self.assertEqual((entries[1]["status"], entries[1]["structurally_complete_count"]), ("partial", 5))
        self.assertEqual(entries[0]["metrics"]["brand_visibility"]["cited"], 40)
        self.assertEqual(entries[1]["metrics"]["brand_visibility"]["not_cited"], 5)  # PA not cited in run 2
        self.assertEqual(entries[0]["signalscope_version"], SIGNALSCOPE_VERSION)
        self.assertEqual(entries[0]["requested_models"], ["gemini-2.5-flash"])
        self.assertEqual(entries[0]["created_at"], "2026-06-01T09:00:00Z")

    def test_invalid_snapshot_in_list_has_no_metrics(self) -> None:
        self.two_snapshots(second_limit=5)
        with (self.snapshots_dir / RUN_1 / "audit_results.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        entries = self.call(get_snapshots, SLUG, audits_dir=self.audits)["snapshots"]
        self.assertEqual((entries[0]["valid"], entries[0]["metrics"]), (False, None))
        self.assertTrue(any("modified file audit_results.csv" in p for p in entries[0]["problems"]))
        self.assertIsNotNone(entries[1]["metrics"])

    def test_snapshot_detail_uses_its_own_files(self) -> None:
        self.two_snapshots(second_limit=5)
        self.edit_config(brand="Changed Brand")  # the current config must not leak into history
        detail = self.call(get_snapshot, SLUG, RUN_1, audits_dir=self.audits)
        self.assertEqual(set(detail), SNAPSHOT_DETAIL_KEYS)
        self.assertEqual(set(detail["snapshot"]), SNAPSHOT_KEYS)
        self.assertEqual((detail["snapshot"]["run_id"], detail["snapshot"]["valid"], detail["is_latest"]),
                         (RUN_1, True, False))
        self.assertEqual(detail["row_basis"], {"total_rows": 40, "rows_by_engine": {"Gemini": 40},
                                               "unique_questions": 40})
        self.assert_metrics_shape(detail["metrics"])
        self.assertEqual(len(detail["findings"]), 7)
        self.assertTrue(any("Lumière" in f["value"] for f in detail["findings"]))
        self.assertFalse(any("Changed Brand" in json.dumps(f) for f in detail["findings"]))
        latest = self.call(get_snapshot, SLUG, RUN_2, audits_dir=self.audits)
        self.assertIs(latest["is_latest"], True)
        self.assertEqual(latest["row_basis"]["total_rows"], 5)

    def test_invalid_snapshot_detail_returns_problems_without_data(self) -> None:
        def modified(path):
            with (path / "audit_results.csv").open("a", encoding="utf-8") as handle:
                handle.write("\n")

        def missing_manifest(path):
            (path / "snapshot_manifest.json").unlink()

        def undeclared(path):
            (path / "extra.txt").write_text("extra", encoding="utf-8")

        def count_mismatch(path):
            manifest = json.loads((path / "snapshot_manifest.json").read_text(encoding="utf-8"))
            manifest["structurally_complete_count"] = 4
            (path / "snapshot_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        self.collect(limit=5)
        self.snapshot(when=T1, allow_partial=True)
        folder = self.snapshots_dir / RUN_1
        pristine = tree_state(folder)
        backup = self.root / "backup"
        shutil.copytree(folder, backup)
        for name, tamper, fragment in (("modified", modified, "modified file audit_results.csv"),
                                       ("missing manifest", missing_manifest, "manifest is missing"),
                                       ("undeclared file", undeclared, "undeclared file extra.txt"),
                                       ("count mismatch", count_mismatch, "structurally_complete_count does not match")):
            with self.subTest(tamper=name):
                shutil.rmtree(folder)
                shutil.copytree(backup, folder)
                self.assertEqual(tree_state(folder), pristine)
                tamper(folder)
                detail = self.call(get_snapshot, SLUG, RUN_1, audits_dir=self.audits)
                self.assertIs(detail["snapshot"]["valid"], False)
                self.assertTrue(any(fragment in p for p in detail["snapshot"]["problems"]), detail["snapshot"])
                self.assertEqual((detail["row_basis"], detail["metrics"], detail["findings"]), (None, None, []))
                self.assertEqual(set(detail["snapshot"]), SNAPSHOT_KEYS)
        shutil.rmtree(backup)

    def test_snapshot_detail_errors(self) -> None:
        self.assert_api_error(404, "unknown_snapshot", get_snapshot, SLUG, RUN_1, audits_dir=self.audits)
        self.assert_api_error(404, "unknown_audit", get_snapshot, "no-such-audit", RUN_1, audits_dir=self.audits)
        self.assert_api_error(404, "unknown_audit", get_snapshots, "no-such-audit", audits_dir=self.audits)


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


class ComparisonResourceTests(_ReadonlyTestCase):
    def test_comparable_pair_is_computed_without_writing(self) -> None:
        self.two_snapshots(second_limit=30)
        comparisons = self.root / "reports" / SLUG / "comparisons"
        result = self.call(get_comparison, SLUG, RUN_1, RUN_2, audits_dir=self.audits, generated_at=GEN_DATE)
        self.assertFalse(comparisons.exists())
        self.assertEqual(set(result), COMPARISON_KEYS)
        self.assertEqual((result["comparable"], result["from_run"], result["to_run"]), (True, RUN_1, RUN_2))
        self.assertEqual(result["from"], {"structurally_complete_count": 40, "question_count": 40})
        self.assertEqual(result["to"], {"structurally_complete_count": 30, "question_count": 40})
        self.assertIs(result["unequal_coverage"], True)
        self.assertEqual((result["shared_question_count"], result["shared_question_ids"]), (30, self.ids[:30]))
        self.assertEqual(result["warnings"], {"requested_models": None, "signalscope_version": None})
        self.assertEqual(result["generated_at"], "2026-11-02")
        expected = compute_snapshot_comparison(SLUG, RUN_1, RUN_2, audits_dir=self.audits, generated_at=GEN_DATE)
        self.assertEqual(
            [tuple(m[k] for k in ("metric_name", "before", "after", "difference", "direction"))
             for m in result["metrics"]],
            [(m.metric_name, m.before, m.after, m.difference, m.direction) for m in expected.progress.metrics])
        self.assertEqual(len(result["metrics"]), 7)
        self.assertTrue(all(set(m) == COMPARISON_METRIC_KEYS for m in result["metrics"]))
        self.assertEqual(result["overall_assessment"], expected.progress.overall_assessment)

    def test_methodology_mismatch_is_a_normal_result(self) -> None:
        self.collect(limit=5)
        self.snapshot(when=T1, allow_partial=True)
        start_new_run(SLUG, audits_dir=self.audits)
        self.edit_config(brand="Lumiere Tea")
        self.collect(limit=5, suffix="Run two.")
        self.snapshot(when=T2, allow_partial=True)
        result = self.call(get_comparison, SLUG, RUN_1, RUN_2, audits_dir=self.audits)
        self.assertEqual(set(result), NOT_COMPARABLE_KEYS)
        self.assertIs(result["comparable"], False)
        self.assertTrue(any("brand differs" in p for p in result["problems"]))

    def test_refusals(self) -> None:
        self.two_snapshots(second_limit=5)
        self.assert_api_error(400, "comparison_refused", get_comparison, SLUG, RUN_2, RUN_1, audits_dir=self.audits)
        self.assert_api_error(400, "comparison_refused", get_comparison, SLUG, RUN_1, RUN_1, audits_dir=self.audits)
        self.assert_api_error(404, "unknown_snapshot", get_comparison, SLUG, RUN_1, "20260601T110000Z",
                              audits_dir=self.audits)
        self.assert_api_error(404, "unknown_audit", get_comparison, "no-such-audit", RUN_1, RUN_2,
                              audits_dir=self.audits)
        with (self.snapshots_dir / RUN_2 / "audit_results.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        error = self.assert_api_error(409, "snapshot_invalid", get_comparison, SLUG, RUN_1, RUN_2,
                                      audits_dir=self.audits)
        self.assertIn(f"Snapshot {RUN_2} (to run) failed validation", error.message)
        self.assertFalse((self.root / "reports" / SLUG / "comparisons").exists())

    def test_zero_shared_questions_is_refused(self) -> None:
        self.collect(limit=8)
        self.snapshot(when=T1, allow_partial=True)
        start_new_run(SLUG, audits_dir=self.audits)
        self.failing = set(self.ids[:8])
        self.collect(suffix="Run two.")
        self.snapshot(when=T2, allow_partial=True)
        error = self.assert_api_error(400, "comparison_refused", get_comparison, SLUG, RUN_1, RUN_2,
                                      audits_dir=self.audits)
        self.assertIn("No question is structurally complete in both runs", error.message)


# --------------------------------------------------------------------------
# Monitoring plan
# --------------------------------------------------------------------------


class MonitoringPlanResourceTests(_ReadonlyTestCase):
    def plan(self, **kwargs):
        return self.call(get_monitoring_plan, SLUG, 30, audits_dir=self.audits, **kwargs)

    def test_no_baseline(self) -> None:
        result = self.plan()
        self.assertEqual(set(result), PLAN_KEYS)
        self.assertEqual((result["plan_outcome"], result["outcome"]), ("operator action required",) * 2)
        self.assertEqual((result["api_key_check"], result["lock_held"]), ("not_performed", False))
        self.assertFalse((self.audit_dir / ".monitoring.lock").exists())

    def test_due_cycle_without_any_key_check(self) -> None:
        self.collect()
        self.snapshot(when=T1)
        result = self.plan(now=lambda: T1 + timedelta(days=30))
        self.assertEqual((result["plan_outcome"], result["outcome"], result["due"]), ("ready", "ready", True))
        self.assertEqual(result["planned_steps"], ["new-run", "collect", "snapshot when complete", "compare"])
        self.assertEqual((result["active_state"], result["latest_snapshot"], result["previous_snapshot"]),
                         ("snapshotted", RUN_1, None))
        self.assertIs(result["requires_collection"], True)
        self.assertEqual((result["integrity_problems"], result["methodology_differences"]), (0, []))
        self.assertEqual(result["api_key_check"], "not_performed")
        self.assertFalse((self.audit_dir / ".monitoring.lock").exists())  # probing never creates it
        not_due = self.plan(now=lambda: T1 + timedelta(days=1))
        self.assertEqual((not_due["outcome"], not_due["due"], not_due["planned_steps"]), ("not due", False, []))

    def test_lock_held_by_another_process(self) -> None:
        self.collect()
        self.snapshot(when=T1)
        with AuditLock(self.audit_dir / ".monitoring.lock") as lock:
            lock.acquire(SLUG)
            result = self.plan(now=lambda: T1 + timedelta(days=30))
        self.assertEqual((result["plan_outcome"], result["outcome"], result["lock_held"]),
                         ("ready", "already running", True))

    def test_invalid_interval_and_unknown_audit(self) -> None:
        for interval in BAD_INTERVALS:
            with self.subTest(interval=interval):
                self.assert_api_error(400, "invalid_interval", get_monitoring_plan, SLUG, interval,
                                      audits_dir=self.audits)
        self.assert_api_error(404, "unknown_audit", get_monitoring_plan, "no-such-audit", 30, audits_dir=self.audits)
        self.assertFalse((self.audits / "no-such-audit").exists())


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


class ValidationTests(_ReadonlyTestCase):
    def test_invalid_slugs_are_refused_before_any_path_is_built(self) -> None:
        resources = [
            lambda s: get_audit(s, audits_dir=self.audits),
            lambda s: get_current_run(s, audits_dir=self.audits),
            lambda s: get_snapshots(s, audits_dir=self.audits),
            lambda s: get_snapshot(s, RUN_1, audits_dir=self.audits),
            lambda s: get_comparison(s, RUN_1, RUN_2, audits_dir=self.audits),
            lambda s: get_monitoring_plan(s, 30, audits_dir=self.audits),
        ]
        before = tree_state(self.root)
        for slug in BAD_SLUGS:
            for index, resource in enumerate(resources):
                with self.subTest(slug=slug, resource=index):
                    self.assert_api_error(400, "invalid_slug", resource, slug)
        self.assertEqual(tree_state(self.root), before)

    def test_long_slug_is_not_refused_for_its_length(self) -> None:
        self.assertGreater(len(LONG_SLUG), 100)
        # No audit with that slug: unknown, not invalid.
        for resource in (get_audit, get_current_run, get_snapshots):
            with self.subTest(resource=resource.__name__):
                self.assert_api_error(404, "unknown_audit", resource, LONG_SLUG, audits_dir=self.audits)
        # A real audit with that slug is served normally. (Built by copying the
        # fictional workspace: create_audit's staging path would exceed the
        # Windows path limit inside the temp folder - a fixture limit only.)
        shutil.copytree(self.audit_dir, self.audits / LONG_SLUG)
        config_path = self.audits / LONG_SLUG / "audit_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["slug"] = LONG_SLUG
        config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        detail = self.call(get_audit, LONG_SLUG, audits_dir=self.audits)
        self.assertEqual((detail["slug"], detail["current_run"]["state"]), (LONG_SLUG, "fresh"))
        self.assertEqual(self.call(get_current_run, LONG_SLUG, audits_dir=self.audits)["slug"], LONG_SLUG)
        self.assertEqual(self.call(get_snapshots, LONG_SLUG, audits_dir=self.audits)["snapshots"], [])
        plan = self.call(get_monitoring_plan, LONG_SLUG, 30, audits_dir=self.audits)
        self.assertEqual(plan["plan_outcome"], "operator action required")  # no baseline, not a slug error
        self.assertIn(LONG_SLUG, [a["slug"] for a in self.call(get_audits, audits_dir=self.audits)["audits"]])

    def test_invalid_run_ids(self) -> None:
        self.collect(limit=5)
        self.snapshot(when=T1, allow_partial=True)
        for run_id in BAD_RUN_IDS:
            with self.subTest(run_id=run_id):
                self.assert_api_error(400, "invalid_run_id", get_snapshot, SLUG, run_id, audits_dir=self.audits)
                self.assert_api_error(400, "invalid_run_id", get_comparison, SLUG, run_id, RUN_1,
                                      audits_dir=self.audits)
                self.assert_api_error(400, "invalid_run_id", get_comparison, SLUG, RUN_1, run_id,
                                      audits_dir=self.audits)


# --------------------------------------------------------------------------
# The real Boots demonstration audit (read-only)
# --------------------------------------------------------------------------


class BootsReadOnlyTests(_GuardedTestCase):
    def test_boots_resources_are_truthful_and_change_nothing(self) -> None:
        before = production_state()
        with self.forbid():
            health = get_health()
            listing = get_audits()
            detail = get_audit(BOOTS_SLUG)
            current = get_current_run(BOOTS_SLUG)
            history = get_snapshots(BOOTS_SLUG)
        self.assertEqual(production_state(), before)
        for value in (health, listing, detail, current, history):
            assert_json_safe(self, value)
        self.assertEqual([a["slug"] for a in listing["audits"]], [BOOTS_SLUG])
        self.assertEqual(listing["invalid_audits"], [])
        boots = listing["audits"][0]
        self.assertEqual((boots["latest_snapshot"], boots["snapshot_count"]), (None, 0))
        self.assertEqual(history, {"slug": BOOTS_SLUG, "snapshots": []})
        self.assertIsNone(detail["latest_snapshot"])
        self.assertEqual(detail["brand"], "Boots")
        committed = load_existing_results(str(REPO_ROOT / "audits" / BOOTS_SLUG / "audit_results.csv"))
        self.assertIs(current["current_run"]["readable"], True)
        self.assertEqual(current["current_run"]["result_row_count"], len(committed))
        self.assertEqual(current["row_basis"]["total_rows"], len(committed))
        self.assertEqual(current["current_run"]["requested_models"], [])  # no raw evidence is committed
        self.assertEqual(len(current["questions"]), current["current_run"]["question_count"])


if __name__ == "__main__":
    unittest.main()
