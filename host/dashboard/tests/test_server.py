"""The dashboard over HTTP: who may do what, and what an output app can reach."""
import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import server  # noqa: E402
from access import Reach  # noqa: E402

apps = server.apps
EX = HERE.parents[2] / "docs" / "formats" / "examples"
PUBLISHED = "board.example.ts.net"
ALLOWED = "you@example.com"


class FakeBox:
    def status(self):
        return {"window": "ok", "llm": "active", "egress": "active"}


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = apps.Store(self.tmp / "apps")
        app = self.store.create("idle", "放置ゲーム", EX / "idlegame.definition.json", EX / "idlegame.design.json")
        run = app.new_run()
        (run.dir / "outcome.json").write_text(json.dumps({"stage": "done"}), encoding="utf-8")
        (run.dir / "app.html").write_text("<script>fetch('/api/session')</script>", encoding="utf-8")
        self.run_id = run.id
        config = self.tmp / "config.json"
        config.write_text(json.dumps({"remote": {"host": PUBLISHED + ":8443", "users": [ALLOWED]}}),
                          encoding="utf-8")
        self.token = "t0ken"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         server.handler_for(self.store, Reach(config), self.token, FakeBox()))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, method, path, host="127.0.0.1", body=None, token=True, user=None):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        headers = {"Host": host, "Content-Type": "application/json"}
        if token:
            headers["X-Loop-Token"] = self.token
        if user:
            headers["Tailscale-User-Login"] = user
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def remote(self, method, path, body=None):
        return self.request(method, path, host=PUBLISHED, body=body, user=ALLOWED)

    # ---- who is asking ----------------------------------------------------------

    def test_an_unknown_host_is_refused(self):
        for path in ["/", "/api/apps", f"/play/idle/{self.run_id}"]:
            self.assertEqual(self.request("GET", path, host="evil.example")[0], 403)

    def test_a_published_name_without_a_listed_user_is_refused(self):
        self.assertEqual(self.request("GET", "/api/apps", host=PUBLISHED, user="stranger@x")[0], 403)

    def test_the_session_says_what_this_caller_may_do(self):
        local = json.loads(self.request("GET", "/api/session")[2])
        remote = json.loads(self.remote("GET", "/api/session")[2])
        self.assertTrue(local["can_start"] and local["can_approve"])
        self.assertFalse(remote["can_start"] or remote["can_approve"])

    def test_a_change_without_the_token_is_refused(self):
        s, _, _ = self.request("POST", "/api/decision", body={"app": "idle", "run": self.run_id,
                                                              "verdict": "reject"}, token=False)
        self.assertEqual(s, 403)

    # ---- what each may do --------------------------------------------------------

    def test_a_remote_approval_is_refused_and_a_remote_rejection_is_kept(self):
        s, _, _ = self.remote("POST", "/api/decision", {"app": "idle", "run": self.run_id, "verdict": "approve"})
        self.assertEqual(s, 403)
        s, _, body = self.remote("POST", "/api/decision",
                                 {"app": "idle", "run": self.run_id, "verdict": "reject", "note": "no"})
        self.assertEqual(s, 201)
        self.assertEqual(json.loads(body)["scope"], "remote")

    def test_a_local_approval_is_recorded(self):
        s, _, _ = self.request("POST", "/api/decision", body={"app": "idle", "run": self.run_id, "verdict": "approve"})
        self.assertEqual(s, 201)
        self.assertEqual(self.store.app("idle").decision(self.run_id)["verdict"], "approve")

    def test_a_run_cannot_be_started_from_afar(self):
        self.assertEqual(self.remote("POST", "/api/runs/start", {"app": "idle"})[0], 403)

    def test_a_second_run_waits_for_the_first(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.store.acquire("idle", p.pid)
            self.assertEqual(self.request("POST", "/api/runs/start", body={"app": "idle"})[0], 409)
        finally:
            p.kill()
            p.wait()

    # ---- what an output app can reach --------------------------------------------

    def test_an_output_app_is_served_in_a_sandbox(self):
        s, headers, body = self.request("GET", f"/play/idle/{self.run_id}")
        self.assertEqual(s, 200)
        csp = headers.get("Content-Security-Policy", "")
        # An opaque origin: the app's fetch('/api/session') is not same-origin
        # and cannot read the token; default-src 'none' stops it reaching out.
        self.assertIn("sandbox allow-scripts", csp)
        self.assertNotIn("allow-same-origin", csp)
        self.assertIn("default-src 'none'", csp)

    def test_paths_that_are_not_an_app_and_run_are_not_found(self):
        for path in ["/play/idle/..%2f..%2fdesign.json", "/play/..%2fidle/x", "/api/apps/..",
                     "/play/idle/r0", "/api/apps/idle/runs/..%2f..%2fapp.json"]:
            self.assertEqual(self.request("GET", path)[0], 404, path)

    def test_the_app_list_reads_the_store(self):
        data = json.loads(self.request("GET", "/api/apps")[2])
        self.assertEqual([a["name"] for a in data["apps"]], ["idle"])
        self.assertEqual(data["apps"][0]["latest"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
