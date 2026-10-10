"""The flow, end to end, with a local window and stand-in solvers.

The idle game's design is run with its target switched to Python, so the
generated tests run here without the box. The solver is a function: the
reference implementation, or a deliberately bad one. Every branch of
pipeline.run is taken at least once.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import pipeline  # noqa: E402
import window as window_mod  # noqa: E402

EX = ROOT / "docs" / "formats" / "examples"
CORRECT = {p.stem: p.read_text(encoding="utf-8")
           for p in (ROOT / "adapters" / "python" / "tests" / "idlegame").glob("*.py")}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setitem(window_mod.TOOLS, "python", sys.executable)
    design = json.loads((EX / "idlegame.design.json").read_text(encoding="utf-8"))
    design["target"]["language"] = "python"
    src = tmp_path / "design"
    src.mkdir()
    (src / "idlegame.design.json").write_text(json.dumps(design), encoding="utf-8")
    (src / "idlegame.definition.json").write_text(
        (EX / "idlegame.definition.json").read_text(encoding="utf-8"), encoding="utf-8")
    win = window_mod.Window(tmp_path / "work", window_mod.local_runner)
    return src / "idlegame.design.json", win, tmp_path / "ledger.jsonl"


def reference(d, module, feedback):
    return {f"app/{module['name']}.py": CORRECT[module["name"]]}


def events(ledger):
    return [json.loads(l)["event"] for l in ledger.read_text(encoding="utf-8").splitlines()]


def test_the_reference_solver_takes_every_module_to_green(setup):
    path, win, ledger = setup
    out = pipeline.run(path, reference, win, "run1", ledger=pipeline.Ledger(ledger))
    assert out.stage == "done"
    assert out.green == ["catalog", "economy", "format", "rules", "save", "view", "game"]
    ev = events(ledger)
    assert ev[0] == "GATES_PASSED" and ev[-1] == "ALL_GREEN"
    assert ev.count("GREEN") == 7 and ev.count("RED_GATE") == 7


def test_a_failed_attempt_is_retried_with_what_failed(setup):
    path, win, ledger = setup
    seen = []

    def flaky(d, module, feedback):
        seen.append((module["name"], feedback))
        if module["name"] == "economy" and len([s for s in seen if s[0] == "economy"]) == 1:
            return {"app/economy.py": CORRECT["economy"].replace(
                "spec.base_cost * spec.cost_scale ** owned", "spec.base_cost")}
        return reference(d, module, feedback)

    out = pipeline.run(path, flaky, win, "run2", ledger=pipeline.Ledger(ledger))
    assert out.stage == "done"
    second = [f for name, f in seen if name == "economy"][1]
    assert any("M2.E1: expected [33.75], got [15.0]" in line for line in second)


def test_attempts_used_up_go_back_to_the_design_without_its_values(setup):
    path, win, ledger = setup

    def stuck(d, module, feedback):
        if module["name"] == "rules":
            return {"app/rules.py": CORRECT["rules"].replace("state.resource + 1.0", "state.resource + 2.0")}
        return reference(d, module, feedback)

    out = pipeline.run(path, stuck, win, "run3", max_attempts=2, ledger=pipeline.Ledger(ledger))
    assert out.stage == "モジュール設計" and "granularity" in out.reason
    assert out.green == ["catalog", "economy", "format"]
    assert out.detail["examples"] == ["M4.E1"]
    assert "2.0" not in json.dumps(out.detail)


def test_a_candidate_writing_outside_its_file_is_refused_and_retried(setup):
    path, win, ledger = setup
    calls = []

    def sneaky(d, module, feedback):
        calls.append(module["name"])
        files = reference(d, module, feedback)
        if module["name"] == "format" and calls.count("format") == 1:
            files["tests/test_format.py"] = "def test_nothing(): pass\n"
        return files

    out = pipeline.run(path, sneaky, win, "run4", ledger=pipeline.Ledger(ledger))
    assert out.stage == "done"
    assert calls.count("format") == 2


def test_a_design_that_fails_its_gate_never_reaches_the_box(setup):
    path, win, ledger = setup
    broken = json.loads(path.read_text(encoding="utf-8"))
    broken["shell"]["calls"] = "M6"
    path.write_text(json.dumps(broken), encoding="utf-8")
    out = pipeline.run(path, reference, win, "run5", ledger=pipeline.Ledger(ledger))
    assert out.stage == "モジュール設計"
    assert events(ledger) == ["GATE_FAILED"]
    assert not (win.root / "run5").exists()
