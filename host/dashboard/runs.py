"""Starting and stopping runs, and asking the box how it is. The dashboard's
only reach beyond its own files.

A run is started the same way as from a terminal -- engine/cli.py run <app> --
as a detached process, so closing the dashboard does not end it. The run
itself takes the one-at-a-time lock (engine/apps.py); refusing a second start
here is only so the button can say so at once. A stop is the file cli.py
looks for between modules and attempts. The box is asked over the runner key,
through loop-window, which answers status and nothing that changes anything.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"
sys.path.insert(0, str(ENGINE))
import apps  # noqa: E402


def start(store: apps.Store, name: str) -> dict:
    app = store.app(name)                      # KeyError for a name that is not an app
    held = store.running()
    if held:
        raise RuntimeError(f"a run is already going ({held.get('app')}); one at a time")
    log = app.dir / "last-run.log"
    argv = [sys.executable, "-I", str(ENGINE / "cli.py"), "--apps", str(store.root), "run", app.name]
    # A run outlives the dashboard: closing the dashboard must not end a run
    # half-way. On Windows that takes three things -- no console (DETACHED),
    # its own group (Ctrl+C does not reach it), and out of the dashboard's job:
    # a terminal that runs the dashboard in a kill-on-close job would otherwise
    # take the run down with it. The first run started from the dashboard died
    # exactly so (2026-10-10). Breaking away is refused by a job that forbids
    # it; then the run starts without, rather than not at all.
    flags = []
    if os.name == "nt":
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        flags = [base | 0x01000000, base]                    # | CREATE_BREAKAWAY_FROM_JOB
    with log.open("w", encoding="utf-8") as out:
        # shell=False, and the only value from the request is an app name the
        # store has already matched against an existing directory.
        for i, creationflags in enumerate(flags or [0]):
            try:
                proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        creationflags=creationflags, close_fds=True)
                break
            except OSError:
                if i == len(flags) - 1:
                    raise
    return {"pid": proc.pid, "app": app.name}


def stop(store: apps.Store, name: str, run_id: str) -> dict:
    run = store.app(name).run(run_id)
    if run.status() != "running":
        raise RuntimeError("that run is not running")
    (run.dir / "stop").write_text("stop requested from the dashboard\n", encoding="utf-8")
    return {"stopping": run_id}


class Box:
    """The box's status, asked at most every few seconds."""

    def __init__(self, host: str = "loop-runner", every: float = 10.0):
        self.host = host
        self.every = every
        self._at = 0.0
        self._last: dict = {}

    def status(self) -> dict:
        if time.time() - self._at < self.every:
            return self._last
        try:
            # -n and stdin=DEVNULL: ssh is given no input. (Not the cure for a
            # dashboard started inside an SSH session, where ssh hangs before it
            # reads its config whatever its flags -- see host/README.md.)
            proc = subprocess.run(["ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", self.host, "status"],
                                  capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
                                  # no console window for ssh (see engine/pipeline.py, NO_WINDOW)
                                  creationflags=0x08000000 if os.name == "nt" else 0)
            self._last = json.loads(proc.stdout) if proc.returncode == 0 else {
                "window": "down", "error": (proc.stderr.strip() or "no answer")[:200]}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            self._last = {"window": "down", "error": str(e)[:200]}
        self._at = time.time()
        return self._last
