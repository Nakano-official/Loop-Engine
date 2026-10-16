"""From requirements: the analyst, the definer and the designer in
front of the modules.

The roles are stand-ins that write the idle game -- in the shapes of
tests/shapes.py: what to make, then its examples -- and its design into their
out/, the way a Claude role would through run-role; the solver is the
reference implementation. Python is the target here (as in test_pipeline), so
the platform's language rule is read as Python and no output is built.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import artifacts  # noqa: E402
import pipeline  # noqa: E402
import window as window_mod  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shapes import draft_of, platform_design  # noqa: E402

EX = ROOT / "docs" / "formats" / "examples"
CONCEPTS = (EX / "idlegame.concepts.json").read_text(encoding="utf-8")
FULL = json.loads((EX / "idlegame.definition.json").read_text(encoding="utf-8"))
DEFINITION = json.dumps(draft_of(FULL))                  # what the definer writes
# The design, its assembly carrying the examples that check the items (DECISIONS 48).
DESIGN = platform_design(json.loads((EX / "idlegame.design.json").read_text(encoding="utf-8")), FULL)
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
    for role in ("analyst", "definer", "designer"):
        (roles / role / "in").mkdir(parents=True)
        (roles / role / "out").mkdir(parents=True)
    w = window_mod.Window(tmp_path / "work", window_mod.local_runner, roles=roles)
    w.briefs = {"analyst": [], "definer": [], "designer": []}
    w.staged = {}
    return w


def roles(win, definitions, designs, concepts=(CONCEPTS,), modules=None):
    """Stand-ins: each call writes the next of the given files. The designer
    writes in parts (DECISIONS 47): asked for the plan, it takes the next
    design and writes its plan; asked for a module, that design's module.
    Its plan briefs are kept under "designer", its module briefs under
    "designer_module". `modules`: {name: [part, ...]} -- what it writes for
    that module, call after call, in place of the design's."""
    queue = {"analyst": list(concepts), "definer": list(definitions), "designer": list(designs)}
    overrides = {k: list(v) for k, v in (modules or {}).items()}
    current = {}

    def run_role(role, brief):
        text_in = Path(brief).read_text(encoding="utf-8")
        name = {"analyst": "concepts.json", "definer": "definition.json", "designer": "design.json"}[role]
        key = role
        if role == "designer":
            m = re.search(r"Write module `([a-z0-9_]+)`", text_in)
            if m:
                key, name = "designer_module", "module.json"
                mod = next(x for x in current["design"]["modules"] if x["name"] == m.group(1))
                if overrides.get(mod["name"]):
                    text = overrides[mod["name"]].pop(0) if len(overrides[mod["name"]]) > 1 \
                        else overrides[mod["name"]][0]
                else:
                    text = json.dumps({"functions": {fn: {"doc": sig["doc"]} for fn, sig in mod["functions"].items()},
                                       "examples": mod["examples"],
                                       "fixtures": {k: v for k, v in current["design"].get("fixtures", {}).items()
                                                    if k in json.dumps(mod["examples"])}})
            else:
                current["design"] = json.loads(queue[role].pop(0) if len(queue[role]) > 1 else queue[role][0])
                text = json.dumps(artifacts.plan_of(current["design"]))
        else:
            text = queue[role].pop(0) if len(queue[role]) > 1 else queue[role][0]
        win.briefs.setdefault(key, []).append(text_in)
        # Given back what it wrote (out/edit/), a role fixes it there, as the Edit tool would.
        edit = win.roles / role / "out" / "edit"
        win.staged.setdefault(key, []).append((edit / name).read_text(encoding="utf-8") if edit.is_dir() else None)
        (edit if edit.is_dir() else win.roles / role / "out").joinpath(name).write_text(text, encoding="utf-8")
        return 0, f"[{role}] wrote {name}"

    win.run_role_fn = run_role


def reference(d, module, feedback):
    return {f"app/{module['name']}.py": CORRECT[module["name"]]}


def test_requirements_to_green_through_both_gates(win, tmp_path):
    broken = json.loads(DEFINITION)
    broken["types"]["Screen"] = FULL["types"]["Screen"]   # the platform's type, copied out
    roles(win, [json.dumps(broken), DEFINITION], [json.dumps(DESIGN)])
    ledger = tmp_path / "ledger.jsonl"
    out = pipeline.run_from_requirements("放置ゲームを作る", tmp_path / "app", win, "up1", solver=reference,
                                         ledger=pipeline.Ledger(ledger), build=False)
    assert out.stage == "done", (out.stage, out.reason)
    assert out.green[-1] == "game"
    # The definer was refused once, and told why.
    assert len(win.briefs["definer"]) == 2
    assert "types.Screen" in win.briefs["definer"][1]
    # ... and given back what it wrote, to fix in place rather than write again.
    assert "edit/definition.json" in win.briefs["definer"][1]
    assert win.staged["definer"][0] is None and "Screen" in json.loads(win.staged["definer"][1])["types"]
    entries = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    events = [e["event"] for e in entries if e["event"] != "BEGIN"]
    # The designer in parts (DECISIONS 47): the plan, then one call per module.
    n_modules = len(DESIGN["modules"])
    assert events[:4 + n_modules + 1] == ["ANALYST", "DEFINER", "DEFINER"] + ["DESIGNER"] * (1 + n_modules) \
        + ["DESIGN_ROUND"]
    parts = [e.get("part") for e in entries if e["event"] == "DESIGNER"]
    assert parts == ["plan"] + [m["name"] for m in DESIGN["modules"]]
    # Every long step says when it starts, so a dashboard can show it while it runs.
    begun = [(e["step"], e.get("n")) for e in entries if e["event"] == "BEGIN"][:4]
    assert begun == [("analyst", 1), ("definer", 1), ("definer", 2), ("designer", 1)]
    # Each part reads what it needs: the plan has no examples in it, and the
    # assembly's brief has the items and what they answer to -- the examples
    # it writes check them (DECISIONS 48).
    assert all('"steps"' not in b for b in win.briefs["designer"])
    [game] = [b for b in win.briefs["designer_module"] if "Write module `game`" in b]
    assert "## D7" in game and "C2.P1" in game and '"concepts" field' in game
    assert all("## D7" not in b for b in win.briefs["designer_module"] if b is not game)
    # The definer is not asked for examples or the platform's functions.
    assert "Do not write examples" in win.briefs["definer"][0] and '"steps"' not in win.briefs["definer"][0]
    kept_def = json.loads((tmp_path / "app" / "definition.json").read_text(encoding="utf-8"))
    assert list(kept_def["interface"]) == ["start", "step", "act", "screen", "save"]
    assert "examples" not in kept_def["items"][0]
    # The concept file is kept with the request put in verbatim by the machine,
    # and the definer was given it -- not the request alone.
    kept = json.loads((tmp_path / "app" / "concepts.json").read_text(encoding="utf-8"))
    assert kept["request"] == "放置ゲームを作る"
    assert "生産設備" in win.briefs["definer"][0] and "C2.P1" in win.briefs["definer"][0]
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


def test_the_platform_chosen_is_the_one_the_definition_gets(win, tmp_path):
    # The person chose browser-3d. The definer is told that platform's
    # functions and conventions; the machine gives the definition its
    # functions -- step takes input there, so a design made for the idle
    # game's browser-dom does not fit, and goes back to the designer.
    roles(win, [DEFINITION], [json.dumps(DESIGN)])
    out = pipeline.run_from_requirements("3Dで歩く", tmp_path / "app", win, "up4", solver=reference,
                                         gate_rounds=2, build=False, platform="browser-3d")
    assert out.stage == "モジュール設計"
    first = win.briefs["definer"][0]
    assert "step(state: $State, now: float, input: Input) -> $State" in first
    assert "Conventions:" in first and "vertical field of view in degrees" in first
    assert "step(state: GameState, now: float, input: Input)" not in first
    assert len(win.briefs["designer"]) == 2 and "edit/design.json" in win.briefs["designer"][1]


def test_an_assembly_that_shows_no_example_of_a_property_goes_back_to_the_designer(win, tmp_path):
    asm = next(m for m in DESIGN["modules"] if m["kind"] == "assembly")
    part = {"functions": {fn: {"doc": sig["doc"]} for fn, sig in asm["functions"].items()},
            "examples": asm["examples"]}
    short = json.loads(json.dumps(part))
    short["examples"][0]["concepts"] = [r for r in short["examples"][0]["concepts"] if r != "C2.P2"]
    roles(win, [DEFINITION], [json.dumps(DESIGN)], modules={asm["name"]: [json.dumps(short), json.dumps(part)]})
    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up8", solver=reference, build=False)
    assert out.stage == "done", (out.stage, out.reason)
    tries = [b for b in win.briefs["designer_module"] if f"Write module `{asm['name']}`" in b]
    assert len(tries) == 2 and "concepts.C2.P2" in tries[1] and "edit/module.json" in tries[1]


def test_a_concept_file_that_never_passes_stops_at_the_analysis(win, tmp_path):
    broken = json.loads(CONCEPTS)
    broken["concepts"][0]["meaning"] = "C2で定めたものと同じ"
    roles(win, [DEFINITION], [json.dumps(DESIGN)], concepts=[json.dumps(broken)])
    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up5", solver=reference, gate_rounds=2,
                                         build=False)
    assert out.stage == "要求分析"
    assert len(win.briefs["analyst"]) == 2 and "in prose" in win.briefs["analyst"][1]
    assert win.briefs["definer"] == []


def test_a_definition_that_leaves_a_property_unchecked_goes_back_to_the_definer(win, tmp_path):
    uncovered = json.loads(DEFINITION)
    for item in uncovered["items"]:
        item["concepts"] = [r for r in item["concepts"] if r != "C2.P2"]
    roles(win, [json.dumps(uncovered), DEFINITION], [json.dumps(DESIGN)])
    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up6", solver=reference, build=False)
    assert out.stage == "done"
    assert len(win.briefs["definer"]) == 2 and "concepts.C2.P2" in win.briefs["definer"][1]


def test_a_run_can_stop_after_the_analysis(win, tmp_path):
    roles(win, [DEFINITION], [json.dumps(DESIGN)])
    ledger = tmp_path / "ledger.jsonl"
    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up7", solver=reference, build=False,
                                         ledger=pipeline.Ledger(ledger), until="analysis")
    assert out.stage == pipeline.UNTIL
    assert (tmp_path / "app" / "concepts.json").exists() and win.briefs["definer"] == []
    assert json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])["event"] == "UNTIL"


# ---- from what an earlier run left (cli run --from-definition) ---------------

def kept_definition():
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "engine"))
    import artifacts
    return artifacts.complete(json.loads(DEFINITION), "browser-dom")


def test_a_run_can_start_at_the_design_from_what_an_earlier_run_left(win, tmp_path):
    roles(win, [DEFINITION], [json.dumps(DESIGN)])
    ledger = tmp_path / "ledger.jsonl"
    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up9", solver=reference, build=False,
                                         ledger=pipeline.Ledger(ledger),
                                         resume={"from": "r1", "concepts": json.loads(CONCEPTS),
                                                 "definition": kept_definition()})
    assert out.stage == "done", (out.stage, out.reason)
    assert win.briefs["analyst"] == win.briefs["definer"] == []
    assert len(win.briefs["designer"]) == 1
    first = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert first == {**first, "event": "FROM", "run": "r1", "stages": ["analysis", "definition"]}
    assert (tmp_path / "app" / "definition.json").exists() and (tmp_path / "app" / "concepts.json").exists()


def test_what_an_earlier_run_left_is_held_at_its_gates_again(win, tmp_path):
    roles(win, [DEFINITION], [json.dumps(DESIGN)])
    broken = kept_definition()
    broken["types"]["GameState"]["record"][0]["type"] = "Money"           # a type that is nowhere
    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up10", solver=reference, build=False,
                                         resume={"from": "r1", "concepts": json.loads(CONCEPTS),
                                                 "definition": broken})
    assert out.stage == "要件定義" and any("Money" in f for f in out.detail["findings"])
    assert win.briefs["designer"] == []


def test_every_upstream_brief_says_how_to_write_and_to_compute_with_the_run_tool(win, tmp_path):
    roles(win, [DEFINITION], [json.dumps(DESIGN)])
    pipeline.run_from_requirements("x", tmp_path / "app", win, "up11", solver=reference, build=False,
                                   until="design")
    # Whole files, written in parts; parts, written in one go (DECISIONS 47).
    for role in ("analyst", "definer"):
        assert "First Write a skeleton" in win.briefs[role][0] and "`run` tool" in win.briefs[role][0], role
    for role in ("designer", "designer_module"):
        assert "in one go" in win.briefs[role][0] and "`run` tool" in win.briefs[role][0], role


# ---- what went green is not written again (DECISIONS 46) ---------------------

def test_a_second_design_reuses_what_went_green_under_the_first(win, tmp_path):
    roles(win, [DEFINITION], [json.dumps(DESIGN)])
    asked = []

    def stuck(d, module, feedback):
        asked.append(module["name"])
        if module["name"] == "format":
            return {"app/format.py": CORRECT["format"].replace(":.2f", ":.3f")}
        return reference(d, module, feedback)

    ledger = tmp_path / "ledger.jsonl"
    out = pipeline.run_from_requirements("x", tmp_path / "app", win, "up12", solver=stuck, max_attempts=1,
                                         redesigns=1, build=False, ledger=pipeline.Ledger(ledger))
    assert out.stage == "モジュール設計"
    first_round = asked[:asked.index("format") + 1]
    # The same design came back: everything that was green is reused, and
    # only the module that never went green is asked of the solver again.
    assert asked[len(first_round):] == ["format"]
    events = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    reused = [e["module"] for e in events if e["event"] == "REUSED"]
    assert reused == first_round[:-1]


def test_a_fingerprint_changes_with_what_the_module_is_held_to():
    import copy
    sys.path.insert(0, str(ROOT / "adapters"))
    from design import Design
    path = Path(__file__).resolve().parents[2] / "docs" / "formats" / "examples" / "idlegame.design.json"
    d = Design(path)
    m = d.by_name["format"]
    same = d.fingerprint(m)
    assert same == Design(path).fingerprint(Design(path).by_name["format"])
    m2 = copy.deepcopy(m)
    m2["examples"][0]["then"]["equals"] = ["9.99"]
    assert d.fingerprint(m2) != same
    # Another module's doc does not reach this module's tests.
    other = d.by_name["economy"]
    fn = next(iter(other["functions"]))
    before = d.fingerprint(d.by_name["rules"]) if d.by_name["rules"]["depends_on"] else None
    other["functions"][fn]["doc"] = "changed"
    if before is not None:
        assert d.fingerprint(d.by_name["rules"]) == before


def test_the_solver_is_told_what_a_dependency_does_not_how():
    import briefs
    assert briefs.what_it_does("壁の箱を返す。手順: scene_shapes.wall_box で作る") == "壁の箱を返す。"
    assert briefs.what_it_does("Returns the cost. Calls rules.price first.") == "Returns the cost."
    assert briefs.what_it_does("") == "(no description)"


def test_a_design_sent_back_is_changed_in_place_not_written_again(win, tmp_path):
    roles(win, [DEFINITION], [json.dumps(DESIGN)])

    def stuck(d, module, feedback):
        if module["name"] == "format":
            return {"app/format.py": CORRECT["format"].replace(":.2f", ":.3f")}
        return reference(d, module, feedback)

    pipeline.run_from_requirements("x", tmp_path / "app", win, "up13", solver=stuck, max_attempts=1,
                                   redesigns=1, build=False)
    first, second = win.briefs["designer"]
    # The first is written from a skeleton; the second is the first, changed.
    assert "in one go" in first and "edit/design.json" not in first
    assert "Do not write a new" in second and "edit/design.json" in second
    assert "in one go" not in second and "# Your previous design" not in second
    assert win.staged["designer"][0] is None
    assert json.loads(win.staged["designer"][1])["modules"] == artifacts.plan_of(DESIGN)["modules"]
    # Only the module the verdict named is written again; the rest are kept.
    modules_second = win.briefs["designer_module"][len(DESIGN["modules"]):]
    assert len(modules_second) == 1 and "Write module `format`" in modules_second[0]

