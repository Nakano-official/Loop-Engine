"""Conformance on the second platform: the coin room (browser-3d). The
reference implementation in tests/coinroom is green on every example, and the
stubs fail every observed result by comparison, never by a crash -- the same
two promises test_conformance makes for the idle game, on a design with
records nested three deep (Scene) and float math (sin, cos).

Needs vitest (LOOP_VITEST); skipped without it. Run on its own: two
conformance files in one pytest share vitest's cache and collide.
"""
import json
import os
from pathlib import Path

import pytest

import test_conformance as tc

pytestmark = pytest.mark.skipif(not tc.VITEST, reason="LOOP_VITEST is not set")

HERE = Path(__file__).resolve().parent
DESIGN = tc.emit.Design(HERE.parents[2] / "docs" / "formats" / "examples" / "coinroom.design.json")
CORRECT = {p.stem: p.read_text(encoding="utf-8") for p in (HERE / "coinroom").glob("*.ts")}


@pytest.fixture(autouse=True)
def coinroom(monkeypatch):
    monkeypatch.setattr(tc, "DESIGN", DESIGN)


def examples():
    return [ex for m in DESIGN.order() for ex in DESIGN.examples(m)]


def test_the_coin_room_is_green_everywhere(tmp_path):
    v = tc.run(tmp_path, CORRECT)
    assert set(v) == {ex["id"] for ex in examples()}
    assert all(r is not None for r in v.values()), "every example compared; none crashed"
    assert [i for i, r in v.items() if not r["ok"]] == []


def test_coin_room_stubs_fail_by_comparison_and_never_by_crash(tmp_path):
    v = tc.run(tmp_path, {})
    for ex in examples():
        assert v[ex["id"]] is not None, f"{ex['id']} crashed against the stub"
        assert v[ex["id"]]["ok"] is (not DESIGN.observes_a_result(ex)), ex["id"]


def test_a_sign_error_in_walk_fails_the_examples_that_move(tmp_path):
    broken = CORRECT["motion"].replace("const dx = (-s * f + c * r)", "const dx = (s * f + c * r)")
    assert broken != CORRECT["motion"]
    v = tc.run(tmp_path, {**CORRECT, "motion": broken}, only="motion")
    # Only walking forward or back while turned changes x: M1.E11 (yaw pi/2, w).
    assert {i for i, r in v.items() if not r["ok"]} == {"M1.E11"}


# ---- a part of a value, and a condition (FORMATS 4) --------------------------

def judged(tmp_path, change):
    """The coin room with some of its definition's examples judged otherwise."""
    src = HERE.parents[2] / "docs" / "formats" / "examples"
    d = json.loads((src / "coinroom.definition.json").read_text(encoding="utf-8"))
    by_id = {ex["id"]: ex for item in d["items"] for ex in item["examples"]}
    for eid, then in change.items():
        by_id[eid]["then"] = then
    out = tmp_path / "design"
    out.mkdir()
    (out / "coinroom.definition.json").write_text(json.dumps(d), encoding="utf-8")
    (out / "coinroom.design.json").write_text((src / "coinroom.design.json").read_text(encoding="utf-8"),
                                              encoding="utf-8")
    return tc.emit.Design(out / "coinroom.design.json")


RIGHT = {
    "D3.E1": {"observe": ["a"], "matches": [{"player": {"x": 0.0, "z": 7.0}}]},
    "D6.E1": {"observe": ["v"], "matches": [{"title": "コイン集め"}]},
    "D3.E2": {"observe": ["a"], "holds": "(a) => a.player.x === 0.5 && a.player.z === 8"},
}
WRONG = {
    "D3.E1": {"observe": ["a"], "matches": [{"player": {"z": 7.5}}]},
    "D3.E2": {"observe": ["a"], "holds": "(a) => a.nothing.x === 1"},          # throws
    "D3.E3": {"observe": ["b"], "holds": "(b) => 1"},                          # truthy, not true
}


def test_parts_and_conditions_judge_a_right_app_right(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "DESIGN", judged(tmp_path, RIGHT))
    v = tc.run(tmp_path / "ws", CORRECT)
    assert all(r is not None for r in v.values())
    assert [i for i, r in v.items() if not r["ok"]] == []
    assert v["D3.E2"]["expected"] == {"holds": RIGHT["D3.E2"]["holds"]}


def test_parts_and_conditions_refuse_what_they_say_is_wrong_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "DESIGN", judged(tmp_path, WRONG))
    v = tc.run(tmp_path / "ws", CORRECT)
    assert all(r is not None for r in v.values()), "a condition that throws is recorded, not a crash"
    assert {i for i, r in v.items() if not r["ok"]} == set(WRONG)
    assert "error" in v["D3.E2"] and "error" not in v["D3.E3"]


def test_against_stubs_a_part_is_red_and_a_condition_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "DESIGN", judged(tmp_path, RIGHT))
    v = tc.run(tmp_path / "ws", {})
    assert v["D3.E1"]["ok"] is False and v["D6.E1"]["ok"] is False
    assert v["D3.E2"] is not None
