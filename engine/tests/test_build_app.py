"""build-app: the idle game's green modules and the browser-dom shell, bundled
into one HTML file and booted once in happy-dom.

Needs rolldown, node and happy-dom: LOOP_ROLLDOWN and LOOP_HAPPY_DOM name them
(LOOP_NODE optionally); without them these tests are skipped, not passed. In
the box the frozen toolchain provides all three.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import window as window_mod  # noqa: E402

pytestmark = pytest.mark.skipif(not (os.environ.get("LOOP_ROLLDOWN") and os.environ.get("LOOP_HAPPY_DOM")),
                                reason="LOOP_ROLLDOWN / LOOP_HAPPY_DOM not set")

EX = ROOT / "docs" / "formats" / "examples"
CORRECT = {p.stem: p.read_text(encoding="utf-8")
           for p in (ROOT / "adapters" / "typescript" / "tests" / "idlegame").glob("*.ts")}


def workspace(tmp_path, impls):
    win = window_mod.Window(tmp_path / "work", window_mod.local_runner, tool=window_mod.local_tool)
    design = json.loads((EX / "idlegame.design.json").read_text(encoding="utf-8"))
    definition = json.loads((EX / "idlegame.definition.json").read_text(encoding="utf-8"))
    ws = win.root / "app1"
    (ws / ".loop" / "impl").mkdir(parents=True)
    (ws / ".loop" / "design.json").write_text(json.dumps(design), encoding="utf-8")
    (ws / ".loop" / design["definition"]).write_text(json.dumps(definition), encoding="utf-8")
    for name, text in impls.items():
        (ws / ".loop" / "impl" / f"{name}.ts").write_text(text, encoding="utf-8")
    return win


def test_the_idle_game_builds_into_one_file_that_boots(tmp_path):
    out = workspace(tmp_path, CORRECT).build_app("app1", "game")
    assert "error" not in out, out
    html = out["html"]
    assert html.count("<script>") == 1 and "__BUNDLE__" not in html
    assert r"<\/script" not in html.split("<script>", 1)[1].rsplit("</script>", 1)[0].replace(r"<\/script", "")
    boot = out["boot"]
    assert boot["ok"] is True, boot
    assert boot["title"] == "放置ゲーム"
    # heading, two texts, Click, and a text and a button per generator.
    assert boot["nodes"] == 8 and boot["buttons"] == 3
    # A new game has nothing to spend: only Click can be pressed.
    assert boot["pressed"] == 1


def test_an_app_whose_screen_throws_does_not_boot(tmp_path):
    broken = CORRECT["game"].replace("const v = view(state);", "throw new Error(\"no screen\");")
    assert broken != CORRECT["game"]
    out = workspace(tmp_path, {**CORRECT, "game": broken}).build_app("app1", "game")
    assert out["boot"]["ok"] is False
    assert any("no screen" in e for e in out["boot"]["errors"]), out["boot"]


# browser-3d: the coin room. The shell imports three, so the toolchain's
# node_modules must be reachable (LOOP_NODE_MODULES outside the box).
ROOM = {p.stem: p.read_text(encoding="utf-8")
        for p in (ROOT / "adapters" / "typescript" / "tests" / "coinroom").glob("*.ts")}


def room(tmp_path, impls):
    win = window_mod.Window(tmp_path / "work", window_mod.local_runner, tool=window_mod.local_tool)
    design = json.loads((EX / "coinroom.design.json").read_text(encoding="utf-8"))
    definition = json.loads((EX / "coinroom.definition.json").read_text(encoding="utf-8"))
    ws = win.root / "room"
    (ws / ".loop" / "impl").mkdir(parents=True)
    (ws / ".loop" / "design.json").write_text(json.dumps(design), encoding="utf-8")
    (ws / ".loop" / design["definition"]).write_text(json.dumps(definition), encoding="utf-8")
    for name, text in impls.items():
        (ws / ".loop" / "impl" / f"{name}.ts").write_text(text, encoding="utf-8")
    return win


def test_the_coin_room_builds_into_one_file_that_runs_its_frames(tmp_path):
    out = room(tmp_path, ROOM).build_app("room", "game")
    assert "error" not in out, out
    assert out["html"].count("<script>") == 1
    boot = out["boot"]
    assert boot["ok"] is True, boot
    assert boot["title"] == "コイン集め" and boot["frames"] == 300 and boot["moved"] is True
    # Holding w for 2.5 s from z 8 walks 10 m north, over the coin at the
    # centre: floor, four walls and four coins left.
    assert boot["objects"] == 9 and boot["hud"] == 3


def test_a_room_whose_step_throws_does_not_boot(tmp_path):
    broken = ROOM["game"].replace("const dt =", "throw new Error(\"no step\"); const dt =")
    assert broken != ROOM["game"]
    boot = room(tmp_path, {**ROOM, "game": broken}).build_app("room", "game")["boot"]
    # The shell keeps the state and keeps drawing, and says so once.
    assert boot["ok"] is False and boot["moved"] is False and boot["frames"] == 300
    assert boot["errors"] == ["step: no step"], boot
