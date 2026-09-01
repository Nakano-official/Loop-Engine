"""HTTP server for the Loop Engine operator dashboard.

Listens on loopback only, always. Reaching it from a phone is done by putting
`tailscale serve` in front, which proxies from the tailnet to 127.0.0.1 -- so
nothing here is ever exposed to the LAN, and the machine keeps one door.
"""

from __future__ import annotations

import argparse
import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from .access import LOCAL, Reach
    from .actions import Launchers
    from .state import DashboardState
except ImportError:  # direct execution: python host/dashboard/server.py
    from access import LOCAL, Reach
    from actions import Launchers
    from state import DashboardState


STATIC = Path(__file__).with_name("static")


def handler_for(state: DashboardState, launchers: Launchers, reach: Reach, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            print("dashboard: " + format % args)

        def _json(self, value, status=HTTPStatus.OK) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                raise ValueError("request is too large")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def _caller(self):
            """(scope, user), or (None, "") for a request that is refused.

            Binding 127.0.0.1 and requiring a custom header keep an ordinary
            web page out: the header forces a CORS preflight, and there is no
            do_OPTIONS to answer it.  DNS rebinding defeats both -- the
            attacker's name is made to resolve to 127.0.0.1, the page and this
            server become same-origin, and the browser stops objecting.  What
            the rebound request cannot change is the Host header, which still
            carries the attacker's name.  So the names this server answers to
            are a list, and everything else is 403.
            """
            return reach.of(self.headers)

        def _authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-Loop-Token", ""), token)

        def do_GET(self) -> None:
            scope, user = self._caller()
            if scope is None:
                self._json({"error": "unexpected Host header"}, HTTPStatus.FORBIDDEN)
                return
            path = urlparse(self.path).path
            if path == "/api/session":
                # The page is told what it may do rather than finding out by
                # being refused: a button that cannot work should not be there.
                self._json({"token": token, "scope": scope, "user": user,
                            "launchers": launchers.public() if scope == LOCAL else []})
                return
            if path == "/api/state":
                self._json(state.snapshot())
                return
            files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            name = files.get(path)
            if name is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = (STATIC / name).read_bytes()
            kind = "text/html" if name.endswith(".html") else (
                "text/css" if name.endswith(".css") else "text/javascript")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            scope, user = self._caller()
            if scope is None:
                self._json({"error": "unexpected Host header"}, HTTPStatus.FORBIDDEN)
                return
            if not self._authorized():
                self._json({"error": "invalid session token"}, HTTPStatus.FORBIDDEN)
                return
            try:
                body = self._body()
                path = urlparse(self.path).path
                if path == "/api/decision":
                    result = state.decide(
                        str(body.get("kind", "")), str(body.get("request_id", "")),
                        str(body.get("decision", "")), str(body.get("note", "")),
                        scope=scope, user=user,
                    )
                    self._json(result, HTTPStatus.CREATED)
                    return
                if path == "/api/launch":
                    # Starting a program is the one thing that only makes sense
                    # where the screen is. A phone would start a window nobody
                    # is looking at.
                    if scope != LOCAL:
                        raise ValueError(
                            "artifacts can only be started at the machine itself")
                    pid = launchers.launch(str(body.get("launcher_id", "")))
                    self._json({"pid": pid}, HTTPStatus.ACCEPTED)
                    return
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except (ValueError, json.JSONDecodeError) as error:
                self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Loop Engine operator dashboard")
    parser.add_argument("--project", type=Path, required=True,
                        help="host-side project mirror containing plan/ledger.jsonl")
    parser.add_argument("--data", type=Path, default=Path(__file__).with_name(".state"))
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--port", type=int, default=8443)
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        handler_for(DashboardState(args.project, args.data), Launchers(args.config),
                    Reach(args.config), token),
    )
    print(f"Loop dashboard: http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
