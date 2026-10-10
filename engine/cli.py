"""The command line for the apps on this machine.

    python engine/cli.py list
    python engine/cli.py new <name> --title T --definition D.json --design S.json
    python engine/cli.py run <name> [--attempts N]       one run, in the foreground
    python engine/cli.py stop <name> <run>               ask a running run to stop

A run is the pipeline (pipeline.py) against the box, with the solver role, for
one app: its ledger, outcome and output land in apps/<name>/runs/<run>/. The
dashboard starts runs through this same entry, so a run started from a
terminal and one started from the dashboard are the same thing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import apps  # noqa: E402
import pipeline  # noqa: E402


def cmd_list(store: apps.Store, _args) -> int:
    for app in store.apps():
        s = app.summary()
        latest = s["latest"]
        state = f"{latest['id']} {latest['status']}" if latest else "no runs"
        print(f"{s['name']:20} {s['title']:20} {s['runs']:3} runs   latest: {state}")
    return 0


def cmd_new(store: apps.Store, args) -> int:
    app = store.create(args.name, args.title, Path(args.definition), Path(args.design))
    print(f"created {app.dir}")
    return 0


def cmd_run(store: apps.Store, args) -> int:
    app = store.app(args.name)
    try:
        store.acquire(app.name, os.getpid())     # one run at a time, across all apps
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        return _run(store, app, args)
    finally:
        store.release(os.getpid())


def _run(store: apps.Store, app: "apps.App", args) -> int:
    run = app.new_run()
    (run.dir / "run.pid").write_text(str(os.getpid()))
    ledger = pipeline.Ledger(run.dir / "ledger.jsonl")
    # A stop is a file, not a signal: on Windows a signal to another process is
    # TerminateProcess, and a run killed that way writes no outcome. The
    # pipeline looks for the file between modules and between attempts, and
    # ends cleanly at the next one.
    stop_file = run.dir / "stop"
    try:
        out = pipeline.run(app.design_path, "box", pipeline.RemoteWindow(), run.workspace,
                           max_attempts=args.attempts, ledger=ledger, output=run.dir / "app.html",
                           should_stop=stop_file.exists)
        outcome = {"stage": out.stage, "reason": out.reason, "green": out.green, "detail": out.detail}
    except KeyboardInterrupt:
        ledger("STOPPED")
        outcome = {"stage": "stopped", "reason": "interrupted at the terminal", "green": []}
    except Exception as e:  # noqa: BLE001 -- the run must end with an outcome on disk
        ledger("CRASHED", error=str(e))
        outcome = {"stage": "crashed", "reason": str(e), "green": []}
    (run.dir / "outcome.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=1), encoding="utf-8")
    (run.dir / "run.pid").unlink(missing_ok=True)
    print(json.dumps({"app": app.name, "run": run.id, **outcome}, ensure_ascii=False))
    return 0 if outcome["stage"] == "done" else 1


def cmd_stop(store: apps.Store, args) -> int:
    run = store.app(args.name).run(args.run)
    if run.status() != "running":
        print("not running")
        return 1
    (run.dir / "stop").write_text("stop requested\n")
    print(f"asked {args.name}/{args.run} to stop at the next module or attempt")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="loop")
    p.add_argument("--apps", default=str(apps.ROOT), help="where the apps live")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    n = sub.add_parser("new")
    n.add_argument("name")
    n.add_argument("--title", required=True)
    n.add_argument("--definition", required=True)
    n.add_argument("--design", required=True)
    r = sub.add_parser("run")
    r.add_argument("name")
    r.add_argument("--attempts", type=int, default=3)
    s = sub.add_parser("stop")
    s.add_argument("name")
    s.add_argument("run")
    args = p.parse_args(argv)
    store = apps.Store(args.apps)
    return {"list": cmd_list, "new": cmd_new, "run": cmd_run, "stop": cmd_stop}[args.cmd](store, args)


if __name__ == "__main__":
    sys.exit(main())
