"""Conformance: the TypeScript adapter, on the idle game, gives the same
verdicts as the Python adapter -- same examples green, same examples red,
for the same reasons.

Needs vitest. LOOP_VITEST names the binary (in the box:
/srv/loop/node/node_modules/.bin/vitest); without it these tests are skipped,
not passed. tests/idlegame holds a correct implementation of every module in
TypeScript; it stands in for the solver. The verdict is read from the record.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import emit  # noqa: E402

VITEST = os.environ.get("LOOP_VITEST")
pytestmark = pytest.mark.skipif(not VITEST, reason="LOOP_VITEST is not set")

DESIGN = emit.Design(HERE.parents[2] / "docs" / "formats" / "examples" / "idlegame.design.json")
CORRECT = {p.stem: p.read_text(encoding="utf-8") for p in (HERE / "idlegame").glob("*.ts")}


def run(ws: Path, impls: dict, only: str | None = None) -> dict[str, dict]:
    emit.build_workspace(DESIGN, ws, impls)
    env = {**os.environ, "LOOP_EXAMPLES": str(ws / "examples.json"), "LOOP_RECORD_DIR": str(ws)}
    argv = emit.run_command(VITEST, ws, only)
    proc = subprocess.run(argv, cwd=ws, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", shell=sys.platform == "win32")
    records = ws / "records.jsonl"
    assert records.exists(), f"vitest wrote no record:\n{proc.stdout}\n{proc.stderr}"
    verdict: dict[str, dict] = {}
    for line in records.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["t"] == "start":
            verdict.setdefault(r["id"], None)
        else:
            verdict[r["id"]] = r
    return verdict


def all_examples():
    return [ex for m in DESIGN.order() for ex in DESIGN.examples(m)]


def test_correct_implementation_is_green_everywhere(tmp_path):
    v = run(tmp_path, CORRECT)
    assert set(v) == {ex["id"] for ex in all_examples()}
    assert all(r is not None for r in v.values()), "every example compared; none crashed"
    assert [i for i, r in v.items() if not r["ok"]] == []


def test_stubs_fail_every_result_by_comparison_and_never_by_crash(tmp_path):
    v = run(tmp_path, {})
    for ex in all_examples():
        r = v[ex["id"]]
        assert r is not None, f"{ex['id']} crashed against the stub"
        assert r["ok"] is (not DESIGN.observes_a_result(ex)), ex["id"]


def test_one_module_stubbed_is_red_only_where_it_is_observed(tmp_path):
    rules = DESIGN.by_name["rules"]
    v = run(tmp_path, {k: s for k, s in CORRECT.items() if k != "rules"}, only="rules")
    assert set(v) == {ex["id"] for ex in DESIGN.examples(rules)}
    assert {i for i, r in v.items() if not r["ok"]} == \
        {ex["id"] for ex in DESIGN.examples(rules) if DESIGN.observes_a_result(ex)}


def test_a_bug_fails_exactly_the_examples_it_changes(tmp_path):
    broken = CORRECT["economy"].replace("spec.base_cost * spec.cost_scale ** owned", "spec.base_cost")
    assert broken != CORRECT["economy"]
    v = run(tmp_path, {**CORRECT, "economy": broken}, only="economy")
    assert {i for i, r in v.items() if not r["ok"]} == {"M2.E1"}


def test_a_wrong_error_is_caught(tmp_path):
    broken = CORRECT["economy"].replace("throw new T.UnknownGenerator(name);", "throw new RangeError(name);")
    assert broken != CORRECT["economy"]
    v = run(tmp_path, {**CORRECT, "economy": broken}, only="economy")
    assert {i for i, r in v.items() if not r["ok"]} == {"M2.E5"}
    assert v["M2.E5"]["actual"] == {"raises": "RangeError"}


def test_mutating_the_input_is_impossible(tmp_path):
    # Inputs are deep-frozen and modules are strict: editing the state in place
    # throws at the edit, so the immutability example cannot pass by luck.
    broken = CORRECT["rules"].replace(
        "if (state.resource < cost) throw new T.NotEnough(name);",
        "if (state.resource < cost) throw new T.NotEnough(name);\n"
        "  (state as any).resource = state.resource - cost;")
    assert broken != CORRECT["rules"]
    v = run(tmp_path, {**CORRECT, "rules": broken}, only="rules")
    assert v["M4.E5"] is None or v["M4.E5"]["ok"] is False
