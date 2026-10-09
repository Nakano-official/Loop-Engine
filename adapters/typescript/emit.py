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
    out = [f"// STUB for {module['id']} ({module['name']}). Generated: the right shape,",
           "// and values no example expects. The solver replaces this file.",
           'import type * as T from "../loop_types";', ""]
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


def run_command(vitest: str, ws: Path, only: str | None = None) -> list[str]:
    """How exec runs a workspace's tests.

    --configLoader native: by default vite bundles the config and writes a
    temporary .timestamp-*.mjs beside it -- in the workspace, which exec may not
    write. The first run in the box stopped there with EACCES. The config
    imports only node builtins, so Node can load it as it is.
    """
    return [vitest, "run", "--root", str(ws), "--configLoader", "native"] + \
        ([f"tests/{only}.test.ts"] if only else [])


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
