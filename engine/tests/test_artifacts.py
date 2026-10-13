"""The exit gates, in both directions: the idle game passes, and each way of
breaking a definition or a design is refused -- by the right stage, at the
right place."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import artifacts  # noqa: E402

EX = ROOT / "docs" / "formats" / "examples"
DEFINITION = json.loads((EX / "idlegame.definition.json").read_text(encoding="utf-8"))
DESIGN = json.loads((EX / "idlegame.design.json").read_text(encoding="utf-8"))


def item(d, iid):
    return next(i for i in d["items"] if i["id"] == iid)


def module(ds, mid):
    return next(m for m in ds["modules"] if m["id"] == mid)


def test_the_idle_game_passes_both_gates():
    assert artifacts.check_definition(DEFINITION) == []
    assert artifacts.check_design(DESIGN, DEFINITION) == []
    assert artifacts.check_files(EX / "idlegame.design.json") == []


# ---- the definition gate ---------------------------------------------------

def d_unknown_type(d):
    d["types"]["GameState"]["record"][0]["type"] = "Money"

def d_item_without_examples(d):
    item(d, "D4")["examples"] = []

def d_missing_argument(d):
    del item(d, "D3")["examples"][0]["steps"][0]["args"]["name"]

def d_wrong_value_type(d):
    item(d, "D1")["examples"][0]["steps"][0]["args"]["now"] = "noon"

def d_unbound_reference(d):
    item(d, "D2")["examples"][0]["steps"][1]["args"]["state"] = {"$": "nothing"}

def d_undeclared_error(d):
    item(d, "D3")["examples"][2]["then"]["raises"] = "TimeWentBackwards"

def d_contradiction(d):
    clone = copy.deepcopy(item(d, "D3")["examples"][0])
    clone["id"] = "D3.E9"
    clone["then"]["equals"][0]["resource"] = 1.0
    item(d, "D3")["examples"].append(clone)

def d_function_without_example(d):
    d["interface"]["pause"] = {"params": [], "returns": "bool"}

def d_unknown_platform(d):
    d["shell"]["platform"] = "android"

def d_duplicate_id(d):
    item(d, "D4")["examples"][1]["id"] = "D4.E1"

def d_map_with_dollar_key(d):
    item(d, "D1")["examples"][0]["then"]["equals"][0]["owned"] = {"$": 1}


@pytest.mark.parametrize("breaks, where", [
    (d_unknown_type, "types.GameState"),
    (d_item_without_examples, "items[D4]"),
    (d_missing_argument, "examples[D3.E1]"),
    (d_wrong_value_type, "examples[D1.E1]"),
    (d_unbound_reference, "examples[D2.E1]"),
    (d_undeclared_error, "examples[D3.E3]"),
    (d_contradiction, "examples[D3.E9]"),
    (d_function_without_example, "interface.pause"),
    (d_unknown_platform, "shell.platform"),
    (d_duplicate_id, "items"),
    (d_map_with_dollar_key, "examples[D1.E1]"),
])
def test_a_broken_definition_is_refused_by_the_definition_gate(breaks, where):
    d = copy.deepcopy(DEFINITION)
    breaks(d)
    found = artifacts.check_definition(d)
    assert found, f"{breaks.__name__} was not refused"
    assert {f.stage for f in found} == {artifacts.DEFINITION}
    assert any(f.where.startswith(where) for f in found), [str(f) for f in found]


# ---- the design gate ---------------------------------------------------------

def s_type_differs_from_definition(ds):
    ds["types"]["GameState"]["record"].pop()

def s_unreachable_module(ds):
    module(ds, "M7")["depends_on"].remove("M5")

def s_cycle(ds):
    module(ds, "M1")["depends_on"].append("M4")

def s_two_assemblies(ds):
    module(ds, "M6")["kind"] = "assembly"

def s_assembly_drifts(ds):
    module(ds, "M7")["functions"]["click"]["params"].append({"name": "n", "type": "int"})

def s_function_without_example(ds):
    module(ds, "M3")["examples"] = [e for e in module(ds, "M3")["examples"] if e["id"] not in ("M3.E7", "M3.E8")]

def s_call_outside_dependencies(ds):
    module(ds, "M3")["examples"][0]["steps"][0]["call"] = "economy.current_cost"

def s_fixture_wrong_type(ds):
    ds["fixtures"]["CURSOR"]["value"]["base_cost"] = "fifteen"

def s_reference_wrong_type(ds):
    module(ds, "M2")["examples"][0]["steps"][0]["args"]["spec"] = {"$": "CATALOG"}

def s_language_without_adapter(ds):
    ds["target"]["language"] = "cobol"

def s_platform_differs(ds):
    ds["target"]["platform"] = "browser-3d"

def s_shell_bypasses_assembly(ds):
    ds["shell"]["calls"] = "M6"

def s_function_without_doc(ds):
    del module(ds, "M2")["functions"]["current_cost"]["doc"]

def s_empty_doc(ds):
    module(ds, "M7")["functions"]["load"]["doc"] = "  "

def s_unknown_contract_field(ds):
    module(ds, "M2")["functions"]["current_cost"]["notes"] = "x"

def s_module_contradiction(ds):
    clone = copy.deepcopy(module(ds, "M2")["examples"][0])
    clone["id"] = "M2.E9"
    clone["then"]["equals"] = [34.0]
    module(ds, "M2")["examples"].append(clone)


@pytest.mark.parametrize("breaks, where", [
    (s_type_differs_from_definition, "types.GameState"),
    (s_unreachable_module, "modules[M5]"),
    (s_cycle, "modules[M"),
    (s_two_assemblies, "modules"),
    (s_assembly_drifts, "modules[M7]"),
    (s_function_without_example, "modules[M3].functions.format_rate"),
    (s_call_outside_dependencies, "modules[M3].examples[M3.E1]"),
    (s_fixture_wrong_type, "fixtures.CURSOR"),
    (s_reference_wrong_type, "modules[M2].examples[M2.E1]"),
    (s_language_without_adapter, "target.language"),
    (s_platform_differs, "target.platform"),
    (s_shell_bypasses_assembly, "shell.calls"),
    (s_module_contradiction, "modules[M2].examples[M2.E9]"),
    (s_function_without_doc, "modules[M2].functions.current_cost"),
    (s_empty_doc, "modules[M7].functions.load"),
    (s_unknown_contract_field, "modules[M2].functions.current_cost"),
])
def test_a_broken_design_is_refused_by_the_design_gate(breaks, where):
    ds = copy.deepcopy(DESIGN)
    breaks(ds)
    found = artifacts.check_design(ds, DEFINITION)
    assert found, f"{breaks.__name__} was not refused"
    assert {f.stage for f in found} == {artifacts.DESIGN}
    assert any(f.where.startswith(where) for f in found), [str(f) for f in found]


def test_a_design_is_not_judged_against_a_failing_definition(tmp_path):
    d = copy.deepcopy(DEFINITION)
    d_unknown_platform(d)
    (tmp_path / "idlegame.definition.json").write_text(json.dumps(d), encoding="utf-8")
    (tmp_path / "idlegame.design.json").write_text(json.dumps(DESIGN), encoding="utf-8")
    found = artifacts.check_files(tmp_path / "idlegame.design.json")
    assert found and {f.stage for f in found} == {artifacts.DEFINITION}


def test_the_assembly_says_how_while_the_definition_says_what():
    # Their docs differ by design; the contract match must not see it.
    assert DESIGN["modules"][-1]["functions"]["load"]["doc"]
    assert "doc" not in DEFINITION["interface"]["load"]
    assert artifacts.check_design(DESIGN, DEFINITION) == []


# ---- the concept file and the coverage gate (DESIGN 4, FORMATS 11) ----------------

CONCEPTS = json.loads((EX / "idlegame.concepts.json").read_text(encoding="utf-8"))


def concept(c, cid):
    return next(k for k in c["concepts"] if k["id"] == cid)


def test_the_idle_game_concepts_pass_and_its_definition_covers_them():
    assert artifacts.check_concepts(CONCEPTS) == []
    assert artifacts.check_coverage(CONCEPTS, DEFINITION) == []


def broken_concepts():
    def prose_ref(c): concept(c, "C1")["meaning"] = "C2で定めた設備を使う"
    def bad_id(c): concept(c, "C2")["properties"][0]["id"] = "C1.P9"
    def dup(c): c["requirements"][1]["id"] = "R1"
    def implied_no_reason(c): del c["requirements"][1]["reason"]
    def bad_check(c): concept(c, "C1")["properties"][0]["check"] = "maybe"
    def no_props(c): concept(c, "C3")["properties"] = []
    def no_request(c): c["request"] = ""
    def ref_missing(c): c["requirements"][0]["concepts"] = ["C9.P1"]
    def bad_kind(c): concept(c, "C1")["kind"] = "feature"
    def not_ref(c): concept(c, "C1")["not"].append("R1 を満たさないものは違う")
    return [prose_ref, bad_id, dup, implied_no_reason, bad_check, no_props, no_request, ref_missing,
            bad_kind, not_ref]


@pytest.mark.parametrize("breakit", broken_concepts(), ids=lambda f: f.__name__)
def test_a_broken_concept_file_goes_back_to_the_analysis(breakit):
    c = copy.deepcopy(CONCEPTS)
    breakit(c)
    found = artifacts.check_concepts(c)
    assert found and all(f.stage == artifacts.ANALYSIS for f in found), found


def test_ascii_words_in_japanese_are_not_taken_for_references():
    c = copy.deepcopy(CONCEPTS)
    concept(c, "C1")["meaning"] = "3D迷路のように W/A/S/D で歩く。CPU も R&D も関係ない"
    assert artifacts.check_concepts(c) == []


def test_a_property_no_item_checks_sends_the_definition_back():
    d = copy.deepcopy(DEFINITION)
    for it in d["items"]:
        it["concepts"] = [r for r in it.get("concepts", []) if r != "C2.P2"]
    found = artifacts.check_coverage(CONCEPTS, d)
    assert [f.where for f in found] == ["concepts.C2.P2"]
    assert found[0].stage == artifacts.DEFINITION


def test_evaluation_properties_need_no_item_and_retired_ones_may_not_be_cited():
    c = copy.deepcopy(CONCEPTS)
    assert all(f.where != "concepts.C3.P1" for f in artifacts.check_coverage(c, DEFINITION))
    c["requirements"][0]["status"] = "retired"
    found = artifacts.check_coverage(c, DEFINITION)
    assert any("'R1' is retired" in f.message for f in found)


def test_a_definition_must_say_what_it_makes_and_cite_only_what_exists():
    d = copy.deepcopy(DEFINITION)
    del d["summary"]
    item(d, "D1")["concepts"] = ["C7.P1"]
    found = {f.where for f in artifacts.check_coverage(CONCEPTS, d)}
    assert found == {"summary", "items[D1].concepts"}
