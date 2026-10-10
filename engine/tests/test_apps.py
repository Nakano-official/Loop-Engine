"""The apps on the host: their files, their runs' status read from those files,
decisions, and stopping a run."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import apps  # noqa: E402

EX = ROOT / "docs" / "formats" / "examples"


@pytest.fixture
def store(tmp_path):
    s = apps.Store(tmp_path / "apps")
    s.create("idle", "放置ゲーム", EX / "idlegame.definition.json", EX / "idlegame.design.json")
    return s


def write_run(app, events, outcome=None, html=False):
    run = app.new_run()
    with (run.dir / "ledger.jsonl").open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    if outcome:
        (run.dir / "outcome.json").write_text(json.dumps(outcome), encoding="utf-8")
    if html:
        (run.dir / "app.html").write_text("<html></html>", encoding="utf-8")
    return run


def test_a_new_app_points_its_design_at_its_definition(store):
    app = store.app("idle")
    assert json.loads(app.design_path.read_text(encoding="utf-8"))["definition"] == "definition.json"
    assert (app.dir / "definition.json").exists()
    assert app.meta()["title"] == "放置ゲーム"
    assert [a.name for a in store.apps()] == ["idle"]


def test_names_that_could_be_paths_are_refused(store, tmp_path):
    for bad in ["../x", "Idle", "a b", ""]:
        with pytest.raises((ValueError, KeyError)):
            store.create(bad, "t", EX / "idlegame.definition.json", EX / "idlegame.design.json")
        with pytest.raises(KeyError):
            store.app(bad)


def test_status_is_read_from_the_files(store):
    app = store.app("idle")
    done = write_run(app, [{"event": "GREEN", "module": "catalog"}], {"stage": "done"}, html=True)
    failed = write_run(app, [{"event": "EXHAUSTED", "module": "format", "reason": "granularity"}],
                       {"stage": "モジュール設計"})
    dead = write_run(app, [{"event": "RED_GATE", "module": "catalog", "stage": "red"}])
    assert done.status() == "done" and done.output()
    assert failed.status() == "failed"
    assert dead.status() == "interrupted"  # no outcome and no process: it died
    assert failed.modules() == [{"module": "format", "attempts": 0, "state": "exhausted",
                                 "reason": "granularity"}]


def test_asking_whether_a_run_is_alive_does_not_end_it():
    # On Windows os.kill(pid, 0) is TerminateProcess. The check must not be.
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert apps._alive(p.pid) is True
        assert apps._alive(p.pid) is True
        assert p.poll() is None, "the liveness check killed the process"
    finally:
        p.kill()
        p.wait()
    assert apps._alive(p.pid) is False


def test_approval_only_from_this_machine_and_only_with_an_app(store):
    app = store.app("idle")
    with_app = write_run(app, [], {"stage": "done"}, html=True)
    without = write_run(app, [], {"stage": "モジュール設計"})
    with pytest.raises(PermissionError):
        app.decide(with_app.id, "approve", "", "someone", "remote")
    with pytest.raises(ValueError):
        app.decide(without.id, "approve", "", "me", "local")
    app.decide(with_app.id, "reject", "buttons overlap", "someone", "remote")
    app.decide(with_app.id, "approve", "plays fine", "me", "local")
    assert app.decision(with_app.id)["verdict"] == "approve"
    assert len(app.decisions()) == 2       # append-only: the rejection is still there


def test_a_stop_request_ends_the_pipeline_cleanly(store, monkeypatch, tmp_path):
    import pipeline
    import window as window_mod
    monkeypatch.setitem(window_mod.TOOLS, "python", sys.executable)
    real = pipeline.artifacts.platform
    monkeypatch.setattr(pipeline.artifacts, "platform",
                        lambda name: {**real(name), "language": "python"} if real(name) else None)
    app = store.app("idle")
    ds = json.loads(app.design_path.read_text(encoding="utf-8"))
    ds["target"]["language"] = "python"
    app.design_path.write_text(json.dumps(ds), encoding="utf-8")
    correct = {p.stem: p.read_text(encoding="utf-8")
               for p in (ROOT / "adapters" / "python" / "tests" / "idlegame").glob("*.py")}
    calls = []

    def solver(d, module, feedback):
        calls.append(module["name"])
        return {f"app/{module['name']}.py": correct[module["name"]]}

    win = window_mod.Window(tmp_path / "work", window_mod.local_runner)
    out = pipeline.run(app.design_path, solver, win, "stoptest", build=False,
                       should_stop=lambda: len(calls) >= 2)
    assert out.stage == "stopped" and out.green == ["catalog", "economy"]


def test_runs_started_in_the_same_second_do_not_collide(store):
    app = store.app("idle")
    ids = [app.new_run().id for _ in range(3)]
    assert len(set(ids)) == 3


def test_only_one_run_at_a_time_across_all_apps(store):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        store.acquire("idle", p.pid)
        with pytest.raises(RuntimeError):
            store.acquire("other", 12345)
        assert store.running()["app"] == "idle"
    finally:
        p.kill()
        p.wait()
    # The holder is gone: the lock is stale and the next run may start.
    assert store.running() is None
    store.acquire("other", subprocess.os.getpid())
    store.release(subprocess.os.getpid())
    assert store.running() is None


def test_the_newest_run_is_first_whatever_its_name(store):
    app = store.app("idle")
    old = app.dir / "runs" / "real-5"
    old.mkdir(parents=True)
    (old / "ledger.jsonl").write_text(json.dumps({"t": 1.0, "event": "GATES_PASSED"}) + "\n", encoding="utf-8")
    new = app.new_run()
    assert [r.id for r in app.runs()][0] == new.id
