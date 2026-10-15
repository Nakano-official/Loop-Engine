"""diagnose, fed real records: each case builds a Python workspace for the idle
game, runs the generated tests the way exec would, and hands the record to
diagnose. The verdict must be the one DESIGN 5's table gives."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "adapters" / "python"))
import diagnose  # noqa: E402
import emit  # noqa: E402

DESIGN = emit.Design(ROOT / "docs" / "formats" / "examples" / "idlegame.design.json")
CORRECT = {p.stem: p.read_text(encoding="utf-8")
           for p in (ROOT / "adapters" / "python" / "tests" / "idlegame").glob("*.py")}
M = DESIGN.by_name


def run(ws: Path, impls: dict, modules: list[str]) -> dict:
    emit.build_workspace(DESIGN, ws, impls)
    env = {**os.environ, "LOOP_EXAMPLES": str(ws / "examples.json"), "LOOP_RECORD_DIR": str(ws)}
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
                          + [f"tests/test_{m}.py" for m in modules],
                          cwd=ws, env=env, capture_output=True, text=True)
    path = ws / "records.jsonl"
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return {"records": records, "output": proc.stdout + proc.stderr}


# ---- the red gate ------------------------------------------------------------

def test_stubs_pass_the_red_gate(tmp_path):
    v = diagnose.red_gate(DESIGN, M["rules"], run(tmp_path, {}, ["rules"]))
    assert v.stage == diagnose.RED


def test_tests_that_did_not_run_are_the_engines_fault(tmp_path):
    r = run(tmp_path, {}, ["rules"])
    r["records"] = [x for x in r["records"] if x["id"] != "M4.E3"]
    v = diagnose.red_gate(DESIGN, M["rules"], r)
    assert v.stage == diagnose.ENGINE and "did not run" in v.reason


def test_a_test_that_cannot_call_the_stub_is_the_engines_fault(tmp_path):
    r = run(tmp_path, {}, ["rules"])
    r["records"] = [x for x in r["records"] if not (x["t"] == "check" and x["id"] == "M4.E2")]
    v = diagnose.red_gate(DESIGN, M["rules"], r)
    assert v.stage == diagnose.ENGINE and "could not call" in v.reason


def test_an_example_passing_against_the_stub_is_the_engines_fault(tmp_path):
    # A "stub" that is really the implementation: a sentinel that collided.
    r = run(tmp_path, {"economy": CORRECT["economy"]}, ["economy"])
    v = diagnose.red_gate(DESIGN, M["economy"], r)
    assert v.stage == diagnose.ENGINE and "passes against the stub" in v.reason


def test_a_condition_met_by_the_stub_is_no_ones_fault(tmp_path):
    # A condition relating two results holds for a stub too, whose results are
    # all the same sentinels (FORMATS 4): the red gate does not ask it to fail.
    r = run(tmp_path, {"economy": CORRECT["economy"]}, ["economy"])

    class AsConditions:
        def __getattr__(self, name):
            return getattr(DESIGN, name)

        def examples(self, module):
            return [{**ex, "then": {"observe": ex["then"].get("observe", []), "holds": "() => true"}}
                    for ex in DESIGN.examples(module)]

    assert diagnose.red_gate(AsConditions(), M["economy"], r).stage == diagnose.RED


# ---- one attempt -------------------------------------------------------------

def test_a_correct_attempt_is_green(tmp_path):
    v = diagnose.attempt(DESIGN, M["economy"], run(tmp_path, CORRECT, ["economy"]), [])
    assert v.stage == diagnose.GREEN


def test_a_wrong_value_goes_back_to_the_implementation_with_what_failed(tmp_path):
    broken = CORRECT["economy"].replace("spec.base_cost * spec.cost_scale ** owned", "spec.base_cost")
    v = diagnose.attempt(DESIGN, M["economy"], run(tmp_path, {**CORRECT, "economy": broken}, ["economy"]), [])
    assert v.stage == diagnose.IMPLEMENTATION
    assert v.facts["failed"] == ["M2.E1"]
    assert any("M2.E1: expected [33.75], got [15.0]" in f for f in v.feedback)


def test_a_module_that_does_not_build_goes_back_to_the_implementation(tmp_path):
    broken = CORRECT["economy"].replace("def current_cost(spec, owned):", "def current_cost(spec, owned)")
    v = diagnose.attempt(DESIGN, M["economy"], run(tmp_path, {**CORRECT, "economy": broken}, ["economy"]), [])
    assert v.stage == diagnose.IMPLEMENTATION and v.facts["built"] is False
    assert "SyntaxError" in v.feedback[0]


def test_breaking_a_green_module_is_reported(tmp_path):
    # rules is attempted after economy went green; this attempt also changed
    # economy (as if rules' solver had reached into it).
    broken = CORRECT["economy"].replace("spec.base_cost * spec.cost_scale ** owned", "spec.base_cost")
    v = diagnose.attempt(DESIGN, M["rules"],
                         run(tmp_path, {**CORRECT, "economy": broken}, ["economy", "rules"]), [M["economy"]])
    assert v.stage == diagnose.IMPLEMENTATION
    assert v.facts["broke"] == ["M2.E1"]


# ---- the attempts used up ----------------------------------------------------

def failing(facts):
    return diagnose.Verdict(diagnose.IMPLEMENTATION, "x", facts=facts)


def test_used_up_on_a_module_is_granularity():
    v = diagnose.exhausted(DESIGN, M["rules"], [failing({"failed": ["M4.E2"], "broke": []})] * 3)
    assert v.stage == diagnose.DESIGN and v.reason.startswith("granularity")


def test_used_up_breaking_green_every_time_is_a_boundary():
    v = diagnose.exhausted(DESIGN, M["rules"], [failing({"failed": [], "broke": ["M2.E1"]})] * 3)
    assert v.reason.startswith("boundary: every attempt broke")


def test_used_up_needing_undeclared_modules_every_time_is_a_boundary():
    v = diagnose.exhausted(DESIGN, M["rules"], [failing({"failed": ["M4.E2"], "undeclared": ["save"]})] * 3)
    assert v.reason.startswith("boundary: every attempt needed")


def test_used_up_reaching_outside_the_module_every_time_is_a_boundary():
    v = diagnose.exhausted(DESIGN, M["rules"], [failing({"failed": ["M4.E2"], "forbidden": ["Date"]})] * 3)
    assert v.reason.startswith("boundary: every attempt reached outside")


def test_a_refused_attempt_goes_back_to_the_implementation_with_what_it_reached_for():
    run_ = {"records": [], "output": "", "undeclared": [], "forbidden": ["Math.random", "fetch"]}
    v = diagnose.attempt(DESIGN, M["rules"], run_, [])
    assert v.stage == diagnose.IMPLEMENTATION and v.reason.startswith("refused before it ran")
    assert "Math.random, fetch" in v.feedback[0]
    assert v.facts["forbidden"] == ["Math.random", "fetch"]
    run_ = {"records": [], "output": "", "undeclared": ["app.save"], "forbidden": []}
    v = diagnose.attempt(DESIGN, M["rules"], run_, [])
    assert "app.save" in v.feedback[0] and v.facts["undeclared"] == ["app.save"]


def test_used_up_on_the_assembly_is_decomposition():
    v = diagnose.exhausted(DESIGN, DESIGN.assembly, [failing({"failed": ["D3.E1"], "broke": []})] * 3)
    assert v.stage == diagnose.DESIGN and v.reason.startswith("decomposition")


def test_the_design_is_never_shown_what_the_implementation_returned(tmp_path):
    broken = CORRECT["economy"].replace("spec.base_cost * spec.cost_scale ** owned", "spec.base_cost")
    a = diagnose.attempt(DESIGN, M["economy"], run(tmp_path, {**CORRECT, "economy": broken}, ["economy"]), [])
    v = diagnose.exhausted(DESIGN, M["economy"], [a, a, a])
    shown = json.dumps(v.for_design())
    assert "M2.E1" in shown and "15.0" not in shown and "33.75" not in shown
