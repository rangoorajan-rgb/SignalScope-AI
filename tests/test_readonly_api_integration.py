"""End-to-end integration tests for the v2.6 read-only API (Checkpoint D4).

A real HTTP request goes to the real localhost server (create_server on
127.0.0.1:0), through the real handler and readonly_api resources, into the
existing SignalScope engines, and back as JSON. The resource layer is never
mocked. Fixtures are temporary audits collected with the real structured
batch (Gemini faked, SDK blocked). During every HTTP journey the Gemini
entry points, the .env loader, the key check and every mutating engine
function are patched to fail; the real audits/, reports/ and master
template are verified unchanged after every test.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import create_audit  # noqa: E402
from audit_history import create_snapshot, start_new_run  # noqa: E402
from readonly_api_server import BIND_HOST, create_server  # noqa: E402
from run_structured_batch_audit import run_structured_batch_audit  # noqa: E402
from version import SIGNALSCOPE_VERSION  # noqa: E402
from write_single_audit_result import RESULTS_SCHEMA, load_existing_results, write_results_atomically  # noqa: E402

SLUG = "lumiere-veloria-tea"
BOOTS_SLUG = "boots-uk-health-beauty"
T1 = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(hours=1)
RUN_1 = "20260601T090000Z"
RUN_2 = "20260601T100000Z"
FRONTEND_ORIGIN = "http://localhost:3000"

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
CITED = json.dumps({"brand_cited": "Y", "brand_position": 1, "competitors_cited": ["Brewvale"],
                    "sources_cited": ["Leaf Journal"], "sentiment": "Positive"})
NOT_CITED = json.dumps({"brand_cited": "N", "brand_position": None, "competitors_cited": ["Brewvale", "Steepwisé"],
                        "sources_cited": [], "sentiment": "Neutral"})

FORBIDDEN = (
    "gemini_client.generate_response",
    "gemini_client._load_dotenv",
    "response_analyzer.analyze_response",
    "run_structured_batch_audit.run_structured_batch_audit",
    "run_monitoring_cycle.run_monitoring_cycle",
    "run_monitoring_cycle.gemini_api_key_present",
    "audit_history.compare_snapshots",
    "audit_history.create_snapshot",
    "audit_history.start_new_run",
    "audit_history._write_report_atomically",
)
SUMMARY_FIELDS = ("run_id", "valid", "problems", "created_at", "status", "signalscope_version", "question_count",
                  "structurally_complete_count", "requested_models")


def tree_state(root: Path) -> dict:
    """Every path under root with its size and SHA-256."""
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
    paths = [*(REPO_ROOT / "questions").rglob("*"), *(REPO_ROOT / "audits").rglob("*"),
             *(REPO_ROOT / "reports").rglob("*")]
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in sorted(paths)}


def _reject_constant(name: str):
    raise ValueError(f"non-standard JSON constant {name}")


def strict_json(body: bytes):
    """Plain json.loads, refusing NaN/Infinity, then a recursive type check."""
    value = json.loads(body.decode("utf-8"), parse_constant=_reject_constant)

    def walk(v):
        if isinstance(v, dict):
            for k, item in v.items():
                assert isinstance(k, str), k
                walk(item)
        elif isinstance(v, list):
            for item in v:
                walk(item)
        else:
            assert v is None or isinstance(v, (str, bool, int, float)), repr(v)
            if isinstance(v, float):
                assert math.isfinite(v), v
            if isinstance(v, str):
                for leak in ("PosixPath(", "WindowsPath(", "SnapshotInfo(", "Progress(", "<object", "dataclass"):
                    assert leak not in v, v

    walk(value)
    return value


class Workspace:
    """A temporary project root holding fictional audits built with the
    released v2.2-v2.4 functions and the real structured batch (Gemini faked)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.audits = root / "audits"
        self.audits.mkdir()
        self.not_cited: set[str] = set()
        self.suffix = ""

    def create(self, **changes):
        data = {**CREATION_DATA, **changes}
        created = create_audit.create_audit_workspace(data, audits_dir=self.audits, reports_dir=self.root / "reports")
        from audit_runner import load_questions
        questions = load_questions(str(created.questions_file))
        return created, questions

    def collect(self, created, questions, limit) -> None:
        by_text = {q["question"]: q["question_id"] for q in questions}

        def answer(prompt: str) -> str:
            return f"For the question {prompt!r}: Lumière leads.\n" + "Detail; " * 80 + self.suffix

        def analysis(prompt: str) -> str:
            qid = next((q for text, q in by_text.items() if repr(text) in prompt), None)
            return NOT_CITED if qid in self.not_cited else CITED

        with patch("run_batch_audit.generate_response", side_effect=answer), \
                patch("response_analyzer.generate_response", side_effect=analysis), redirect_stdout(io.StringIO()):
            run_structured_batch_audit(str(created.questions_file), str(created.results_file), 0, limit,
                                       sleep_fn=lambda s: None, audit_config=created.config)

    def snapshot(self, slug, when):
        return create_snapshot(slug, audits_dir=self.audits, allow_partial=True, now=lambda: when)

    def new_run(self, slug) -> None:
        start_new_run(slug, audits_dir=self.audits)


class _IntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini client"))
        guard.start()
        self.addCleanup(guard.stop)
        before = production_state()

        def check() -> None:
            self.assertEqual(production_state(), before, "production audits/reports/questions changed")
            self.assertEqual(list((REPO_ROOT / "audits").glob("*/.monitoring.lock")), [])

        self.addCleanup(check)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Workspace(Path(tmp.name))

    def serve(self, **kwargs):
        server = create_server(0, **kwargs)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()

        def stop() -> None:
            server.shutdown()
            server.server_close()
            thread.join(10)
            self.assertFalse(thread.is_alive(), "server thread still running")

        self.addCleanup(stop)
        return server.server_address[1]

    def http(self, port: int, path: str, host: str | None = None, origin: str | None = None):
        conn = http.client.HTTPConnection(BIND_HOST, port, timeout=30)
        try:
            conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host or f"127.0.0.1:{port}")
            if origin:
                conn.putheader("Origin", origin)
            conn.endheaders()
            response = conn.getresponse()
            body = response.read()
            headers = {k.lower(): v for k, v in response.getheaders()}
        finally:
            conn.close()
        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        self.assertEqual(int(headers["content-length"]), len(body))
        self.assertEqual((headers["cache-control"], headers["x-content-type-options"]), ("no-store", "nosniff"))
        self.assertNotEqual(headers.get("access-control-allow-origin"), "*")
        return response.status, headers, strict_json(body), body

    def ok(self, port: int, path: str):
        status, _, payload, _ = self.http(port, path)
        self.assertEqual(status, 200, payload)
        return payload

    def forbid(self) -> ExitStack:
        stack = ExitStack()
        for target in FORBIDDEN:
            stack.enter_context(patch(target, side_effect=AssertionError(f"{target} must not be called")))
        return stack

    def assert_error(self, port: int, path: str, status: int, code: str) -> None:
        got, _, payload, body = self.http(port, path)
        self.assertEqual((got, set(payload), set(payload["error"]), payload["error"]["code"]),
                         (status, {"error"}, {"code", "message"}, code), payload)
        text = body.decode("utf-8")
        for leak in ("Traceback", str(self.ws.root), "File \"", "Error("):
            self.assertNotIn(leak, text)


# --------------------------------------------------------------------------
# The full read-only journey
# --------------------------------------------------------------------------


class FullJourneyTests(_IntegrationTestCase):
    """Two comparable snapshots (run 2 does not cite the brand on PA01-PA05)
    and a different, in-progress current run."""

    def setUp(self) -> None:
        super().setUp()
        self.created, self.questions = self.ws.create()
        self.ws.collect(self.created, self.questions, 10)
        self.ws.snapshot(SLUG, T1)
        self.ws.new_run(SLUG)
        self.ws.not_cited = {"PA01", "PA02", "PA03", "PA04", "PA05"}
        self.ws.suffix = "Run two."
        self.ws.collect(self.created, self.questions, 10)
        self.ws.snapshot(SLUG, T2)
        self.ws.new_run(SLUG)
        self.ws.not_cited = set()
        self.ws.suffix = "Run three."
        self.ws.collect(self.created, self.questions, 3)
        self.port = self.serve(audits_dir=self.ws.audits)

    def test_full_journey_is_consistent_and_read_only(self) -> None:
        env_before = dict(os.environ)
        before = tree_state(self.ws.root)
        timings = {}
        with self.forbid():
            responses = {}
            for name, path in (
                ("health", "/health"),
                ("audits", "/audits"),
                ("audit", f"/audits/{SLUG}"),
                ("current", f"/audits/{SLUG}/current-run"),
                ("snapshots", f"/audits/{SLUG}/snapshots"),
                ("older", f"/audits/{SLUG}/snapshots/{RUN_1}"),
                ("newer", f"/audits/{SLUG}/snapshots/{RUN_2}"),
                ("comparison", f"/audits/{SLUG}/comparison?from_run={RUN_1}&to_run={RUN_2}"),
                ("plan", f"/audits/{SLUG}/monitoring-plan?interval_days=30"),
            ):
                started = time.perf_counter()
                responses[name] = self.ok(self.port, path)
                timings[name] = time.perf_counter() - started
        self.assertEqual(tree_state(self.ws.root), before, "the HTTP journey changed the filesystem")
        self.assertEqual(dict(os.environ), env_before)
        self.assertNotIn("comparisons", json.dumps(sorted(before)))
        self.assertFalse((self.ws.root / "reports" / SLUG / "comparisons").exists())
        self.assertFalse((self.ws.audits / SLUG / ".monitoring.lock").exists())
        for name, seconds in timings.items():
            self.assertLess(seconds, 30, f"{name} took {seconds:.1f}s")  # pathological only
        sys.stderr.write("\nPERF " + json.dumps({k: round(v * 1000, 1) for k, v in timings.items()}) + " ms\n")

        health, listing, audit, current = (responses[k] for k in ("health", "audits", "audit", "current"))
        snapshots, older, newer = (responses[k] for k in ("snapshots", "older", "newer"))
        comparison, plan = responses["comparison"], responses["plan"]

        # G. version
        self.assertEqual((health["signalscope_version"], health["read_only"]), (SIGNALSCOPE_VERSION, True))

        # A. audit identity
        entry = next(a for a in listing["audits"] if a["slug"] == SLUG)
        for field in ("brand", "market", "category", "competitors"):
            self.assertEqual(entry[field], audit[field], field)
            self.assertEqual(audit[field], CREATION_DATA[field], field)

        # B. current run summary everywhere
        self.assertEqual(entry["current_run"], audit["current_run"])
        self.assertEqual(audit["current_run"], current["current_run"])
        self.assertEqual((current["current_run"]["state"], current["current_run"]["structurally_complete_count"]),
                         ("in progress / partial", 3))

        # C. latest snapshot
        self.assertEqual([s["run_id"] for s in snapshots["snapshots"]], [RUN_1, RUN_2])
        latest_listed = {k: snapshots["snapshots"][-1][k] for k in SUMMARY_FIELDS}
        self.assertEqual(entry["latest_snapshot"], latest_listed)
        self.assertEqual(audit["latest_snapshot"], latest_listed)
        self.assertEqual(entry["snapshot_count"], 2)

        # D + E. list entries equal detail summaries and metrics
        for listed, detail, is_latest in ((snapshots["snapshots"][0], older, False),
                                          (snapshots["snapshots"][1], newer, True)):
            self.assertEqual({k: listed[k] for k in SUMMARY_FIELDS}, detail["snapshot"])
            self.assertEqual(listed["metrics"], detail["metrics"])
            self.assertIs(detail["is_latest"], is_latest)
            self.assertTrue(detail["snapshot"]["valid"])
            self.assertEqual(len(detail["findings"]), 7)

        # F. comparison
        self.assertEqual((comparison["from_run"], comparison["to_run"], comparison["comparable"]),
                         (RUN_1, RUN_2, True))
        self.assertEqual(comparison["shared_question_count"], len(comparison["shared_question_ids"]))
        self.assertEqual(comparison["shared_question_count"], 10)
        self.assertEqual(len(comparison["metrics"]), 7)
        directions = {m["metric_name"]: m["direction"] for m in comparison["metrics"]}
        self.assertEqual(directions["Brand Visibility"], "Declined")
        self.assertTrue(any(d != "No Change" for d in directions.values()))

        # Monitoring plan: read-only view of the in-progress run
        self.assertEqual((plan["slug"], plan["active_state"], plan["latest_snapshot"], plan["previous_snapshot"]),
                         (SLUG, "in progress / partial", RUN_2, RUN_1))
        self.assertEqual((plan["api_key_check"], plan["lock_held"], plan["outcome"]), ("not_performed", False, "ready"))
        self.assertEqual(plan["planned_steps"], ["collect", "snapshot when complete", "compare"])

    def test_current_run_and_snapshots_stay_separate(self) -> None:
        with self.forbid():
            latest_before = self.http(self.port, f"/audits/{SLUG}/snapshots/{RUN_2}")[3]
            current_before = self.ok(self.port, f"/audits/{SLUG}/current-run")
        self.assertEqual(current_before["row_basis"]["total_rows"], 3)
        self.assertEqual(json.loads(latest_before)["row_basis"]["total_rows"], 10)
        self.assertNotEqual(current_before["metrics"], json.loads(latest_before)["metrics"])

        # Edit the current run after the snapshots were taken.
        rows = load_existing_results(str(self.created.results_file))
        manual = {name: "" for name in RESULTS_SCHEMA}
        manual.update({"run_date": "2026-06-03", "question_id": "PA01", "question": self.questions[0]["question"],
                       "funnel_stage": "Problem Awareness", "engine": "Perplexity", "brand_cited": "N",
                       "sentiment": "Negative", "answer_snippet": "Manual."})
        write_results_atomically(str(self.created.results_file), rows + [manual])
        config_path = self.ws.audits / SLUG / "audit_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["report_subject"] = "Edited Subject"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        with self.forbid():
            latest_after = self.http(self.port, f"/audits/{SLUG}/snapshots/{RUN_2}")[3]
            current_after = self.ok(self.port, f"/audits/{SLUG}/current-run")
            audit_after = self.ok(self.port, f"/audits/{SLUG}")
        self.assertEqual(latest_after, latest_before, "a current-run edit changed a snapshot response")
        self.assertEqual(current_after["row_basis"]["total_rows"], 4)
        self.assertEqual(current_after["row_basis"]["rows_by_engine"], {"Gemini": 3, "Perplexity": 1})
        self.assertEqual(audit_after["report_subject"], "Edited Subject")

    def test_browser_like_cors_journey(self) -> None:
        api_port = self.serve(audits_dir=self.ws.audits, allow_origin=FRONTEND_ORIGIN)
        with self.forbid():
            for path in ("/health", "/audits", f"/audits/{SLUG}"):
                with self.subTest(path=path):
                    status, headers, _, _ = self.http(api_port, path, host=f"localhost:{api_port}",
                                                      origin=FRONTEND_ORIGIN)
                    self.assertEqual(status, 200)
                    self.assertEqual((headers["access-control-allow-origin"], headers["vary"]),
                                     (FRONTEND_ORIGIN, "Origin"))
                    status, headers, _, _ = self.http(api_port, path, host=f"localhost:{api_port}",
                                                      origin="http://127.0.0.1:3000")
                    self.assertEqual(status, 200)
                    self.assertNotIn("access-control-allow-origin", headers)

    def test_real_error_envelopes(self) -> None:
        with self.forbid():
            self.assert_error(self.port, "/audits/Bad_Slug", 400, "invalid_slug")
            self.assert_error(self.port, "/audits/no-such-audit", 404, "unknown_audit")
            self.assert_error(self.port, f"/audits/{SLUG}/snapshots/2026-06-01", 400, "invalid_run_id")
            self.assert_error(self.port, f"/audits/{SLUG}/snapshots/20260601T110000Z", 404, "unknown_snapshot")
            self.assert_error(self.port, f"/audits/{SLUG}/monitoring-plan?interval_days=0", 400, "invalid_interval")
            self.assert_error(self.port, f"/audits/{SLUG}/comparison?from_run={RUN_1}&to_run={RUN_1}", 400,
                              "comparison_refused")


# --------------------------------------------------------------------------
# Separate fixtures
# --------------------------------------------------------------------------


class InvalidLatestSnapshotTests(_IntegrationTestCase):
    def test_invalid_latest_is_reported_without_fallback(self) -> None:
        created, questions = self.ws.create()
        self.ws.collect(created, questions, 5)
        self.ws.snapshot(SLUG, T1)
        self.ws.new_run(SLUG)
        self.ws.suffix = "Run two."
        self.ws.collect(created, questions, 5)
        self.ws.snapshot(SLUG, T2)
        with (self.ws.audits / SLUG / "snapshots" / RUN_2 / "audit_results.csv").open("a", encoding="utf-8") as fh:
            fh.write("\n")
        port = self.serve(audits_dir=self.ws.audits)
        before = tree_state(self.ws.root)
        with self.forbid():
            listing = self.ok(port, "/audits")
            audit = self.ok(port, f"/audits/{SLUG}")
            snapshots = self.ok(port, f"/audits/{SLUG}/snapshots")
            detail = self.ok(port, f"/audits/{SLUG}/snapshots/{RUN_2}")
            self.assert_error(port, f"/audits/{SLUG}/comparison?from_run={RUN_1}&to_run={RUN_2}", 409,
                              "snapshot_invalid")
        self.assertEqual(tree_state(self.ws.root), before)
        for latest in (listing["audits"][0]["latest_snapshot"], audit["latest_snapshot"]):
            self.assertEqual((latest["run_id"], latest["valid"]), (RUN_2, False))  # never the older valid one
        self.assertEqual([(s["run_id"], s["valid"]) for s in snapshots["snapshots"]], [(RUN_1, True), (RUN_2, False)])
        self.assertIsNone(snapshots["snapshots"][1]["metrics"])
        self.assertEqual((detail["snapshot"]["valid"], detail["metrics"], detail["findings"]), (False, None, []))
        self.assertTrue(detail["snapshot"]["problems"])


class NonComparableSnapshotTests(_IntegrationTestCase):
    def test_methodology_mismatch_is_a_normal_result(self) -> None:
        created, questions = self.ws.create()
        self.ws.collect(created, questions, 5)
        self.ws.snapshot(SLUG, T1)
        self.ws.new_run(SLUG)
        config_path = self.ws.audits / SLUG / "audit_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["competitors"] = list(reversed(config["competitors"]))
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        import audit_config
        created = SimpleNamespace(questions_file=created.questions_file, results_file=created.results_file,
                                  config=audit_config.load_audit_config(SLUG, audits_dir=self.ws.audits))
        self.ws.suffix = "Run two."
        self.ws.collect(created, questions, 5)
        self.ws.snapshot(SLUG, T2)
        port = self.serve(audits_dir=self.ws.audits)
        before = tree_state(self.ws.root)
        with self.forbid():
            result = self.ok(port, f"/audits/{SLUG}/comparison?from_run={RUN_1}&to_run={RUN_2}")
        self.assertEqual(tree_state(self.ws.root), before)
        self.assertEqual(set(result), {"slug", "from_run", "to_run", "comparable", "problems"})
        self.assertIs(result["comparable"], False)
        self.assertTrue(any("competitor order differs" in p for p in result["problems"]), result["problems"])


class FreshAuditTests(_IntegrationTestCase):
    def test_fresh_audit_has_no_fabricated_history(self) -> None:
        self.ws.create()
        port = self.serve(audits_dir=self.ws.audits)
        before = tree_state(self.ws.root)
        with self.forbid():
            listing = self.ok(port, "/audits")
            current = self.ok(port, f"/audits/{SLUG}/current-run")
            snapshots = self.ok(port, f"/audits/{SLUG}/snapshots")
        self.assertEqual(tree_state(self.ws.root), before)
        entry = listing["audits"][0]
        self.assertEqual((entry["snapshot_count"], entry["latest_snapshot"]), (0, None))
        self.assertEqual((current["current_run"]["state"], current["metrics"], current["findings"]), ("fresh", None, []))
        self.assertEqual(len(current["questions"]), 40)
        self.assertEqual(snapshots, {"slug": SLUG, "snapshots": []})


# --------------------------------------------------------------------------
# Production, CLI and import checks
# --------------------------------------------------------------------------


class BootsProductionSentinelTests(_IntegrationTestCase):
    def test_boots_read_only_requests(self) -> None:
        before = production_state()
        port = self.serve()  # production defaults
        with self.forbid():
            health = self.ok(port, "/health")
            listing = self.ok(port, "/audits")
            audit = self.ok(port, f"/audits/{BOOTS_SLUG}")
            current = self.ok(port, f"/audits/{BOOTS_SLUG}/current-run")
            snapshots = self.ok(port, f"/audits/{BOOTS_SLUG}/snapshots")
        self.assertEqual(production_state(), before)
        self.assertEqual(health["signalscope_version"], SIGNALSCOPE_VERSION)
        self.assertEqual([a["slug"] for a in listing["audits"]], [BOOTS_SLUG])
        self.assertEqual((listing["audits"][0]["snapshot_count"], audit["latest_snapshot"]), (0, None))
        self.assertIs(current["current_run"]["readable"], True)
        self.assertEqual(snapshots, {"slug": BOOTS_SLUG, "snapshots": []})


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((BIND_HOST, 0))
        return probe.getsockname()[1]


class CliSubprocessTests(unittest.TestCase):
    def test_real_cli_serves_health_and_stops(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        for attempt in range(3):  # the free-port handoff can race; retry with a new port
            port = _free_local_port()
            process = subprocess.Popen([sys.executable, str(SRC_DIR / "readonly_api_server.py"), "--port", str(port)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=REPO_ROOT)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        with socket.create_connection((BIND_HOST, port), timeout=0.5):
                            break
                    except OSError:
                        time.sleep(0.05)
                if process.poll() is not None:
                    continue  # the port was taken in between; try another
                conn = http.client.HTTPConnection(BIND_HOST, port, timeout=10)
                conn.request("GET", "/health")
                response = conn.getresponse()
                payload = strict_json(response.read())
                conn.close()
                self.assertEqual(response.status, 200)
                self.assertEqual((payload["status"], payload["read_only"]), ("ok", True))
                break
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=20)
                process.stdout.close()
                process.stderr.close()
        else:
            self.fail("could not start the CLI server on a free local port")
        self.assertIsNotNone(process.returncode)
        with self.assertRaises(OSError):
            socket.create_connection((BIND_HOST, port), timeout=1).close()


IMPORT_PROBE = r"""
import builtins, hashlib, io, json, os, socket, sys, threading, traceback
from pathlib import Path
repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "src"))

def state():
    paths = [*(repo / "questions").rglob("*"), *(repo / "audits").rglob("*"), *(repo / "reports").rglob("*")]
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in sorted(paths)}

before = state()
events = {"binds": [], "ipv6_capability_probes": 0, "listens": [], "writes": [], "env_reads": []}
real_bind, real_listen = socket.socket.bind, socket.socket.listen

def watched_bind(self, addr):
    # urllib3 (a transitive dependency) binds ('::1', 0) once at import to
    # detect IPv6 support, then closes the socket without listening.
    frames = traceback.extract_stack()
    if any(f.name == "_has_ipv6" and f.filename.replace("\\", "/").endswith("urllib3/util/connection.py")
           for f in frames) and addr == ("::1", 0):
        events["ipv6_capability_probes"] += 1
    else:
        events["binds"].append(str(addr))
    return real_bind(self, addr)

socket.socket.bind = watched_bind
socket.socket.listen = lambda self, *a: (events["listens"].append(1), real_listen(self, *a))[1]
real_open = io.open

def watched_open(file, mode="r", *args, **kwargs):
    if any(flag in mode for flag in "wax+"):
        events["writes"].append(str(file))
    if str(file).endswith(".env"):
        events["env_reads"].append(str(file))
    return real_open(file, mode, *args, **kwargs)

builtins.open = io.open = watched_open
from google import genai
clients = []
class Sentinel:
    def __init__(self, *a, **k):
        clients.append(1)
        raise AssertionError("client")
genai.Client = Sentinel
threads_before = threading.active_count()
env_before = dict(os.environ)
import readonly_api, readonly_api_server
print(json.dumps({**events, "clients": len(clients), "threads_added": threading.active_count() - threads_before,
                  "env_changed": dict(os.environ) != env_before, "production_changed": state() != before}))
"""


class ImportSideEffectTests(unittest.TestCase):
    def test_importing_the_api_modules_has_no_side_effects(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        completed = subprocess.run([sys.executable, "-c", IMPORT_PROBE, str(REPO_ROOT)], capture_output=True,
                                   text=True, env=env, cwd=REPO_ROOT, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout.strip().splitlines()[-1])
        probes = report.pop("ipv6_capability_probes")
        self.assertLessEqual(probes, 1)  # urllib3's import-time IPv6 check only: bind, close, never listen
        self.assertEqual(report, {"binds": [], "listens": [], "writes": [], "env_reads": [], "clients": 0,
                                  "threads_added": 0, "env_changed": False, "production_changed": False})


if __name__ == "__main__":
    unittest.main()
