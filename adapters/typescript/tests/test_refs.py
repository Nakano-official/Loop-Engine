"""Conformance: the reference check (DESIGN 5) in the TypeScript adapter.

refs.mjs parses one module file with the parser rolldown carries and reports
what it imports and which globals it may not use; emit.check_references holds
the imports against the design. The correct idle game and coin room pass
untouched; each way of reaching outside a pure module is refused; types and
the language's own tools for computing are not.

Needs node and the frozen toolchain: LOOP_NODE and LOOP_NODE_MODULES (in the
box: /usr/bin/node and /srv/loop/node/node_modules). Without them these tests
are skipped, not passed.
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

TOOLS = {"node": os.environ.get("LOOP_NODE", ""), "node_modules": os.environ.get("LOOP_NODE_MODULES", "")}
pytestmark = pytest.mark.skipif(not (TOOLS["node"] and TOOLS["node_modules"]),
                                reason="LOOP_NODE and LOOP_NODE_MODULES are not set")

EXAMPLES = HERE.parents[2] / "docs" / "formats" / "examples"
IDLE = emit.Design(EXAMPLES / "idlegame.design.json")
COIN = emit.Design(EXAMPLES / "coinroom.design.json")


def facts(tmp_path: Path, source: str) -> dict:
    f = tmp_path / "m.ts"
    f.write_text(source, encoding="utf-8")
    proc = subprocess.run(emit.references_command(TOOLS, f), capture_output=True, text=True, encoding="utf-8")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def check(tmp_path, design, module, source):
    return emit.check_references(design, design.by_name[module], facts(tmp_path, source))


@pytest.mark.parametrize("design, folder", [(IDLE, "idlegame"), (COIN, "coinroom")])
def test_the_correct_apps_pass(tmp_path, design, folder):
    for p in sorted((HERE / folder).glob("*.ts")):
        found = check(tmp_path, design, p.stem, p.read_text(encoding="utf-8"))
        assert found == {"undeclared": [], "forbidden": []}, (p.name, found)


@pytest.mark.parametrize("source, refused", [
    ('export function f() { return fetch("https://example.com"); }', "fetch"),
    ("export function f() { return document.title; }", "document"),
    ("export function f() { return window.location.href; }", "window"),
    ("export function f() { return globalThis.x; }", "globalThis"),
    ("export function f() { return Date.now(); }", "Date"),
    ("export function f() { return new Date(); }", "Date"),
    ("export function f() { return Math.random(); }", "Math.random"),
    ('export function f() { return Math["random"](); }', "Math.random"),
    ("export function f(k: string) { return (Math as any)[k](); }", "Math[...]"),
    ("const { random } = Math; export function f() { return random(); }", "Math.random"),
    ("export function f() { console.log(1); return 1; }", "console"),
    ("export function f(s: string) { return eval(s); }", "eval"),
    ('export function f() { return Function("return 1")(); }', "Function"),
    ("export function f() { return [].constructor.constructor; }", ".constructor"),
    ('export async function f() { return import("./x"); }', "import()"),
    ("export function f() { setTimeout(() => 0, 1); return 1; }", "setTimeout"),
    ("export function f() { return localStorage.getItem('k'); }", "localStorage"),
    ('import * as THREE from "three"; export const f = () => THREE;', "import three"),
    ('import { readFileSync } from "node:fs"; export const f = () => readFileSync;', "import node:fs"),
])
def test_reaching_outside_is_refused(tmp_path, source, refused):
    assert refused in check(tmp_path, IDLE, "format", source)["forbidden"]


def test_a_module_the_design_does_not_declare_is_refused(tmp_path):
    # format depends on scale only.
    found = check(tmp_path, IDLE, "format", 'import * as m_economy from "./economy";\nexport const f = 1;')
    assert found["undeclared"] == ["./economy"]
    ok = 'import * as T from "../loop_types";\nimport * as m_scale from "./scale.ts";\nexport const f = 1;'
    assert check(tmp_path, IDLE, "format", ok)["undeclared"] == []


def test_types_and_computing_are_allowed(tmp_path):
    source = """
import * as T from "../loop_types";
type Pair = Readonly<Record<string, ReadonlyArray<number>>>;
interface Local { readonly a: Promise<Date>; }
enum Dir { N = 1, S = Math.max(2, 1) }
export function f(xs: ReadonlyArray<number>, now: number): T.GameState {
  const total = xs.reduce((a, b) => a + b, 0);
  const { length } = xs;
  const m = new Map<string, number>([["a", Math.floor(now)]]);
  label: for (const x of xs) { if (x > 1) break label; }
  const o = { total, length, fetch: 1, Date: 2 };
  try { JSON.parse("{}"); } catch (e) { throw new T.CorruptSave(String(e)); }
  return { resource: o.total + Number.parseFloat("1") + Dir.N, owned: Object.fromEntries(m),
           last_update: now } as unknown as T.GameState;
}
"""
    assert check(tmp_path, IDLE, "save", source) == {"undeclared": [], "forbidden": []}


def test_a_file_that_does_not_parse_is_left_to_its_tests(tmp_path):
    assert "error" in facts(tmp_path, "export function f( {")
