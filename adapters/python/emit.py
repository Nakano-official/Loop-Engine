"""The Python adapter: a design in, Python types, stubs and tests out.

    build_workspace(design, ws, impls)

writes a workspace the window can hand to exec:

    ws/loopcheck.py            the comparison function (copied)
    ws/loop_types.py           records, enums and errors, generated
    ws/examples.json           LOOP_EXAMPLES: every example, annotated
    ws/app/__init__.py
    ws/app/<module>.py         the implementation if `impls` has one, else a stub
    ws/tests/test_<module>.py  one test per example, generated

Nothing here makes a judgement. A test is a transcription of an example: build
each argument from the example, call, compare once. A stub has the contract's
shape and returns values built only from sentinels no expected value contains
(DESIGN 5), so every example that observes a result fails against it with a
clean assertion rather than an error.

Modules live in the package `app` so that a design's module name can never
shadow the standard library (a module called `json` or `random` would). Tests
import them as `m_<name>`, so a module called `format` does not shadow the
builtin in the test either.
"""
from __future__ import annotations

import json
import keyword
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from design import Design, is_ref, parse_type  # noqa: E402

HERE = Path(__file__).resolve().parent


def pyname(name: str) -> str:
    return name + "_" if keyword.iskeyword(name) else name


def classname(name: str) -> str:
    return name  # design type and error names are already CapWords


def annotation(t: tuple) -> str:
    kind = t[0]
    if kind == "prim":
        return {"int": "int", "float": "float", "string": "str", "bool": "bool"}[t[1]]
    if kind == "list":
        return f"list[{annotation(t[1])}]"
    if kind == "map":
        return f"dict[str, {annotation(t[1])}]"
    if kind == "optional":
        return f"{annotation(t[1])} | None"
    return f"loop_types.{classname(t[1])}"


# ---- types ---------------------------------------------------------------

def emit_types(d: Design) -> str:
    out = ['"""Generated from the design. Do not edit: the window regenerates it."""',
           "from __future__ import annotations", "",
           "import dataclasses", "import enum", "import keyword", "", "",
           "def pyname(name: str) -> str:",
           "    return name + '_' if keyword.iskeyword(name) else name", "", ""]
    records, enums = [], []
    for name, decl in d.types.items():
        if "enum" in decl:
            enums.append(name)
            out.append(f"class {classname(name)}(enum.Enum):")
            for v in decl["enum"]:
                out.append(f"    {pyname(v).upper()} = {v!r}")
            out += ["", ""]
    for name, decl in d.types.items():
        if "record" not in decl:
            continue
        records.append(name)
        # frozen: v1 has no in-place change (FORMATS 2). A state is replaced,
        # never edited, and an example that observes an input after a call
        # (to show it was left alone) holds by construction.
        out += ["@dataclasses.dataclass(frozen=True)", f"class {classname(name)}:"]
        for f in decl["record"]:
            ann = annotation(parse_type(f["type"])).replace("loop_types.", "")
            meta = f" = dataclasses.field(metadata={{'design': {f['name']!r}}})" \
                if pyname(f["name"]) != f["name"] else ""
            out.append(f"    {pyname(f['name'])}: {ann!r}{meta}" if meta else
                       f"    {pyname(f['name'])}: {ann!r}")
        out += ["", ""]
    for name, text in d.errors.items():
        out += [f"class {classname(name)}(Exception):", f"    \"\"\"{text}\"\"\"", "", ""]
    out.append("RECORDS = {")
    for name in records:
        fields = [(f["name"], f["type"]) for f in d.types[name]["record"]]
        out.append(f"    {name!r}: ({classname(name)}, {fields!r}),")
    out += ["}", "ENUMS = {" + ", ".join(f"{n!r}: {classname(n)}" for n in enums) + "}", ""]
    return "\n".join(out)


# ---- stubs ---------------------------------------------------------------

class Sentinels:
    """Values no expected value in the design contains (Design.leaves)."""

    def __init__(self, d: Design):
        self.d = d
        s = d.sentinels()
        self.number, self.integer, self.string = s["float"], s["int"], s["string"]
        self.unused_enum = s["unused_enum"]

    def expr(self, t: tuple) -> str:
        kind = t[0]
        if kind == "prim":
            if t[1] == "int":
                return repr(self.integer)
            if t[1] == "float":
                return repr(self.number)
            # string, and bool: every bool is the right answer to something,
            # so a bool is answered with a string, which equals no bool.
            return repr(self.string)
        if kind == "optional":
            return self.expr(t[1])
        if kind == "list":
            return f"[{self.expr(t[1])}]"
        if kind == "map":
            return f"{{{self.string!r}: {self.expr(t[1])}}}"
        decl = self.d.types[t[1]]
        if "enum" in decl:
            unused = self.unused_enum[t[1]]
            return f"loop_types.{classname(t[1])}({unused[0]!r})" if unused else repr(self.string)
        args = ", ".join(f"{pyname(f['name'])}={self.expr(parse_type(f['type']))}"
                         for f in decl["record"])
        return f"loop_types.{classname(t[1])}({args})"


def signature(sig: dict) -> str:
    params = ", ".join(f"{pyname(p['name'])}: {annotation(parse_type(p['type']))!r}"
                       for p in sig["params"])
    return f"({params}) -> {annotation(parse_type(sig['returns']))!r}"


def emit_stub(d: Design, module: dict) -> str:
    s = Sentinels(d)
    out = [f'"""STUB for {module["id"]} ({module["name"]}). Generated: the right shape,',
           '   and values no example expects. The solver replaces this file."""',
           "from __future__ import annotations", "", "import loop_types", "", ""]
    for fn, sig in module["functions"].items():
        out += [f"def {pyname(fn)}{signature(sig)}:",
                f"    return {s.expr(parse_type(sig['returns']))}", "", ""]
    return "\n".join(out).rstrip() + "\n"


# ---- tests ---------------------------------------------------------------

def emit_tests(d: Design, module: dict) -> str:
    modules = {module["name"]} | {d.modules[m]["name"] for m in module["depends_on"]}
    out = [f'"""Tests for {module["id"]} ({module["name"]}), generated from the design.',
           '   One test per example. Expected values are read from LOOP_EXAMPLES."""',
           "import loop_types", "import loopcheck"]
    out += [f"from app import {n} as m_{n}" for n in sorted(modules)]
    out += ["", "loopcheck.use_types(loop_types)", "", ""]
    for ex in d.examples(module):
        test = "test_" + ex["id"].replace(".", "_")
        body = [f"    ex = loopcheck.start({ex['id']!r})"]
        steps = ex["steps"]
        for i, st in enumerate(steps):
            last = i == len(steps) - 1
            if "value" in st:
                body.append(f"    {pyname(st['let'])} = loopcheck.arg(ex, {i})")
                continue
            target, fn, sig = d.resolve(module, st["call"])
            args = []
            for p in sig["params"]:
                v = st["args"][p["name"]]
                if is_ref(v) and v["$"] not in d.fixtures:
                    args.append(f"{pyname(p['name'])}={pyname(v['$'])}")
                else:
                    args.append(f"{pyname(p['name'])}=loopcheck.arg(ex, {i}, {p['name']!r})")
            call = f"m_{target['name']}.{pyname(fn)}({', '.join(args)})"
            if last and "raises" in ex["then"]:
                body.append(f"    loopcheck.check_raises(ex, lambda: {call})")
            else:
                body.append(f"    {pyname(st['let'])} = {call}")
        if "raises" not in ex["then"]:
            observed = ", ".join(pyname(o) for o in ex["then"]["observe"])
            body.append(f"    loopcheck.check(ex, {observed})")
        out += [f"def {test}():"] + body + ["", ""]
    return "\n".join(out).rstrip() + "\n"


# ---- running ---------------------------------------------------------------

def run_command(python: str, ws: Path, modules: list[str] | None = None) -> list[str]:
    """How exec runs a workspace's tests: all of them, or those of `modules`."""
    targets = [f"tests/test_{m}.py" for m in modules] if modules else ["tests"]
    return [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets]


EXTENSION = ".py"


# ---- the workspace -------------------------------------------------------

def references_command(tools: dict, path: Path) -> list[str]:
    """How the window reads what one module file reaches for (refs.py)."""
    return [tools["python"], str(HERE / "refs.py"), str(path)]


def check_references(d: Design, module: dict, facts: dict) -> dict:
    """refs.py's report against the design: a module may import the types and
    the modules it depends on."""
    allowed = {"loop_types"} | {f"app.{d.modules[m]['name']}" for m in module["depends_on"]}
    return {"undeclared": sorted({s for s in facts.get("imports", []) if s not in allowed}),
            "forbidden": sorted(facts.get("forbidden", []))}


def build_workspace(d: Design, ws: Path, impls: dict[str, str] | None = None) -> None:
    """impls: module name -> source. Modules without one get their stub."""
    impls = impls or {}
    ws = Path(ws)
    (ws / "app").mkdir(parents=True, exist_ok=True)
    (ws / "tests").mkdir(exist_ok=True)
    shutil.copyfile(HERE / "loopcheck.py", ws / "loopcheck.py")
    (ws / "loop_types.py").write_text(emit_types(d), encoding="utf-8")
    (ws / "examples.json").write_text(json.dumps(d.examples_file(), ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    (ws / "app" / "__init__.py").write_text("", encoding="utf-8")
    for module in d.order():
        name = module["name"]
        (ws / "app" / f"{name}.py").write_text(impls.get(name) or emit_stub(d, module), encoding="utf-8")
        (ws / "tests" / f"test_{name}.py").write_text(emit_tests(d, module), encoding="utf-8")


# ---- what the implementer is told ------------------------------------------

def implementation_guide(d: Design, module: dict) -> str:
    """The language-specific half of an implementation brief: how to write
    this module's one file so the generated tests can import and call it."""
    name = module["name"]
    deps = [d.modules[m]["name"] for m in module["depends_on"]]
    lines = [
        f"Write the Python module `app/{name}.py`.",
        "",
        "- Import the design's types with `import loop_types`. Records are frozen dataclasses:",
        "  build them with keyword arguments, and make a changed copy with",
        "  `dataclasses.replace(...)`. Never modify a value you were given.",
        "- Raise the design's errors as `raise loop_types.<ErrorName>(...)`.",
    ]
    if deps:
        lines.append("- Call the modules you depend on through these imports, and nothing else:")
        lines += [f"    from app import {dep} as m_{dep}" for dep in deps]
    else:
        lines.append("- You depend on no other module of the design.")
    lines += ["- Besides these, import only standard library modules that compute: math, json,",
              "  dataclasses, typing, enum, functools, itertools, collections, decimal, fractions,",
              "  operator, re, string, copy, bisect, heapq, statistics. Everything that changes from",
              "  call to call -- the time, randomness -- comes in through your parameters: time,",
              "  datetime, random, os, open, print and input are refused.",
              "",
              "The generated types (loop_types.py):", "```python", emit_types(d), "```"]
    for dep in deps:
        lines += ["", f"The contract of `{dep}` (signatures only):", "```python",
                  emit_stub(d, d.by_name[dep]), "```"]
    return "\n".join(lines)
