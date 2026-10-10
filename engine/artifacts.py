"""The exit gates for the definition and the design (REDESIGN 4, FORMATS 7).

    check_definition(definition)         -> [Finding]
    check_design(design, definition)     -> [Finding]

A part, not a flow: it reads two JSON documents and says what is wrong with
them, and where. Each finding names the stage that is at fault, which is what
the place a test fails has to name (REDESIGN 4): a definition that fails its
gate goes back to requirements definition; a design that fails its gate goes
back to module design, never further -- the definition it was checked against
already passed its own.

Nothing here runs code or calls a model. Every rule is one the machine can
decide by reading.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters"))
from design import PRIMITIVES, is_ref, parse_type  # noqa: E402

DEFINITION = "要件定義"
DESIGN = "モジュール設計"

PLATFORM_DIR = Path(__file__).resolve().parents[1] / "adapters" / "platforms"
# The platforms that exist: a directory with a platform.json. REDESIGN 1 names
# browser-dom and browser-3d as the target; only what is built is accepted.
PLATFORMS = {p.name for p in PLATFORM_DIR.glob("*") if (p / "platform.json").exists()}


def platform(name: str) -> dict | None:
    path = PLATFORM_DIR / name / "platform.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
LANGUAGES = {"python", "typescript"}                          # adapters/ that exist
KINDS = {"pure", "assembly", "support"}                       # FORMATS 5
SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
CAPS = re.compile(r"^[A-Z][A-Za-z0-9]*$")
FIXTURE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class Finding:
    stage: str          # the stage at fault: 要件定義 or モジュール設計
    where: str          # a JSON-ish location, e.g. "modules[M4].examples[M4.E2]"
    message: str

    def __str__(self) -> str:
        return f"[{self.stage}] {self.where}: {self.message}"


class _Gate:
    def __init__(self, stage: str):
        self.stage = stage
        self.findings: list[Finding] = []

    def bad(self, where: str, message: str) -> None:
        self.findings.append(Finding(self.stage, where, message))

    # ---- types ------------------------------------------------------------

    def type_ok(self, t: Any, types: dict, where: str) -> bool:
        if not isinstance(t, str):
            self.bad(where, f"a type must be a string, not {t!r}")
            return False
        try:
            kind = parse_type(t)
        except Exception:  # noqa: BLE001
            self.bad(where, f"cannot read the type {t!r}")
            return False
        return self._kind_ok(kind, types, where, t)

    def _kind_ok(self, kind: tuple, types: dict, where: str, t: str) -> bool:
        if kind[0] == "prim":
            return True
        if kind[0] in ("list", "map", "optional"):
            return self._kind_ok(kind[1], types, where, t)
        if kind[1] not in types:
            self.bad(where, f"unknown type {kind[1]!r} in {t!r}")
            return False
        return True

    def types_ok(self, types: Any, where: str) -> dict:
        if not isinstance(types, dict):
            self.bad(where, "types must be an object")
            return {}
        for name, decl in types.items():
            w = f"{where}.{name}"
            if not CAPS.match(name) or name in PRIMITIVES:
                self.bad(w, "a type name is CapWords and not a primitive")
            if isinstance(decl, dict) and set(decl) == {"record"} and isinstance(decl["record"], list):
                seen = set()
                for f in decl["record"]:
                    if not (isinstance(f, dict) and set(f) == {"name", "type"}):
                        self.bad(w, f"a field is {{name, type}}, not {f!r}")
                        continue
                    if not SNAKE.match(f["name"]):
                        self.bad(w, f"field name {f['name']!r} is not snake_case")
                    if f["name"] in seen:
                        self.bad(w, f"field {f['name']!r} appears twice")
                    seen.add(f["name"])
                    self.type_ok(f["type"], types, f"{w}.{f['name']}")
            elif isinstance(decl, dict) and set(decl) == {"enum"} and isinstance(decl["enum"], list):
                vals = decl["enum"]
                if not vals or not all(isinstance(v, str) and v for v in vals) or len(set(vals)) != len(vals):
                    self.bad(w, "an enum is a non-empty list of distinct strings")
            else:
                self.bad(w, "a type is {record: [...]} or {enum: [...]}")
        return types

    def errors_ok(self, errors: Any, where: str) -> dict:
        if not isinstance(errors, dict):
            self.bad(where, "errors must be an object")
            return {}
        for name, text in errors.items():
            if not CAPS.match(name) or not isinstance(text, str):
                self.bad(f"{where}.{name}", "an error is a CapWords name with a description")
        return errors

    def contract_ok(self, name: str, sig: Any, types: dict, errors: dict, where: str,
                    need_doc: bool = False) -> bool:
        if not SNAKE.match(name):
            self.bad(where, f"function name {name!r} is not snake_case")
        if not (isinstance(sig, dict) and isinstance(sig.get("params"), list) and "returns" in sig):
            self.bad(where, "a contract is {params: [...], returns, raises?, doc?}")
            return False
        unknown = set(sig) - {"params", "returns", "raises", "doc"}
        if unknown:
            self.bad(where, f"a contract has no field {sorted(unknown)}")
        # A design says HOW each function does what it does (FORMATS 3). The
        # first run with the real solver stopped on an assembly function whose
        # composition -- read the save, then advance it to now -- was written
        # nowhere the implementer reads: examples alone did not carry it.
        if need_doc and not (isinstance(sig.get("doc"), str) and sig["doc"].strip()):
            self.bad(where, "no doc: a design says how each function does what it does")
        seen = set()
        for p in sig["params"]:
            if not (isinstance(p, dict) and set(p) == {"name", "type"}):
                self.bad(where, f"a parameter is {{name, type}}, not {p!r}")
                continue
            if p["name"] in seen:
                self.bad(where, f"parameter {p['name']!r} appears twice")
            seen.add(p["name"])
            self.type_ok(p["type"], types, f"{where}({p['name']})")
        self.type_ok(sig["returns"], types, f"{where}.returns")
        for e in sig.get("raises", []):
            if e not in errors:
                self.bad(where, f"raises {e!r}, which is not a declared error")
        return True

    # ---- values -----------------------------------------------------------

    def value_ok(self, v: Any, t: str, types: dict, where: str) -> None:
        def fits(v: Any, kind: tuple) -> bool:
            k = kind[0]
            if k == "prim":
                return {"int": isinstance(v, int) and not isinstance(v, bool),
                        "float": isinstance(v, (int, float)) and not isinstance(v, bool),
                        "string": isinstance(v, str),
                        "bool": isinstance(v, bool)}[kind[1]]
            if k == "optional":
                return v is None or fits(v, kind[1])
            if k == "list":
                return isinstance(v, list) and all(fits(x, kind[1]) for x in v)
            if k == "map":
                # "$" alone would read as a reference.
                return isinstance(v, dict) and "$" not in v and all(fits(x, kind[1]) for x in v.values())
            decl = types.get(kind[1], {})
            if "enum" in decl:
                return v in decl["enum"]
            fields = decl.get("record", [])
            return (isinstance(v, dict) and set(v) == {f["name"] for f in fields}
                    and all(fits(v[f["name"]], parse_type(f["type"])) for f in fields))
        if not fits(v, parse_type(t)):
            self.bad(where, f"{json.dumps(v, ensure_ascii=False)[:80]} is not a {t}")

    # ---- examples ---------------------------------------------------------

    def examples_ok(self, examples: list, reachable: dict, types: dict, errors: dict,
                    fixtures: dict, where: str) -> set[str]:
        """reachable: callable name -> contract. Returns the bare names called."""
        called = set()
        seen_inputs: dict[str, tuple[str, str]] = {}
        for ex in examples:
            w = f"{where}[{ex.get('id', '?')}]"
            if not isinstance(ex.get("steps"), list) or not ex["steps"] or "then" not in ex:
                self.bad(w, "an example is {id, steps: [...], then}")
                continue
            scope: dict[str, str] = {}
            last_sig = None
            for i, st in enumerate(ex["steps"]):
                sw = f"{w}.steps[{i}]"
                name = st.get("let")
                if not isinstance(name, str) or not SNAKE.match(name):
                    self.bad(sw, "every step binds a snake_case name with let")
                    continue
                if name in scope or name in fixtures:
                    self.bad(sw, f"{name!r} is bound twice")
                if "value" in st:
                    if self.type_ok(st.get("type"), types, sw):
                        self.value_ok(st["value"], st["type"], types, sw)
                    scope[name] = st.get("type", "")
                    last_sig = None
                    continue
                sig = reachable.get(st.get("call"))
                if sig is None:
                    self.bad(sw, f"calls {st.get('call')!r}, which this example cannot reach")
                    continue
                called.add(st["call"])
                last_sig = sig
                params = {p["name"]: p["type"] for p in sig["params"]}
                args = st.get("args", {})
                if set(args) != set(params):
                    self.bad(sw, f"arguments {sorted(args)} do not match the parameters {sorted(params)}")
                for a, v in args.items():
                    if a not in params:
                        continue
                    if is_ref(v):
                        got = scope.get(v["$"]) or fixtures.get(v["$"], {}).get("type")
                        if got is None:
                            self.bad(sw, f"${v['$']} refers to nothing bound before it")
                        elif not _assignable(got, params[a]):
                            self.bad(sw, f"${v['$']} is a {got}, the parameter {a} is a {params[a]}")
                    else:
                        self.value_ok(v, params[a], types, f"{sw}.{a}")
                scope[name] = sig["returns"]
            then = ex["then"]
            if "raises" in then:
                if last_sig is None:
                    self.bad(w, "an error is expected of the last step, which is not a call")
                elif then["raises"] not in last_sig.get("raises", []):
                    self.bad(w, f"expects {then['raises']!r}, which the last call does not declare")
                outcome = ("raises", then["raises"])
            elif isinstance(then.get("observe"), list) and isinstance(then.get("equals"), list):
                if len(then["observe"]) != len(then["equals"]) or not then["observe"]:
                    self.bad(w, "observe and equals must be the same, non-zero length")
                for ref, val in zip(then["observe"], then["equals"]):
                    if ref not in scope:
                        self.bad(w, f"observes {ref!r}, which is not bound")
                    elif not is_ref(val):
                        self.value_ok(val, scope[ref], types, f"{w}.equals")
                outcome = ("equals", json.dumps(then["equals"], sort_keys=True))
            else:
                self.bad(w, "then is {observe, equals} or {raises}")
                continue
            # The same call on the same input cannot have two answers. Checked
            # for one-step examples, the only case the machine can decide.
            if len(ex["steps"]) == 1 and "call" in ex["steps"][0]:
                st = ex["steps"][0]
                key = f"{st['call']}({json.dumps(st.get('args', {}), sort_keys=True)})"
                prev = seen_inputs.get(key)
                if prev and prev[1] != json.dumps(outcome):
                    self.bad(w, f"{st['call']} on the same input as {prev[0]} expects something else")
                seen_inputs.setdefault(key, (ex["id"], json.dumps(outcome)))
        return called


def _without_doc(functions: dict) -> dict:
    return {n: {k: v for k, v in sig.items() if k != "doc"} if isinstance(sig, dict) else sig
            for n, sig in functions.items()}


def _assignable(got: str, want: str) -> bool:
    """A value of type `got` may be passed where `want` is expected: the same
    type, or `want` is optional<got> -- something present where "maybe
    absent" is allowed. Nothing looser: an int is not a float here, because
    the examples are typed and the adapters decode by the declared type."""
    got, want = got.replace(" ", ""), want.replace(" ", "")
    return got == want or want == f"optional<{got}>"


def _ids_ok(gate: _Gate, ids: list[str], where: str) -> None:
    seen = set()
    for i in ids:
        if i in seen:
            gate.bad(where, f"id {i!r} appears twice")
        seen.add(i)


# ---- the definition ------------------------------------------------------

def check_definition(d: Any) -> list[Finding]:
    g = _Gate(DEFINITION)
    if not isinstance(d, dict) or d.get("format") != "loop/definition@1":
        g.bad("format", "not a loop/definition@1 document")
        return g.findings
    types = g.types_ok(d.get("types", {}), "types")
    errors = g.errors_ok(d.get("errors", {}), "errors")
    interface = d.get("interface", {})
    if not isinstance(interface, dict) or not interface:
        g.bad("interface", "the external interface has no functions")
        interface = {}
    for name, sig in interface.items():
        g.contract_ok(name, sig, types, errors, f"interface.{name}")
    items = d.get("items", [])
    ids = []
    examples = []
    for item in items:
        iid = item.get("id", "?")
        ids.append(iid)
        if not item.get("examples"):
            g.bad(f"items[{iid}]", "a definition item without examples cannot be checked")
        for ex in item.get("examples", []):
            ids.append(ex.get("id", "?"))
            if not str(ex.get("id", "")).startswith(iid + "."):
                g.bad(f"items[{iid}]", f"example {ex.get('id')!r} is outside its item")
            examples.append(ex)
    _ids_ok(g, ids, "items")
    called = g.examples_ok(examples, interface, types, errors, {}, "examples")
    for name in interface:
        if name not in called:
            g.bad(f"interface.{name}", "no example calls it")
    shell = d.get("shell", {})
    if shell.get("platform") not in PLATFORMS:
        g.bad("shell.platform", f"{shell.get('platform')!r} is not one of {sorted(PLATFORMS)}")
    else:
        _platform_ok(g, d, platform(shell["platform"]))
    return g.findings


def _platform_ok(g: _Gate, d: dict, plat: dict) -> None:
    """The definition offers what its platform's shell calls (REDESIGN 1): the
    platform's types, declared exactly, and its functions, with the app's state
    type ($State) the same record throughout."""
    name = plat["name"]
    for tname, decl in plat["types"].items():
        if d.get("types", {}).get(tname) != decl:
            g.bad(f"types.{tname}", f"{name} requires this type exactly as its platform declares it")
    interface = d.get("interface", {})
    start = interface.get("start", {})
    state = start.get("returns") if isinstance(start, dict) else None
    if not (isinstance(state, str) and "record" in d.get("types", {}).get(state, {})):
        g.bad("interface.start", f"{name} requires start to return the app's state, a record type")
        return
    for fn, want in plat["interface"].items():
        got = interface.get(fn)
        if not isinstance(got, dict):
            g.bad(f"interface.{fn}", f"{name}'s shell calls {fn}; the interface does not have it")
            continue
        want_params = [(p["name"], p["type"].replace("$State", state)) for p in want["params"]]
        got_params = [(p.get("name"), p.get("type")) for p in got.get("params", [])]
        if got_params != want_params or got.get("returns") != want["returns"].replace("$State", state):
            sig = ", ".join(f"{n}: {t}" for n, t in want_params)
            g.bad(f"interface.{fn}",
                  f"{name} requires {fn}({sig}) -> {want['returns'].replace('$State', state)}")


# ---- the design ----------------------------------------------------------

def check_design(ds: Any, definition: dict) -> list[Finding]:
    g = _Gate(DESIGN)
    if not isinstance(ds, dict) or ds.get("format") != "loop/design@1":
        g.bad("format", "not a loop/design@1 document")
        return g.findings
    target = ds.get("target", {})
    if target.get("language") not in LANGUAGES:
        g.bad("target.language", f"no adapter for {target.get('language')!r} ({sorted(LANGUAGES)})")
    plat = platform(str(target.get("platform")))
    if plat and target.get("language") != plat["language"]:
        g.bad("target.language", f"{plat['name']} is built from {plat['language']}, not {target.get('language')}")
    if target.get("platform") != definition.get("shell", {}).get("platform"):
        g.bad("target.platform", "differs from the platform the definition declares")

    types = g.types_ok(ds.get("types", {}), "types")
    errors = g.errors_ok(ds.get("errors", {}), "errors")
    for name, decl in definition.get("types", {}).items():
        if types.get(name) != decl:
            g.bad(f"types.{name}", "differs from the definition, or is missing")
    for name in definition.get("errors", {}):
        if name not in errors:
            g.bad(f"errors.{name}", "the definition declares it; the design does not")

    fixtures = ds.get("fixtures", {})
    for name, fx in fixtures.items():
        w = f"fixtures.{name}"
        if not FIXTURE.match(name):
            g.bad(w, "a fixture name is UPPER_CASE")
        if g.type_ok(fx.get("type"), types, w):
            g.value_ok(fx.get("value"), fx["type"], types, w)

    modules = ds.get("modules", [])
    by_id = {m.get("id"): m for m in modules}
    _ids_ok(g, [m.get("id", "?") for m in modules], "modules")
    _ids_ok(g, [m.get("name", "?") for m in modules], "modules (names)")
    for m in modules:
        w = f"modules[{m.get('id')}]"
        if not SNAKE.match(str(m.get("name", ""))):
            g.bad(w, f"module name {m.get('name')!r} is not snake_case")
        if m.get("kind") not in KINDS:
            g.bad(w, f"kind {m.get('kind')!r} is not one of {sorted(KINDS)}")
        for dep in m.get("depends_on", []):
            if dep not in by_id or dep == m.get("id"):
                g.bad(w, f"depends on {dep!r}, which is not another module")
        for fn, sig in m.get("functions", {}).items():
            g.contract_ok(fn, sig, types, errors, f"{w}.functions.{fn}", need_doc=True)

    # Acyclic.
    state: dict[str, int] = {}

    def visit(mid: str) -> None:
        if state.get(mid) == 1:
            g.bad(f"modules[{mid}]", "is part of a dependency cycle")
            return
        if state.get(mid) == 2 or mid not in by_id:
            return
        state[mid] = 1
        for dep in by_id[mid].get("depends_on", []):
            visit(dep)
        state[mid] = 2

    for mid in by_id:
        visit(mid)

    assemblies = [m for m in modules if m.get("kind") == "assembly"]
    if len(assemblies) != 1:
        g.bad("modules", f"exactly one assembly module is required, found {len(assemblies)}")
        return g.findings
    asm = assemblies[0]
    # The assembly's contract is the interface: same functions, parameters,
    # returns and errors. Not the same doc -- the definition says what, the
    # design says how.
    if _without_doc(asm.get("functions", {})) != _without_doc(definition.get("interface", {})):
        g.bad(f"modules[{asm['id']}]", "the assembly's contract is not the definition's interface")
    if ds.get("shell", {}).get("calls") != asm["id"]:
        g.bad("shell.calls", "the shell must call the assembly")

    reach, todo = set(), [asm["id"]]
    while todo:
        x = todo.pop()
        if x in reach or x not in by_id:
            continue
        reach.add(x)
        todo += by_id[x].get("depends_on", [])
    for mid in by_id:
        if mid not in reach:
            g.bad(f"modules[{mid}]", "cannot be reached from the assembly -- nothing would call it")

    definition_examples = [e for it in definition.get("items", []) for e in it.get("examples", [])]
    ids = [e.get("id") for m in modules for e in m.get("examples", [])]
    _ids_ok(g, ids, "examples")
    for m in modules:
        w = f"modules[{m['id']}]"
        reachable = dict(m.get("functions", {}))
        for dep in m.get("depends_on", []):
            if dep in by_id:
                for fn, sig in by_id[dep].get("functions", {}).items():
                    reachable[f"{by_id[dep]['name']}.{fn}"] = sig
        for ex in m.get("examples", []):
            if not str(ex.get("id", "")).startswith(m["id"] + "."):
                g.bad(w, f"example {ex.get('id')!r} is outside its module")
        exs = m.get("examples", []) + (definition_examples if m is asm else [])
        called = g.examples_ok(exs, reachable, types, errors, fixtures, f"{w}.examples")
        for fn in m.get("functions", {}):
            if fn not in called:
                g.bad(f"{w}.functions.{fn}", "no example calls it")
    return g.findings


def check_files(design_path: Path | str) -> list[Finding]:
    """Both gates, from a design file and the definition it names."""
    design_path = Path(design_path)
    ds = json.loads(design_path.read_text(encoding="utf-8"))
    definition = json.loads((design_path.parent / ds["definition"]).read_text(encoding="utf-8"))
    found = check_definition(definition)
    if found:
        return found          # a design is not checked against a definition that failed
    return check_design(ds, definition)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    findings = check_files(sys.argv[1])
    print("\n".join(map(str, findings)) or "both gates passed")
    sys.exit(1 if findings else 0)
