"""Conformance on the second platform: the coin room (browser-3d). The
reference implementation in tests/coinroom is green on every example, and the
stubs fail every observed result by comparison, never by a crash -- the same
two promises test_conformance makes for the idle game, on a design with
records nested three deep (Scene) and float math (sin, cos).

Needs vitest (LOOP_VITEST); skipped without it. Run on its own: two
conformance files in one pytest share vitest's cache and collide.
"""
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
