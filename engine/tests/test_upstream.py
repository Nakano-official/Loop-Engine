"""From requirements: the definer and the designer in front of the modules.

The roles are stand-ins that write the idle game's definition and design into
their out/, the way a Claude role would through run-role; the solver is the
reference implementation. Python is the target here (as in test_pipeline), so
the platform's language rule is read as Python and no output is built.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import pipeline  # noqa: E402
import window as window_mod  # noqa: E402

EX = ROOT / "docs" / "formats" / "examples"
DEFINITION = (EX / "idlegame.definition.json").read_text(encoding="utf-8")
DESIGN = json.loads((EX / "idlegame.design.json").read_text(encoding="utf-8"))
DESIGN["target"]["language"] = "python"
CORRECT = {p.stem: p.read_text(encoding="utf-8")
           for p in (ROOT / "adapters" / "python" / "tests" / "idlegame").glob("*.py")}


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setitem(window_mod.TOOLS, "python", sys.executable)
    real = pipeline.artifacts.platform
    monkeypatch.setattr(pipeline.artifacts, "platform",
                        lambda name: {**real(name), "language": "python"} if real(name) else None)
    roles = tmp_path / "roles"
    for role in ("definer", "designer"):
        (roles / role / "in").mkdir(parents=True)
        (roles / role / "out").mkdir(parents=True)
    w = window_mod.Window(tmp_path / "work", window_mod.local_runner, roles=roles)
    w.briefs = {"definer": [], "designer": []}
    return w


def roles(win, definitions, designs):
    """Stand-ins: each call writes the next of the given files."""
    queue = {"definer": list(definitions), "designer": list(designs)}

    def run_role(role, brief):
        win.briefs[role].append(Path(brief).read_text(encoding="utf-8"))
        name = "definition.json" if role == "definer" else "design.json"
        text = queue[role].pop(0) if len(queue[role]) > 1 else queue[role][0]
        (win.roles / role / "out" / name).write_text(text, encoding="utf-8")
        return 0, f"[{role}] wrote {name}"

    win.run_role_fn = run_role


def reference(d, module, feedback):
    return {f"app/{module['name']}.py": CORRECT[module["name"]]}


def test_requirements_to_green_through_both_gates(win, tmp_path):
    broken = json.loads(DEFINITION)
    del broken["types"]["Screen"]                       # the platform's type, missing
    roles(win, [json.dumps(broken), DEFINITION], [json.dumps(DESIGN)])
    ledger = tmp_path / "ledger.jsonl"
    out = pipeline.run_from_requirements("放置ゲームを作る", tmp_path / "app", win, "up1", solver=reference,
                                         ledger=pipeline.Ledger(ledger), build=False)
    assert out.stage == "done", (out.stage, out.reason)
    assert out.green[-1] == "game"
    # The definer was refused once, and told why.
    assert len(win.briefs["definer"]) == 2
    assert "types.Screen" in win.briefs["definer"][1]
    events = [json.loads(l)["event"] for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert events[:4] == ["DEFINER", "DEFINER", "DESIGNER", "DESIGN_ROUND"]
    assert json.loads((tmp_path / "app" / "design.json").read_text(encoding="utf-8"))["definition"] == "definition.json"


def test_a_definition_that_never_passes_stops_at_the_definition(win, tmp_path):
    roles(win, ["not json"], [json.dumps(DESIGN)])
    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up2", solver=reference, gate_rounds=2,
                                         build=False)
    assert out.stage == "要件定義"
    assert len(win.briefs["definer"]) == 2 and win.briefs["designer"] == []


def test_used_up_attempts_send_the_designer_ids_and_reasons_only(win, tmp_path):
    roles(win, [DEFINITION], [json.dumps(DESIGN)])

    def stuck(d, module, feedback):
        if module["name"] == "format":
            return {"app/format.py": CORRECT["format"].replace(":.2f", ":.3f")}
        return reference(d, module, feedback)

    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up3", solver=stuck,
                                         max_attempts=1, redesigns=1, build=False)
    assert out.stage == "モジュール設計"
    assert len(win.briefs["designer"]) == 2
    second = win.briefs["designer"][1]
    assert "Module `format` could not be implemented" in second
    assert "granularity" in second and "M3.E1" in second
    # What the implementation returned never reaches the designer.
    assert "2.500K" not in second
