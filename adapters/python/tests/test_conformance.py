"""Conformance: the Python adapter, on the idle game, fails where REDESIGN 4
says it must and nowhere else.

The design is docs/formats/examples. tests/idlegame holds a correct
implementation of every module; it stands in for the solver. Each case builds a
workspace with emit.build_workspace, runs the generated tests the way exec
would (pytest, LOOP_EXAMPLES, LOOP_RECORD_DIR), and reads the verdict from the
RECORD -- never from pytest's report.
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

DESIGN = emit.Design(HERE.parents[2] / "docs" / "formats" / "examples" / "idlegame.design.json")
CORRECT = {p.stem: p.read_text(encoding="utf-8") for p in (HERE / "idlegame").glob("*.py")}


def run(ws: Path, impls: dict, only: str | None = None) -> dict[str, dict]:
    """Build, run, and return {example id: its CHECK record, or None if it
    started and never compared}."""
    emit.build_workspace(DESIGN, ws, impls)
    env = {**os.environ, "LOOP_EXAMPLES": str(ws / "examples.json"), "LOOP_RECORD_DIR": str(ws)}
    target = f"tests/test_{only}.py" if only else "tests"
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
                   cwd=ws, env=env, capture_output=True, text=True)
    verdict: dict[str, dict] = {}
    for line in (ws / "records.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["t"] == "start":
            verdict.setdefault(r["id"], None)
        else:
            verdict[r["id"]] = r
    return verdict


def all_examples(module=None):
    mods = [module] if module else DESIGN.order()
    return [ex for m in mods for ex in DESIGN.examples(m)]


def test_correct_implementation_is_green_everywhere(tmp_path):
    v = run(tmp_path, CORRECT)
    ids = {ex["id"] for ex in all_examples()}
    assert set(v) == ids, "every example started"
    assert all(r is not None for r in v.values()), "every example compared; none crashed"
    assert [i for i, r in v.items() if not r["ok"]] == []


def test_stubs_fail_every_result_by_comparison_and_never_by_crash(tmp_path):
    v = run(tmp_path, {})
    for ex in all_examples():
        r = v[ex["id"]]
        # A stub has the contract's shape: calling it never breaks. If it did,
        # the red gate would blame the engine (REDESIGN 4), so it must not.
        assert r is not None, f"{ex['id']} crashed against the stub"
        if DESIGN.observes_a_result(ex):
            assert r["ok"] is False, f"{ex['id']} passed against a stub"
        else:
            assert r["ok"] is True, f"{ex['id']} observes an input; a stub leaves it alone"


def test_input_observing_examples_exist_in_the_design():
    # Otherwise the previous test's exemption would be untested. Only M4.E5
    # observes a value it put there itself. D2.E2 reads like the same kind of
    # example ("the old state is unchanged") but the state it observes was
    # RETURNED by new_game -- so against a stub it must fail, and does.
    assert [ex["id"] for ex in all_examples() if not DESIGN.observes_a_result(ex)] == ["M4.E5"]


def test_one_module_stubbed_is_red_only_where_it_is_observed(tmp_path):
    rules = DESIGN.by_name["rules"]
    v = run(tmp_path, {k: s for k, s in CORRECT.items() if k != "rules"}, only="rules")
    failed = {i for i, r in v.items() if not r["ok"]}
    assert set(v) == {ex["id"] for ex in DESIGN.examples(rules)}
    assert failed == {ex["id"] for ex in DESIGN.examples(rules) if DESIGN.observes_a_result(ex)}


def test_a_bug_fails_exactly_the_examples_it_changes(tmp_path):
    # current_cost ignores how many are owned. At owned=0 that is still right,
    # so M2.E2 must stay green and only M2.E1 may go red.
    broken = CORRECT["economy"].replace("spec.base_cost * spec.cost_scale ** owned", "spec.base_cost")
    assert broken != CORRECT["economy"]
    v = run(tmp_path, {**CORRECT, "economy": broken}, only="economy")
    assert {i for i, r in v.items() if not r["ok"]} == {"M2.E1"}


def test_a_wrong_error_is_caught(tmp_path):
    broken = CORRECT["economy"].replace("raise loop_types.UnknownGenerator(name)", "raise KeyError(name)")
    v = run(tmp_path, {**CORRECT, "economy": broken}, only="economy")
    assert {i for i, r in v.items() if not r["ok"]} == {"M2.E5"}
    assert v["M2.E5"]["actual"] == {"raises": "KeyError"}


def test_mutating_the_input_is_impossible(tmp_path):
    # Records are frozen (FORMATS 2: no in-place change). An implementation
    # that edits the state it was given crashes in place instead of passing
    # the immutability example by luck.
    broken = CORRECT["rules"].replace(
        "return dataclasses.replace(state, resource=state.resource - cost,",
        "object.__setattr__(state, 'resource', state.resource - cost)\n"
        "    return dataclasses.replace(state, resource=state.resource,")
    v = run(tmp_path, {**CORRECT, "rules": broken}, only="rules")
    assert v["M4.E5"]["ok"] is False


@pytest.mark.parametrize("module", [m["name"] for m in DESIGN.order()])
def test_every_generated_file_compiles(tmp_path, module):
    emit.build_workspace(DESIGN, tmp_path, {})
    for f in [tmp_path / "loop_types.py", tmp_path / "app" / f"{module}.py",
              tmp_path / "tests" / f"test_{module}.py"]:
        compile(f.read_text(encoding="utf-8"), str(f), "exec")


def test_a_stub_filled_in_place_works(tmp_path):
    # Same property as the TypeScript adapter's: the stub's own imports must
    # work at run time, because the solver keeps them.
    stub = emit.emit_stub(DESIGN, DESIGN.by_name["economy"])
    head, _, _ = stub.partition("def production_rate")
    filled = head + "def production_rate(owned, catalog):\n    raise loop_types.UnknownGenerator('any')\n"
    v = run(tmp_path, {**CORRECT, "economy": filled}, only="economy")
    assert v["M2.E5"]["ok"] is True, v["M2.E5"]


def test_definition_examples_copied_into_the_assembly_count_once(tmp_path):
    # maze3d's designer copied all 16 definition examples into the assembly
    # under its own ids; the solver's brief doubled and no longer fit the
    # local model's context. The copy goes, the definition's id stays.
    src = HERE.parents[2] / "docs" / "formats" / "examples"
    design = json.loads((src / "coinroom.design.json").read_text(encoding="utf-8"))
    definition = json.loads((src / "coinroom.definition.json").read_text(encoding="utf-8"))
    defined = [e for item in definition["items"] for e in item["examples"]]
    game = next(m for m in design["modules"] if m["kind"] == "assembly")
    new = {"id": "M6.E99", "steps": [{"let": "s", "call": "start", "args": {"now": 1.0, "saved": None}}],
           "then": {"observe": ["s"], "equals": [defined[0]["then"]["equals"][0] | {"last": 1.0}]}}
    game["examples"] = [{**e, "id": f"M6.E{i}"} for i, e in enumerate(defined, 1)] + [new]
    (tmp_path / "coinroom.definition.json").write_text(json.dumps(definition), encoding="utf-8")
    (tmp_path / "d.json").write_text(json.dumps(design), encoding="utf-8")
    d = emit.Design(tmp_path / "d.json")
    assert [e["id"] for e in d.examples(d.assembly)] == [e["id"] for e in defined] + ["M6.E99"]
