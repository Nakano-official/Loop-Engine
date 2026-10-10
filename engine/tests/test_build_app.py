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
    assert "<\/script" not in html.split("<script>", 1)[1].rsplit("</script>", 1)[0].replace("<\/script", "")
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
