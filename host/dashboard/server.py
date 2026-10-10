"""The Loop Engine dashboard: every app on this machine, its runs, its output.

Listens on loopback only, always. Reaching it from a phone is done by putting
`tailscale serve` in front, which proxies from the tailnet to 127.0.0.1 -- so
nothing here is ever exposed to the LAN, and the machine keeps one door.

What it shows comes from engine/apps.py and nowhere else; it keeps no state
of its own. What it changes is three things: a run started (at this machine
only), a run asked to stop (from anywhere), and a decision appended (an
approval at this machine only -- apps.py refuses it otherwise).

The output apps are code a model wrote. They are served with
`Content-Security-Policy: sandbox allow-scripts`, which gives the document an
opaque origin wherever it is opened -- in the page's iframe or on its own --
so it can run, but it cannot read this dashboard, its session token, or
anything else of this origin.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from .access import LOCAL, Reach
    from . import runs as runs_mod
except ImportError:  # direct execution: python host/dashboard/server.py
    # Added explicitly: under `python -I` the script's own directory is not on
    # the path, and the dashboard is started that way as well.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from access import LOCAL, Reach
    import runs as runs_mod

apps = runs_mod.apps
STATIC = Path(__file__).with_name("static")
APP_CSP = "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'"


def handler_for(store: "apps.Store", reach: Reach, token: str, box: "runs_mod.Box"):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            print("dashboard: " + format % args)

        def _send(self, body: bytes, kind: str, status=HTTPStatus.OK, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, value, status=HTTPStatus.OK) -> None:
            self._send(json.dumps(value, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", status)

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
            do_OPTIONS to answer it. DNS rebinding defeats both; what a rebound
            request cannot change is the Host header. So the names this server
            answers to are a list, and everything else is 403 (access.py)."""
            return reach.of(self.headers)

        def do_GET(self) -> None:
            scope, user = self._caller()
            if scope is None:
                self._json({"error": "unexpected Host header"}, HTTPStatus.FORBIDDEN)
                return
            path = unquote(urlparse(self.path).path)
            try:
                if path == "/api/session":
                    # The page is told what it may do rather than finding out by
                    # being refused: a button that cannot work should not be there.
                    self._json({"token": token, "scope": scope, "user": user,
                                "can_start": scope == LOCAL, "can_approve": scope == LOCAL,
                                "platforms": apps.PLATFORMS})
                    return
                if path == "/api/apps":
                    self._json({"apps": [a.summary() for a in store.apps()],
                                "running": store.running()})
                    return
                if path == "/api/box":
                    self._json(box.status())
                    return
                m = re.fullmatch(r"/api/apps/([^/]+)", path)
                if m:
                    app = store.app(m.group(1))
                    self._json({"name": app.name, "title": app.meta().get("title", app.name),
                                "requirements": app.requirements(),
                                "runs": [r.summary() for r in app.runs()]})
                    return
                m = re.fullmatch(r"/api/apps/([^/]+)/runs/([^/]+)", path)
                if m:
                    run = store.app(m.group(1)).run(m.group(2))
                    self._json({**run.summary(), "ledger": run.ledger()[-200:], "outcome": run.outcome(),
                                "decisions": [d for d in run.app.decisions() if d.get("run") == run.id]})
                    return
                m = re.fullmatch(r"/play/([^/]+)/([^/]+)", path)
                if m:
                    out = store.app(m.group(1)).run(m.group(2)).output()
                    if out is None:
                        raise KeyError("no app in this run")
                    self._send(out.read_bytes(), "text/html; charset=utf-8",
                               extra={"Content-Security-Policy": APP_CSP})
                    return
            except KeyError:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            name = files.get(path)
            if name is None:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            kind = "text/html" if name.endswith(".html") else (
                "text/css" if name.endswith(".css") else "text/javascript")
            self._send((STATIC / name).read_bytes(), kind + "; charset=utf-8")

        def do_POST(self) -> None:
            scope, user = self._caller()
            if scope is None:
                self._json({"error": "unexpected Host header"}, HTTPStatus.FORBIDDEN)
                return
            if not secrets.compare_digest(self.headers.get("X-Loop-Token", ""), token):
                self._json({"error": "invalid session token"}, HTTPStatus.FORBIDDEN)
                return
            try:
                body = self._body()
                path = urlparse(self.path).path
                if path == "/api/apps":
                    # A new app from requirements. Local, like starting a run:
                    # its first run is what the person creating it will play.
                    if scope != LOCAL:
                        raise PermissionError("an app is created at this machine")
                    app = store.create_from_requirements(str(body.get("name", "")), str(body.get("title", "")),
                                                         str(body.get("requirements", "")),
                                                         platform=str(body.get("platform", "browser-dom")))
                    self._json({"name": app.name}, HTTPStatus.CREATED)
                    return
                if path == "/api/runs/start":
                    # Starting is a local act: it spends the machine, and the
                    # person who starts a run is the one who will play its app.
                    if scope != LOCAL:
                        raise PermissionError("a run is started at this machine")
                    self._json(runs_mod.start(store, str(body.get("app", ""))), HTTPStatus.ACCEPTED)
                    return
                if path == "/api/runs/stop":
                    # Stopping is "no", and "no" is cheap: it may come from anywhere.
                    self._json(runs_mod.stop(store, str(body.get("app", "")), str(body.get("run", ""))),
                               HTTPStatus.ACCEPTED)
                    return
                if path == "/api/decision":
                    app = store.app(str(body.get("app", "")))
                    entry = app.decide(str(body.get("run", "")), str(body.get("verdict", "")),
                                       str(body.get("note", "")), user=user or "local", scope=scope)
                    self._json(entry, HTTPStatus.CREATED)
                    return
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except KeyError:
                self._json({"error": "no such app or run"}, HTTPStatus.NOT_FOUND)
            except PermissionError as e:
                self._json({"error": str(e)}, HTTPStatus.FORBIDDEN)
            except FileExistsError:
                self._json({"error": "an app with that name already exists"}, HTTPStatus.CONFLICT)
            except (ValueError, RuntimeError, json.JSONDecodeError) as e:
                self._json({"error": str(e)}, HTTPStatus.CONFLICT if isinstance(e, RuntimeError)
                           else HTTPStatus.BAD_REQUEST)

    return Handler


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Loop Engine dashboard")
    parser.add_argument("--apps", type=Path, default=apps.ROOT, help="where the apps live")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--port", type=int, default=8443)
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 handler_for(apps.Store(args.apps), Reach(args.config), token, runs_mod.Box()))
    print(f"Loop dashboard: http://127.0.0.1:{args.port}  (apps: {args.apps})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
