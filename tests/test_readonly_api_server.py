"""Tests for src/readonly_api_server.py - v2.6 Checkpoint D3: the localhost
read-only HTTP transport over readonly_api.

Servers are created with create_server on 127.0.0.1:0 in a background
thread and always shut down; requests use http.client. Fictional audits
live in temporary directories, Gemini is blocked, every mutating engine
function is patched to fail, and the real audits/, reports/ and master
template are verified unchanged after every test.
"""

from __future__ import annotations

import ast
import hashlib
import http.client
import inspect
import io
import json
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import create_audit  # noqa: E402
import readonly_api  # noqa: E402
import readonly_api_server  # noqa: E402
from audit_history import create_snapshot, start_new_run  # noqa: E402
from readonly_api import READONLY_API_CONTRACT_VERSION, ReadonlyApiError  # noqa: E402
from readonly_api_server import BIND_HOST, create_server, parse_args  # noqa: E402
from run_structured_batch_audit import run_structured_batch_audit  # noqa: E402
from version import SIGNALSCOPE_VERSION  # noqa: E402

SLUG = "lumiere-veloria-tea"
BOOTS_SLUG = "boots-uk-health-beauty"
T1 = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(hours=1)
RUN_1 = "20260601T090000Z"
RUN_2 = "20260601T100000Z"
ORIGIN = "http://localhost:3000"

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
ANALYSIS_JSON = json.dumps({"brand_cited": "Y", "brand_position": 1, "competitors_cited": ["Brewvale"],
                            "sources_cited": ["Leaf Journal"], "sentiment": "Positive"})

RESOURCES = ("get_health", "get_audits", "get_audit", "get_current_run", "get_snapshots", "get_snapshot",
             "get_comparison", "get_monitoring_plan")
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
NOT_ALLOWED = ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


def tree_state(root: Path) -> dict:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


def production_state() -> dict:
    paths = [REPO_ROOT / "questions" / "buyer_questions_master.csv",
             *(REPO_ROOT / "audits").rglob("*"), *(REPO_ROOT / "reports").rglob("*")]
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in sorted(paths)}


class _ServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        guard = patch("gemini_client.genai.Client", side_effect=AssertionError("real Gemini client"))
        guard.start()
        self.addCleanup(guard.stop)
        before = production_state()

        def check() -> None:
            self.assertEqual(production_state(), before, "production audits/reports/template changed")
            self.assertEqual(list((REPO_ROOT / "audits").glob("*/.monitoring.lock")), [])

        self.addCleanup(check)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.audits = self.root / "audits"
        self.audits.mkdir()

    def start(self, **kwargs):
        server = create_server(0, **kwargs)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        return server

    def request(self, method: str, path: str, headers: dict | None = None):
        conn = http.client.HTTPConnection(BIND_HOST, self.port, timeout=15)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            body = response.read()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, body
        finally:
            conn.close()

    def get_json(self, path: str, headers: dict | None = None):
        status, response_headers, body = self.request("GET", path, headers)
        self.assert_standard_headers(response_headers, body)
        return status, response_headers, json.loads(body.decode("utf-8"))

    def assert_standard_headers(self, headers: dict, body: bytes, method: str = "GET") -> None:
        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        if method != "HEAD":
            self.assertEqual(int(headers["content-length"]), len(body))
        self.assertNotEqual(headers.get("access-control-allow-origin"), "*")

    def assert_error(self, path: str, status: int, code: str, message: str | None = None):
        got_status, _, payload = self.get_json(path)
        self.assertEqual(got_status, status, payload)
        self.assertEqual(set(payload), {"error"})
        self.assertEqual(set(payload["error"]), {"code", "message"})
        self.assertEqual(payload["error"]["code"], code)
        if message is not None:
            self.assertEqual(payload["error"]["message"], message)
        return payload

    def forbid(self) -> ExitStack:
        stack = ExitStack()
        for target in FORBIDDEN:
            stack.enter_context(patch(target, side_effect=AssertionError(f"{target} must not be called")))
        return stack

    def resources_must_not_run(self) -> ExitStack:
        stack = ExitStack()
        for name in RESOURCES:
            stack.enter_context(patch(f"readonly_api.{name}", side_effect=AssertionError(f"{name} was called")))
        return stack


class _FixtureTestCase(_ServerTestCase):
    """A fictional audit with two comparable (partial) snapshots."""

    def setUp(self) -> None:
        super().setUp()
        created = create_audit.create_audit_workspace(CREATION_DATA, audits_dir=self.audits,
                                                      reports_dir=self.root / "reports")
        self.config = created.config
        self.questions_path, self.results_path = str(created.questions_file), str(created.results_file)
        with patch("run_batch_audit.generate_response", side_effect=self._answer), \
                patch("response_analyzer.generate_response", return_value=ANALYSIS_JSON):
            self.collect()
            create_snapshot(SLUG, audits_dir=self.audits, allow_partial=True, now=lambda: T1)
            start_new_run(SLUG, audits_dir=self.audits)
            self.suffix = "Run two."
            self.collect()
            create_snapshot(SLUG, audits_dir=self.audits, allow_partial=True, now=lambda: T2)

    suffix = ""

    def _answer(self, prompt: str) -> str:
        return f"For the question {prompt!r}: Lumière leads.\n" + "Detail; " * 80 + self.suffix

    def collect(self) -> None:
        with redirect_stdout(io.StringIO()):
            run_structured_batch_audit(self.questions_path, self.results_path, 0, 5, sleep_fn=lambda s: None,
                                       audit_config=self.config)


# --------------------------------------------------------------------------
# Health, headers and binding
# --------------------------------------------------------------------------


class HealthAndBindingTests(_ServerTestCase):
    def test_health(self) -> None:
        server = self.start()
        with self.forbid():
            status, headers, payload = self.get_json("/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok", "signalscope_version": SIGNALSCOPE_VERSION,
                                   "contract_version": READONLY_API_CONTRACT_VERSION, "read_only": True})
        self.assertEqual(server.server_address[0], "127.0.0.1")
        self.assertNotIn("access-control-allow-origin", headers)

    def test_binds_only_to_ipv4_loopback(self) -> None:
        server = self.start()
        self.assertEqual(server.server_address[0], "127.0.0.1")
        self.assertEqual(BIND_HOST, "127.0.0.1")
        self.assertNotIn("host", inspect.signature(create_server).parameters)
        self.assertNotIn("--host", parse_args.__code__.co_consts.__repr__())
        for bad in (-1, 65536, 1.5, True, "8765"):
            with self.subTest(port=bad):
                with self.assertRaises(ValueError):
                    create_server(bad)

    def test_standard_headers_on_every_kind_of_response(self) -> None:
        self.start()
        with patch("readonly_api.get_audit", side_effect=RuntimeError("boom")):
            for method, path in (("GET", "/health"), ("GET", "/nope"), ("POST", "/health"), ("GET", "/audits/Bad"),
                                 ("GET", "/audits/x/monitoring-plan"), ("GET", "/audits/x"), ("HEAD", "/health")):
                with self.subTest(method=method, path=path):
                    _, headers, body = self.request(method, path)
                    self.assert_standard_headers(headers, body, method)
                    self.assertEqual(headers.get("connection"), "close")

    def test_module_is_a_thin_transport(self) -> None:
        tree = ast.parse(Path(readonly_api_server.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"__future__", "argparse", "json", "re", "sys", "http.server", "pathlib",
                                    "urllib.parse", "readonly_api"})
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
               {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("open", "write_text", "write_bytes", "environ", "getenv", "mkdir", "unlink",
                          "compare_snapshots", "compute_snapshot_comparison", "list_snapshots", "plan_cycle",
                          "load_existing_results", "print_exc", "format_exc"):
            self.assertNotIn(forbidden, used)
        called = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                  and isinstance(n.value, ast.Name) and n.value.id == "readonly_api"}
        self.assertEqual(called, set(RESOURCES))


# --------------------------------------------------------------------------
# Routes (real resources over temporary fixtures)
# --------------------------------------------------------------------------


class RouteTests(_FixtureTestCase):
    ROUTES = {
        "/health": ("get_health", (), {}),
        "/audits": ("get_audits", (), {"audits_dir": None}),
        f"/audits/{SLUG}": ("get_audit", (SLUG,), {"audits_dir": None}),
        f"/audits/{SLUG}/current-run": ("get_current_run", (SLUG,), {"audits_dir": None}),
        f"/audits/{SLUG}/snapshots": ("get_snapshots", (SLUG,), {"audits_dir": None}),
        f"/audits/{SLUG}/snapshots/{RUN_2}": ("get_snapshot", (SLUG, RUN_2), {"audits_dir": None}),
        f"/audits/{SLUG}/comparison?from_run={RUN_1}&to_run={RUN_2}":
            ("get_comparison", (SLUG, RUN_1, RUN_2), {"audits_dir": None}),
        f"/audits/{SLUG}/monitoring-plan?interval_days=30":
            ("get_monitoring_plan", (SLUG, 30), {"audits_dir": None}),
    }

    def test_each_route_calls_its_resource_and_returns_its_json(self) -> None:
        self.start(audits_dir=self.audits)
        before = tree_state(self.root)
        for path, (name, args, kwargs) in self.ROUTES.items():
            with self.subTest(path=path):
                real = getattr(readonly_api, name)
                kwargs = {k: self.audits for k in kwargs}
                expected = real(*args, **kwargs)
                with self.forbid(), patch(f"readonly_api.{name}", wraps=real) as spy:
                    status, _, payload = self.get_json(path)
                self.assertEqual(status, 200, payload)
                spy.assert_called_once_with(*args, **kwargs)
                self.assertEqual(payload, json.loads(json.dumps(expected)))
        self.assertEqual(tree_state(self.root), before)  # the whole HTTP pass wrote nothing
        self.assertFalse((self.root / "reports" / SLUG / "comparisons").exists())
        self.assertFalse((self.audits / SLUG / ".monitoring.lock").exists())

    def test_normal_percent_encoding_is_decoded_per_segment(self) -> None:
        self.start(audits_dir=self.audits)
        encoded_slug = "%6Cumiere-veloria-tea"
        encoded_run = "2026%30601T100000Z"
        with patch("readonly_api.get_snapshot", wraps=readonly_api.get_snapshot) as spy:
            status, _, payload = self.get_json(f"/audits/{encoded_slug}/snapshots/{encoded_run}")
        self.assertEqual(status, 200, payload)
        spy.assert_called_once_with(SLUG, RUN_2, audits_dir=self.audits)
        with patch("readonly_api.get_comparison", wraps=readonly_api.get_comparison) as spy:
            status, _, payload = self.get_json(
                f"/audits/{SLUG}/comparison?from_run=%32{RUN_1[1:]}&to_run={RUN_2}")
        self.assertEqual((status, payload["comparable"]), (200, True))
        spy.assert_called_once_with(SLUG, RUN_1, RUN_2, audits_dir=self.audits)

    def test_resource_errors_pass_through(self) -> None:
        self.start(audits_dir=self.audits)
        self.assert_error("/audits/no-such-audit", 404, "unknown_audit")
        self.assert_error("/audits/Bad", 400, "invalid_slug")
        self.assert_error(f"/audits/{SLUG}/snapshots/20261301T090000Z", 400, "invalid_run_id")
        self.assert_error(f"/audits/{SLUG}/comparison?from_run={RUN_2}&to_run={RUN_1}", 400, "comparison_refused")
        self.assert_error(f"/audits/{SLUG}/monitoring-plan?interval_days=0", 400, "invalid_interval")
        with (self.audits / SLUG / "snapshots" / RUN_2 / "audit_results.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        self.assert_error(f"/audits/{SLUG}/comparison?from_run={RUN_1}&to_run={RUN_2}", 409, "snapshot_invalid")


class UnknownRouteAndMethodTests(_ServerTestCase):
    def test_unknown_routes_are_json_404s(self) -> None:
        self.start(audits_dir=self.audits)
        with self.resources_must_not_run():
            for path in ("/", "/version", "/trend", "/findings", "/create", "/run", "/snapshot", "/new-run",
                         "/monitor", "/recommendations", "/raw-responses", "/health/", "/audits/x/findings",
                         "/audits/x/snapshots/y/z", "/audits/x/raw-responses", "/audits/x/new-run", "/AUDITS",
                         "/%61udits", "/audits/x/current-run/extra", "/index.html"):
                with self.subTest(path=path):
                    payload = self.assert_error(path, 404, "not_found", "No such resource.")
                    self.assertNotIn(str(self.root), json.dumps(payload))

    def test_only_get_is_allowed(self) -> None:
        self.start(audits_dir=self.audits)
        with self.resources_must_not_run():
            for method in NOT_ALLOWED:
                for path in ("/health", "/audits", f"/audits/{SLUG}"):
                    with self.subTest(method=method, path=path):
                        status, headers, body = self.request(method, path)
                        self.assertEqual(status, 405)
                        self.assertEqual(headers["allow"], "GET")
                        self.assert_standard_headers(headers, body, method)
                        if method == "HEAD":
                            self.assertEqual(body, b"")  # HEAD never carries a body; health not run
                        else:
                            self.assertEqual(json.loads(body), {"error": {"code": "method_not_allowed",
                                                                          "message": "Only GET is supported."}})
            status, headers, body = self.request("TRACE", "/health")
        self.assertEqual((status, headers["allow"]), (405, "GET"))
        self.assertEqual(json.loads(body)["error"]["code"], "method_not_allowed")


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ErrorMappingTests(_ServerTestCase):
    def test_readonly_api_errors_map_exactly(self) -> None:
        self.start(audits_dir=self.audits)
        for status, code, message in ((400, "invalid_slug", "bad slug text"), (404, "unknown_snapshot", "no snap"),
                                      (409, "snapshot_invalid", "Snapshot X failed validation")):
            with self.subTest(code=code):
                with patch("readonly_api.get_audit", side_effect=ReadonlyApiError(status, code, message)):
                    self.assert_error("/audits/any-audit", status, code, message)

    def test_unexpected_errors_reveal_nothing(self) -> None:
        self.start(audits_dir=self.audits)
        secret = "sk-FAKE-SECRET-123"
        fake_path = "C:\\Users\\Someone\\secret-audits\\client.csv"
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("readonly_api.get_current_run",
                                            side_effect=RuntimeError(f"{fake_path} token={secret}")):
            status, _, body = self.request("GET", "/audits/any-audit/current-run")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body), {"error": {"code": "internal_error", "message": "Internal server error."}})
        for leaked in (secret, "secret-audits", "RuntimeError", "Traceback", "token="):
            self.assertNotIn(leaked, body.decode("utf-8"))
            self.assertNotIn(leaked, stderr.getvalue())

    def test_non_json_safe_result_is_an_internal_error(self) -> None:
        self.start()
        with patch("readonly_api.get_health", return_value={"value": float("nan")}):
            self.assert_error("/health", 500, "internal_error", "Internal server error.")

    def test_fields_are_passed_through_unchanged(self) -> None:
        self.start()
        odd = {"weird_Key": [1, {"nested": None, "flag": False}], "unicode": "Lumière — é", "n": 1.25}
        with patch("readonly_api.get_health", return_value=odd):
            status, _, payload = self.get_json("/health")
        self.assertEqual((status, payload), (200, odd))


# --------------------------------------------------------------------------
# Path safety and query rules
# --------------------------------------------------------------------------


class PathSafetyTests(_ServerTestCase):
    UNSAFE = ("%2F", "%2f", "%5C", "%5c", "%0A", "%0D", "%00", "%01", "%1F", "%7F", "%09")
    MALFORMED = ("%", "%2", "%zz", "%G1", "%E0%A4", "%C3%28")

    def test_unsafe_slug_segments(self) -> None:
        self.start(audits_dir=self.audits)
        with self.resources_must_not_run():
            for escape in self.UNSAFE + self.MALFORMED:
                for template in ("/audits/lumiere{e}tea", "/audits/lumiere{e}tea/current-run",
                                 "/audits/{e}/snapshots", "/audits/a{e}/comparison?from_run=x&to_run=y",
                                 "/audits/..{e}..{e}etc/monitoring-plan?interval_days=1"):
                    path = template.format(e=escape)
                    with self.subTest(path=path):
                        self.assert_error(path, 400, "invalid_slug")

    def test_unsafe_run_id_segments(self) -> None:
        self.start(audits_dir=self.audits)
        with self.resources_must_not_run():
            for escape in self.UNSAFE + self.MALFORMED:
                path = f"/audits/{SLUG}/snapshots/20260601T090000Z{escape}"
                with self.subTest(path=path):
                    self.assert_error(path, 400, "invalid_run_id")
            self.assert_error(f"/audits/{SLUG}/snapshots/..%2F..%2Faudit_config.json", 400, "invalid_run_id")

    def test_trailing_newline_slug_never_reaches_the_resource(self) -> None:
        self.start(audits_dir=self.audits)
        with self.resources_must_not_run():
            self.assert_error(f"/audits/{SLUG}%0A", 400, "invalid_slug")
            self.assert_error(f"/audits/{SLUG}%0A/current-run", 400, "invalid_slug")


class QueryRuleTests(_ServerTestCase):
    def test_comparison_parameters(self) -> None:
        self.start(audits_dir=self.audits)
        base = f"/audits/{SLUG}/comparison"
        with self.resources_must_not_run():
            for query in ("", f"?to_run={RUN_2}", f"?from_run={RUN_1}", f"?from_run={RUN_1}&from_run={RUN_1}&to_run={RUN_2}",
                          f"?from_run={RUN_1}&to_run={RUN_2}&to_run={RUN_2}"):
                with self.subTest(query=query):
                    self.assert_error(base + query, 400, "comparison_refused")

    def test_monitoring_interval_syntax(self) -> None:
        self.start(audits_dir=self.audits)
        base = f"/audits/{SLUG}/monitoring-plan"
        with self.resources_must_not_run():
            for query in ("", "?interval_days=30&interval_days=30", "?interval_days=", "?interval_days=abc",
                          "?interval_days=1.5", "?interval_days=-1", "?interval_days=%2B3", "?interval_days=3%20",
                          "?interval_days=%D9%A3", "?days=30"):
                with self.subTest(query=query):
                    self.assert_error(base + query, 400, "invalid_interval")
        with patch("readonly_api.get_monitoring_plan", return_value={"ok": True}) as plan:
            self.get_json(base + "?interval_days=0030")
        plan.assert_called_once_with(SLUG, 30, audits_dir=self.audits)
        self.assertIs(type(plan.call_args.args[1]), int)


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------


class CorsTests(_ServerTestCase):
    def test_no_configured_origin_sends_no_cors_header(self) -> None:
        self.start()
        _, headers, _ = self.get_json("/health", {"Origin": ORIGIN})
        self.assertNotIn("access-control-allow-origin", headers)

    def test_exact_origin_only(self) -> None:
        self.start(allow_origin=ORIGIN)
        _, headers, _ = self.get_json("/health", {"Origin": ORIGIN})
        self.assertEqual((headers["access-control-allow-origin"], headers["vary"]), (ORIGIN, "Origin"))
        for other in ("http://localhost:3001", "http://evil.example", "https://localhost:3000", "null",
                      ORIGIN + "/", "HTTP://localhost:3000"):
            with self.subTest(origin=other):
                _, headers, _ = self.get_json("/health", {"Origin": other})
                self.assertNotIn("access-control-allow-origin", headers)
        _, headers, _ = self.get_json("/health")
        self.assertNotIn("access-control-allow-origin", headers)
        status, headers, _ = self.request("OPTIONS", "/health", {"Origin": ORIGIN,
                                                                 "Access-Control-Request-Method": "GET"})
        self.assertEqual(status, 405)
        self.assertNotEqual(headers.get("access-control-allow-origin"), "*")
        self.assertNotIn("access-control-allow-credentials", headers)

    def test_origin_configuration_is_validated(self) -> None:
        for bad in ("*", "localhost:3000", "http://localhost:3000/", "http://localhost:3000/app", "ftp://x",
                    "http://user@localhost:3000", "http://localhost:3000?x=1", ""):
            with self.subTest(origin=bad):
                with self.assertRaises(ValueError):
                    create_server(0, allow_origin=bad)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class CliTests(unittest.TestCase):
    def test_arguments(self) -> None:
        args = parse_args([])
        self.assertEqual((args.port, args.allow_origin), (8765, None))
        args = parse_args(["--port", "9000", "--allow-origin", ORIGIN])
        self.assertEqual((args.port, args.allow_origin), (9000, ORIGIN))
        for argv in (["--port", "0"], ["--port", "65536"], ["--port", "-1"], ["--port", "abc"], ["--port", "1.5"],
                     ["--allow-origin", "*"], ["--allow-origin", "http://localhost:3000/x"], ["--host", "0.0.0.0"],
                     ["--audits-dir", "x"]):
            with self.subTest(argv=argv):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                    parse_args(argv)
                self.assertEqual(ctx.exception.code, 2)

    def test_help(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("127.0.0.1", out.getvalue())
        self.assertNotIn("--host", out.getvalue())


# --------------------------------------------------------------------------
# The real Boots demonstration audit over HTTP (read-only)
# --------------------------------------------------------------------------


class BootsHttpTests(_ServerTestCase):
    def test_boots_endpoints_are_truthful_and_change_nothing(self) -> None:
        before = production_state()
        self.start()  # production defaults
        with self.forbid():
            results = {path: self.get_json(path) for path in (
                "/health", "/audits", f"/audits/{BOOTS_SLUG}", f"/audits/{BOOTS_SLUG}/current-run",
                f"/audits/{BOOTS_SLUG}/snapshots")}
        self.assertEqual(production_state(), before)
        self.assertTrue(all(status == 200 for status, _, _ in results.values()))
        listing = results["/audits"][2]
        self.assertEqual([a["slug"] for a in listing["audits"]], [BOOTS_SLUG])
        self.assertEqual((listing["audits"][0]["snapshot_count"], listing["audits"][0]["latest_snapshot"]), (0, None))
        self.assertEqual(results[f"/audits/{BOOTS_SLUG}/snapshots"][2], {"slug": BOOTS_SLUG, "snapshots": []})
        self.assertIs(results[f"/audits/{BOOTS_SLUG}/current-run"][2]["current_run"]["readable"], True)
        self.assertEqual(results[f"/audits/{BOOTS_SLUG}"][2]["brand"], "Boots")


# --------------------------------------------------------------------------
# Host header validation (DNS-rebinding defence)
# --------------------------------------------------------------------------


class HostHeaderTests(_ServerTestCase):
    INVALID = {"error": {"code": "bad_request", "message": "Invalid Host header."}}

    def setUp(self) -> None:
        super().setUp()
        self.start(allow_origin=ORIGIN)
        self.other_port = self.port % 65535 + 1  # any port that is not this server's

    def with_host(self, host_values, method="GET", path="/health", headers=None):
        """A request whose Host header(s) are set explicitly (http.client adds none)."""
        conn = http.client.HTTPConnection(BIND_HOST, self.port, timeout=15)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for value in host_values:
                conn.putheader("Host", value)
            for name, value in (headers or {}).items():
                conn.putheader(name, value)
            conn.endheaders()
            response = conn.getresponse()
            body = response.read()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, body
        finally:
            conn.close()

    def raw(self, data: bytes):
        """Local raw-socket request to this 127.0.0.1 test server only."""
        with socket.create_connection((BIND_HOST, self.port), timeout=15) as sock:
            sock.sendall(data)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1").split("\r\n")
        status = int(lines[0].split()[1])
        headers = {k.strip().lower(): v.strip() for k, v in (line.split(":", 1) for line in lines[1:])}
        return status, headers, body

    def assert_refused(self, response, method="GET") -> None:
        status, headers, body = response
        self.assertEqual(status, 400)
        self.assert_standard_headers(headers, body, method)
        if method != "HEAD":
            self.assertEqual(json.loads(body), self.INVALID)
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertNotIn("vary", headers)

    def test_a_local_hosts_on_this_port_are_accepted(self) -> None:
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"LOCALHOST:{self.port}",
                     f"LocalHost:{self.port}"):
            with self.subTest(host=host):
                with patch("readonly_api.get_health", wraps=readonly_api.get_health) as health:
                    status, headers, body = self.with_host([host])
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["status"], "ok")
                health.assert_called_once_with()
                self.assert_standard_headers(headers, body)

    def test_dns_rebinding_hostname_is_refused_before_any_resource(self) -> None:
        # A page on attacker.example that rebinds its name to 127.0.0.1 makes
        # "same-origin" requests carrying Host: attacker.example:<port>.
        # CORS cannot stop that; the Host check must, before any resource runs.
        with patch("readonly_api.get_health", side_effect=AssertionError("resource reached")) as health:
            self.assert_refused(self.with_host([f"attacker.example:{self.port}"]))
        self.assertEqual(health.call_count, 0)

    def test_b_wrong_hostnames(self) -> None:
        with self.resources_must_not_run():
            for host in (f"evil.example:{self.port}", f"localhost.evil.example:{self.port}",
                         f"127.0.0.1.evil.example:{self.port}", f"attacker.test:{self.port}"):
                with self.subTest(host=host):
                    self.assert_refused(self.with_host([host]))

    def test_c_wrong_port(self) -> None:
        with self.resources_must_not_run():
            for host in (f"127.0.0.1:{self.other_port}", f"localhost:{self.other_port}"):
                with self.subTest(host=host):
                    self.assert_refused(self.with_host([host]))

    def test_d_unsafe_and_malformed_hosts(self) -> None:
        port = self.port
        bad = ["", " ", "*", "127.0.0.1", "localhost", f":{port}", f"127.0.0.1 :{port}", f"127.0.0.1: {port}",
               f"127.0.0.1:{port} x", f"127.0.0.1:{port}\tx", f"127.0.0.1:{port}\x0b", "127.0.0.1:abc",
               "127.0.0.1:99999", "127.0.0.1:65536", "127.0.0.1:0", f"127.0.0.1:{port}:1", f"127.0.0.1:+{port}",
               f"user@localhost:{port}", f"0.0.0.0:{port}", f"127.0.0.2:{port}", f"[::1]:{port}",
               f"localhost.:{port}", f"sub.localhost:{port}", f"127.1:{port}", f"2130706433:{port}",
               f"localhost%00:{port}"]
        with self.resources_must_not_run():
            for host in bad:
                with self.subTest(host=host):
                    self.assert_refused(self.with_host([host]))
            with self.subTest(host="missing"):
                self.assert_refused(self.with_host([]))

    def test_d_control_characters_and_http10_via_raw_socket(self) -> None:
        port = self.port
        with self.resources_must_not_run():
            for request in (
                f"GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\rX\r\n\r\n",
                f"GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\x00\r\n\r\n",
                "GET /health HTTP/1.0\r\n\r\n",
                f"GET /health HTTP/1.1\r\nHost: evil.example\r\n :{port}\r\n\r\n",
            ):
                with self.subTest(request=request):
                    status, headers, body = self.raw(request.encode("iso-8859-1"))
                    self.assertEqual(status, 400)
                    self.assertEqual(json.loads(body)["error"]["code"], "bad_request")
                    self.assertNotIn("access-control-allow-origin", headers)

    def test_e_duplicate_host_headers(self) -> None:
        valid = f"127.0.0.1:{self.port}"
        with self.resources_must_not_run():
            self.assert_refused(self.with_host([valid, valid]))
            self.assert_refused(self.with_host([valid, f"evil.example:{self.port}"]))
            status, _, body = self.raw(f"GET /health HTTP/1.1\r\nHost: {valid}\r\nHost: {valid}\r\n\r\n"
                                       .encode("ascii"))
        self.assertEqual((status, json.loads(body)), (400, self.INVALID))

    def test_f_cors_is_never_applied_to_a_refused_host(self) -> None:
        with self.resources_must_not_run():
            self.assert_refused(self.with_host([f"evil.example:{self.port}"], headers={"Origin": ORIGIN}))
        status, headers, _ = self.with_host([f"localhost:{self.port}"], headers={"Origin": ORIGIN})
        self.assertEqual((status, headers["access-control-allow-origin"], headers["vary"]), (200, ORIGIN, "Origin"))

    def test_g_host_check_precedes_method_dispatch_and_path_decoding(self) -> None:
        valid, invalid = f"127.0.0.1:{self.port}", f"evil.example:{self.port}"
        with self.resources_must_not_run():
            status, headers, body = self.with_host([valid], method="POST")
            self.assertEqual((status, headers["allow"]), (405, "GET"))
            self.assertEqual(json.loads(body)["error"]["code"], "method_not_allowed")
            for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"):
                with self.subTest(method=method):
                    response = self.with_host([invalid], method=method)
                    self.assert_refused(response, method)
                    self.assertNotIn("allow", response[1])
            # An unsafe path is not even decoded when the Host is wrong.
            self.assert_refused(self.with_host([invalid], path="/audits/%00/current-run"))
            self.assert_refused(self.with_host([invalid], path="/no-such-route"))


if __name__ == "__main__":
    unittest.main()
