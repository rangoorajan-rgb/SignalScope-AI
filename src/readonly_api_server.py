"""Localhost read-only HTTP transport for SignalScope AI (v2.6).

A thin standard-library server over readonly_api: it parses the URL,
selects one of eight GET routes, calls the matching readonly_api resource
and serialises its result as JSON. It holds no business rules - slug,
run-ID and interval semantics, metrics and every error classification
come from readonly_api - and it never writes a file, calls Gemini or reads
the Gemini key.

It binds only to the IPv4 loopback address, accepts only requests whose
Host header names this server (127.0.0.1 or localhost with its own port -
a DNS-rebinding defence), answers only GET, and adds a CORS header only
for one exactly configured origin.

    python src/readonly_api_server.py [--port 8765] [--allow-origin http://localhost:3000]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import readonly_api
from readonly_api import ReadonlyApiError

BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
ALLOWED_METHODS = "GET"

_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_HOST_HEADER = re.compile(r"([A-Za-z0-9.]+):([0-9]{1,5})")
_LOCAL_HOSTNAMES = ("127.0.0.1", "localhost")
_DIGITS = re.compile(r"[0-9]+")


class _TransportRefusal(Exception):
    """A request the transport refuses before any resource is called."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _decode_segment(raw: str, code: str) -> str:
    """Percent-decode one raw path segment. Transport safety only (not the
    slug or run-ID grammar): malformed escapes, invalid UTF-8, a decoded
    '/' or '\\', and ASCII control characters are refused."""
    if _PERCENT_ESCAPE.search(raw):
        raise _TransportRefusal(400, code, "Malformed percent-encoding in the request path.")
    try:
        decoded = unquote(raw, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        raise _TransportRefusal(400, code, "The request path is not valid UTF-8.") from None
    if "/" in decoded or "\\" in decoded:
        raise _TransportRefusal(400, code, "A path segment may not contain '/' or '\\'.")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in decoded):
        raise _TransportRefusal(400, code, "A path segment may not contain control characters.")
    return decoded


def _single(query: dict[str, list[str]], name: str, code: str) -> str:
    values = query.get(name, [])
    if len(values) != 1:
        raise _TransportRefusal(400, code, f"The query parameter {name!r} must be given exactly once.")
    return values[0]


def _route(path: str, query_string: str, audits_dir):
    """Select the resource for a request: returns a zero-argument callable.
    Routes are matched on the raw (undecoded) path structure, then each
    variable segment is decoded on its own."""
    if not path.startswith("/"):
        raise _TransportRefusal(404, "not_found", "No such resource.")
    segments = path[1:].split("/")

    if segments == ["health"]:
        return lambda: readonly_api.get_health()
    if segments == ["audits"]:
        return lambda: readonly_api.get_audits(audits_dir=audits_dir)
    if not segments or segments[0] != "audits" or not 2 <= len(segments) <= 4:
        raise _TransportRefusal(404, "not_found", "No such resource.")

    tail = segments[2:]
    if tail not in ([], ["current-run"], ["snapshots"], ["comparison"], ["monitoring-plan"]) and not (
        len(tail) == 2 and tail[0] == "snapshots"
    ):
        raise _TransportRefusal(404, "not_found", "No such resource.")
    slug = _decode_segment(segments[1], "invalid_slug")

    if tail == []:
        return lambda: readonly_api.get_audit(slug, audits_dir=audits_dir)
    if tail == ["current-run"]:
        return lambda: readonly_api.get_current_run(slug, audits_dir=audits_dir)
    if tail == ["snapshots"]:
        return lambda: readonly_api.get_snapshots(slug, audits_dir=audits_dir)
    if tail[0] == "snapshots":
        run_id = _decode_segment(tail[1], "invalid_run_id")
        return lambda: readonly_api.get_snapshot(slug, run_id, audits_dir=audits_dir)

    query = parse_qs(query_string, keep_blank_values=True)
    if tail == ["comparison"]:
        from_run = _single(query, "from_run", "comparison_refused")
        to_run = _single(query, "to_run", "comparison_refused")
        return lambda: readonly_api.get_comparison(slug, from_run, to_run, audits_dir=audits_dir)
    interval = _single(query, "interval_days", "invalid_interval")
    if not _DIGITS.fullmatch(interval):
        raise _TransportRefusal(400, "invalid_interval", "interval_days must be a whole number of days.")
    return lambda: readonly_api.get_monitoring_plan(slug, int(interval), audits_dir=audits_dir)


class ReadonlyApiHandler(BaseHTTPRequestHandler):
    server_version = "SignalScope-ReadOnly"
    sys_version = ""
    _host_ok = False

    def _host_is_local(self) -> bool:
        """Exactly one Host header naming this server: 127.0.0.1 or localhost
        (case-insensitive) with the port it is listening on. Textual only -
        no DNS lookup - so a hostname rebound to 127.0.0.1 is refused."""
        headers = getattr(self, "headers", None)
        if headers is None or headers.defects:  # e.g. a bare CR splitting the Host line
            return False
        values = headers.get_all("Host", [])
        if len(values) != 1:
            return False
        match = _HOST_HEADER.fullmatch(values[0])
        if not match:
            return False
        hostname, port = match.group(1).lower(), int(match.group(2))
        return hostname in _LOCAL_HOSTNAMES and port == self.server.server_address[1]

    def _refuse_host(self) -> None:
        self._send(400, self._encode(_error("bad_request", "Invalid Host header.")))

    def do_GET(self) -> None:
        self._host_ok = self._host_is_local()
        if not self._host_ok:  # before any routing, decoding or resource call
            self._refuse_host()
            return
        try:
            parts = urlsplit(self.path)
            call = _route(parts.path, parts.query, self.server.audits_dir)
            status, payload = 200, call()
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ReadonlyApiError, _TransportRefusal) as exc:
            status, body = exc.status, self._encode(_error(exc.code, exc.message))
        except Exception:  # noqa: BLE001 - never expose internals
            status, body = 500, self._encode(_error("internal_error", "Internal server error."))
        self._send(status, body)

    def _method_not_allowed(self) -> None:
        self._host_ok = self._host_is_local()
        if not self._host_ok:  # Host safety comes before method dispatch
            self._refuse_host()
            return
        self._send(405, self._encode(_error("method_not_allowed", "Only GET is supported.")),
                   extra={"Allow": ALLOWED_METHODS})

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _method_not_allowed

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """JSON instead of http.server's HTML error pages."""
        if code == 501:  # a method with no do_* handler
            self._method_not_allowed()
            return
        self.close_connection = True
        self._send(code, self._encode(_error("bad_request", "The request could not be parsed.")))

    @staticmethod
    def _encode(payload: dict) -> bytes:
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _send(self, status: int, body: bytes, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        allow_origin = getattr(self.server, "allow_origin", None)
        headers = getattr(self, "headers", None)  # absent if the request line itself was rejected
        if (self._host_ok and allow_origin is not None and headers is not None
                and headers.get("Origin") == allow_origin):
            self.send_header("Access-Control-Allow-Origin", allow_origin)
            self.send_header("Vary", "Origin")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        if getattr(self, "command", None) != "HEAD":  # a HEAD response never carries a body
            self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - http.server's signature
        """No access log: request paths are not echoed to the console."""


def create_server(port: int, *, audits_dir: str | Path | None = None,
                  allow_origin: str | None = None) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1:port (0 lets the OS choose), serving the
    read-only resources for audits_dir (default: the project's audits)."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError(f"port must be 0-65535, got {port!r}")
    if allow_origin is not None:
        allow_origin = validate_origin(allow_origin)
    server = ThreadingHTTPServer((BIND_HOST, port), ReadonlyApiHandler)
    server.daemon_threads = True
    server.audits_dir = audits_dir
    server.allow_origin = allow_origin
    return server


def validate_origin(value: str) -> str:
    """One exact browser origin: scheme://host[:port], never '*'."""
    parts = urlsplit(value)
    if (value == "*" or parts.scheme not in ("http", "https") or not parts.netloc
            or parts.path or parts.query or parts.fragment or "@" in parts.netloc
            or value != f"{parts.scheme}://{parts.netloc}"):
        raise ValueError(f"--allow-origin must be one exact origin such as http://localhost:3000, got {value!r}")
    return value


def _port(value: str) -> int:
    if not _DIGITS.fullmatch(value) or not 1 <= int(value) <= 65535:
        raise argparse.ArgumentTypeError(f"must be a whole number from 1 to 65535, got {value!r}")
    return int(value)


def _origin(value: str) -> str:
    try:
        return validate_origin(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Serve the SignalScope read-only API on http://{BIND_HOST} (GET only, local use)."
    )
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT, help=f"Port on {BIND_HOST} (default: {DEFAULT_PORT})")
    parser.add_argument("--allow-origin", type=_origin, default=None,
                        help="One exact browser origin allowed by CORS, e.g. http://localhost:3000")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    server = create_server(args.port, allow_origin=args.allow_origin)
    print(f"SignalScope read-only API on http://{BIND_HOST}:{server.server_address[1]} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
