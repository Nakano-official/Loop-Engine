"""The TypeScript adapter: a design in, TypeScript types, stubs and tests out.

    build_workspace(design, ws, impls)

    ws/loopcheck.ts              the comparison function (copied)
    ws/loop_types.ts             records (readonly interfaces), enums (string
                                 unions), errors (Error subclasses), generated
    ws/examples.json             LOOP_EXAMPLES
    ws/vitest.config.mjs         generated
    ws/app/<module>.ts           the implementation if `impls` has one, else a stub
    ws/tests/<module>.test.ts    one test per example, generated

Same rules as the Python adapter, and the same language-neutral core
(adapters/design.py): a test is a transcription of one example, a stub returns
the same sentinels, and the verdict is the record.

Names stay as the design writes them -- fields, functions and modules alike --
so the canonical form needs no translation back. A name that is a reserved
word in TypeScript gets a trailing underscore where it is an identifier.

The tests do not import vitest: the config turns on its globals, so a
workspace needs no node_modules of its own and the frozen toolchain
(/srv/loop/node) runs it from outside. Test files run one at a time, because
they all append to one record.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from design import Design, is_ref, parse_type  # noqa: E402

HERE = Path(__file__).resolve().parent

RESERVED = set("""break case catch class const continue debugger default delete do else
enum export extends false finally for function if import in instanceof new null return
super switch this throw true try typeof var void while with as implements interface let
package private protected public static yield await""".split())


def tsname(name: str) -> str:
    return name + "_" if name in RESERVED else name


def annotation(t: tuple) -> str:
    kind = t[0]
    if kind == "prim":
        return {"int": "number", "float": "number", "string": "string", "bool": "boolean"}[t[1]]
    if kind == "list":
        return f"ReadonlyArray<{annotation(t[1])}>"
    if kind == "map":
        return f"Readonly<Record<string, {annotation(t[1])}>>"
    if kind == "optional":
        return f"{annotation(t[1])} | null"
    return f"T.{t[1]}"


# ---- types ---------------------------------------------------------------

def emit_types(d: Design) -> str:
    out = ["// Generated from the design. Do not edit: the window regenerates it.", ""]
    enums, records = [], []
    for name, decl in d.types.items():
        if "enum" in decl:
            enums.append(name)
            out += [f"export type {name} = " + " | ".join(json.dumps(v) for v in decl["enum"]) + ";", ""]
        else:
            records.append(name)
            out.append(f"export interface {name} {{")
            for f in decl["record"]:
                ann = annotation(parse_type(f["type"])).replace("T.", "")
                out.append(f"  readonly {json.dumps(f['name'])}: {ann};")
            out += ["}", ""]
    for name, text in d.errors.items():
        out += [f"/** {text} */",
                f"export class {name} extends Error {{",
                f"  constructor(message?: string) {{ super(message); this.name = {json.dumps(name)}; }}",
                "}", ""]
    rec = {n: [[f["name"], f["type"]] for f in d.types[n]["record"]] for n in records}
    out += [f"export const RECORDS: Record<string, [string, string][]> = {json.dumps(rec)};",
            f"export const ENUMS: string[] = {json.dumps(enums)};", ""]
    return "\n".join(out)


# ---- stubs ---------------------------------------------------------------

class Sentinels:
    def __init__(self, d: Design):
        self.d = d
        self.s = d.sentinels()

    def expr(self, t: tuple) -> str:
        kind = t[0]
        if kind == "prim":
            if t[1] in ("int", "float"):
                return repr(self.s[t[1]])
            # bool: every bool is the right answer to something, so a string.
            lit = json.dumps(self.s["string"])
            return lit if t[1] == "string" else f"({lit} as unknown as boolean)"
        if kind == "optional":
            return self.expr(t[1])
        if kind == "list":
            return f"[{self.expr(t[1])}]"
        if kind == "map":
            return f"{{{json.dumps(self.s['string'])}: {self.expr(t[1])}}}"
        decl = self.d.types[t[1]]
        if "enum" in decl:
            unused = self.s["unused_enum"][t[1]]
            lit = json.dumps(unused[0] if unused else self.s["string"])
            return f"({lit} as unknown as T.{t[1]})"
        fields = ", ".join(f"{json.dumps(f['name'])}: {self.expr(parse_type(f['type']))}"
                           for f in decl["record"])
        return f"({{{fields}}} as T.{t[1]})"


def signature(sig: dict) -> str:
    params = ", ".join(f"{tsname(p['name'])}: {annotation(parse_type(p['type']))}"
                       for p in sig["params"])
    return f"({params}): {annotation(parse_type(sig['returns']))}"


def emit_stub(d: Design, module: dict) -> str:
    s = Sentinels(d)
    # A value import, not `import type`. The stub needs only the types, but the
    # solver starts from this file and keeps its first line: with `import type`
    # the import is erased at run time, and `throw new T.NegativeAmount()` in an
    # otherwise correct implementation dies with ReferenceError. That happened
    # on the first run with the real solver (2026-10-10): format.ts went red on
    # M3.E6 three times and the loop sent the design back for granularity --
    # the engine's mistake, reported as the design's.
    out = [f"// STUB for {module['id']} ({module['name']}). Generated: the right shape,",
           "// and values no example expects. The solver replaces this file.",
           'import * as T from "../loop_types";', ""]
    for fn, sig in module["functions"].items():
        out += [f"export function {tsname(fn)}{signature(sig)} {{",
                f"  return {s.expr(parse_type(sig['returns']))};", "}", ""]
    return "\n".join(out)


# ---- tests ---------------------------------------------------------------

def emit_tests(d: Design, module: dict) -> str:
    modules = {module["name"]} | {d.modules[m]["name"] for m in module["depends_on"]}
    out = [f"// Tests for {module['id']} ({module['name']}), generated from the design.",
           "// One test per example. Expected values are read from LOOP_EXAMPLES.",
           'import * as L from "../loopcheck";',
           'import * as T from "../loop_types";']
    out += [f'import * as m_{n} from "../app/{n}";' for n in sorted(modules)]
    out += ["", "L.useTypes(T);", ""]
    for ex in d.examples(module):
        body = [f"  const ex = L.start({json.dumps(ex['id'])});"]
        steps = ex["steps"]
        for i, st in enumerate(steps):
            last = i == len(steps) - 1
            if "value" in st:
                body.append(f"  const {tsname(st['let'])} = L.arg(ex, {i});")
                continue
            target, fn, sig = d.resolve(module, st["call"])
            args = []
            for p in sig["params"]:
                v = st["args"][p["name"]]
                if is_ref(v) and v["$"] not in d.fixtures:
                    args.append(tsname(v["$"]))
                else:
                    args.append(f"L.arg(ex, {i}, {json.dumps(p['name'])})")
            call = f"m_{target['name']}.{tsname(fn)}({', '.join(args)})"
            if last and "raises" in ex["then"]:
                body.append(f"  L.checkRaises(ex, () => {call});")
            else:
                body.append(f"  const {tsname(st['let'])} = {call};")
        if "raises" not in ex["then"]:
            observed = ", ".join(tsname(o) for o in ex["then"]["observe"])
            body.append(f"  L.check(ex, {observed});")
        out += [f"test({json.dumps(ex['id'])}, () => {{"] + body + ["});", ""]
    return "\n".join(out)


VITEST_CONFIG = """\
// Generated. vitest's globals are on, so the tests import nothing from vitest
// and the workspace needs no node_modules of its own. One file at a time:
// every test appends to the same record. The cache goes to the temp
// directory, because exec cannot write the workspace.
import { tmpdir } from "node:os";
import { join } from "node:path";

export default {
  cacheDir: join(tmpdir(), "loop-vite-cache"),
  test: {
    globals: true,
    environment: "node",
    include: ["tests/**/*.test.ts"],
    fileParallelism: false,
  },
};
"""


EXTENSION = ".ts"


def run_command(vitest: str, ws: Path, modules: list[str] | str | None = None) -> list[str]:
    """How exec runs a workspace's tests: all of them, or those of `modules`.

    --configLoader native: by default vite bundles the config and writes a
    temporary .timestamp-*.mjs beside it -- in the workspace, which exec may not
    write. The first run in the box stopped there with EACCES. The config
    imports only node builtins, so Node can load it as it is.
    """
    if isinstance(modules, str):
        modules = [modules]
    return [vitest, "run", "--root", str(ws), "--configLoader", "native"] + \
        [f"tests/{m}.test.ts" for m in modules or []]


def references_command(tools: dict, path: Path) -> list[str]:
    """How the window reads what one module file reaches for (refs.mjs): with
    node and the parser rolldown carries in the frozen toolchain."""
    parser = Path(tools["node_modules"]) / "rolldown" / "dist" / "parse-ast-index.mjs"
    return [tools["node"], str(HERE / "refs.mjs"), str(path), str(parser)]


def condition_command(tools: dict, path: Path) -> list[str]:
    """How the window reads one condition (FORMATS 4, "holds"): refs.mjs on a
    file that is `export default (<source>);`, parsed, never run."""
    return references_command(tools, path) + ["condition"]


def condition_file(source: str) -> str:
    return f"export default (\n{source}\n);\n"


def check_condition(facts: dict, arity: int) -> str | None:
    """refs.mjs's report on one condition: what is wrong with it, or None."""
    if "error" in facts:
        return f"does not parse: {facts['error']}"
    if facts.get("function") is None:
        return "is not one JavaScript function (write `(a, b) => ...`, and nothing around it)"
    if facts["function"]["params"] != arity:
        return f"takes {facts['function']['params']} parameters; the example observes {arity} values"
    if facts.get("imports") or facts.get("forbidden"):
        used = sorted(set(facts.get("forbidden", [])) | {f"import {i}" for i in facts.get("imports", [])})
        return (f"uses {', '.join(used)}: a condition may use only the language's tools for computing "
                "(Math, JSON, Number, String, Array, Object, Map, Set, ...)")
    return None


def strip_imports(text: str, specifiers: list[str]) -> str | None:
    """The file without its import lines of `specifiers` -- each a whole line
    of its own, `import ... from "<spec>";`. None when one of them is not a
    line like that: then nothing is taken out, and the file is refused as it
    stands."""
    lines = text.split("\n")
    out, left = [], set(specifiers)
    for line in lines:
        m = re.fullmatch(r"\s*import\s[^;'\"]*from\s*(['\"])([^'\"]+)\1\s*;?\s*", line)
        if m and m.group(2) in left:
            left.discard(m.group(2))
            continue
        out.append(line)
    return None if left else "\n".join(out)


def check_references(d: Design, module: dict, facts: dict) -> dict:
    """refs.mjs's report against the design: a module may import the types and
    the modules it depends on, through the paths the brief gives it."""
    allowed = {"../loop_types"} | {f"./{d.modules[m]['name']}" for m in module["depends_on"]}

    def bare(spec: str) -> str:
        for ext in (".ts", ".js", ".mjs"):
            if spec.endswith(ext):
                return spec[: -len(ext)]
        return spec

    return {"undeclared": sorted({s for s in facts.get("imports", []) if bare(s) not in allowed}),
            "forbidden": sorted(facts.get("forbidden", [])),
            "unused": sorted(facts.get("unused", []))}


def build_workspace(d: Design, ws: Path, impls: dict[str, str] | None = None) -> None:
    impls = impls or {}
    ws = Path(ws)
    (ws / "app").mkdir(parents=True, exist_ok=True)
    (ws / "tests").mkdir(exist_ok=True)
    shutil.copyfile(HERE / "loopcheck.ts", ws / "loopcheck.ts")
    (ws / "loop_types.ts").write_text(emit_types(d), encoding="utf-8")
    (ws / "examples.json").write_text(json.dumps(d.examples_file(), ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    (ws / "vitest.config.mjs").write_text(VITEST_CONFIG, encoding="utf-8")
    for module in d.order():
        name = module["name"]
        (ws / "app" / f"{name}.ts").write_text(impls.get(name) or emit_stub(d, module), encoding="utf-8")
        (ws / "tests" / f"{name}.test.ts").write_text(emit_tests(d, module), encoding="utf-8")


# ---- what the implementer is told ------------------------------------------

def implementation_guide(d: Design, module: dict) -> str:
    """The language-specific half of an implementation brief: how to write
    this module's one file so the generated tests can import and call it."""
    name = module["name"]
    deps = [d.modules[m]["name"] for m in module["depends_on"]]
    lines = [
        f"Write the TypeScript module `app/{name}.ts`.",
        "",
        '- Import the design\'s types with `import * as T from "../loop_types";`.',
        "  Every value you are given is frozen: build new objects (spread syntax),",
        "  never assign to a property of an argument.",
        "- Throw the design's errors as `throw new T.<ErrorName>(...)`.",
        "- Export every function of the contract by exactly its name.",
    ]
    if deps:
        lines.append("- Call the modules you depend on through these imports, and nothing else:")
        lines += [f'    import * as m_{dep} from "./{dep}";' for dep in deps]
    else:
        lines.append("- You depend on no other module of the design.")
    lines += ["- Import nothing else.",
              "- Use only the language's tools for computing: Math, JSON, Number, String, Boolean,",
              "  Array, Object, Map, Set and the Error classes. Everything that changes from call",
              "  to call -- the time, randomness -- comes in through your parameters: Date,",
              "  Math.random, console, fetch, document, window, timers and import() are refused.",
              "",
              "The generated types (loop_types.ts):", "```ts", emit_types(d), "```"]
    for dep in deps:
        lines += ["", f"The contract of `{dep}` (signatures only):", "```ts",
                  emit_stub(d, d.by_name[dep]), "```"]
    return "\n".join(lines)
