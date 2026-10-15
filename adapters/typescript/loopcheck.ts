// The comparison function for TypeScript (DESIGN 5, FORMATS 10).
//
// The same contract as adapters/python/loopcheck.py, in the same words:
//
//   const ex = start("M2.E1");                  // record START, load the example
//   const p = m_economy.current_cost(...);      // the call, built from the example
//   check(ex, p);                               // compare once, record CHECK
//
// or, for an example that expects an error:
//
//   checkRaises(ex, () => m_economy.production_rate(...));
//
// Expected values are read from LOOP_EXAMPLES, inputs are built from it with
// arg(); nothing is written into a test. The verdict is the record: one JSON
// object per line in $LOOP_RECORD_DIR/records.jsonl, written synchronously, so
// a test that crashes after START leaves exactly that behind.
//
// Values built here are deep-frozen. v1 has no in-place change (FORMATS 2), and
// ES modules run in strict mode, so code that edits a state it was given throws
// at the edit instead of passing an immutability example by luck.

import { appendFileSync, readFileSync } from "node:fs";
import { join } from "node:path";

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export interface Example { id: string; then: any; steps: any[]; tol?: { rel?: number; abs?: number } }

const DEFAULT_REL = 1e-9;
const DEFAULT_ABS = 1e-12;

let examples: Map<string, Example> | null = null;
let fixtures: Record<string, Json> = {};
let types: { RECORDS: Record<string, [string, string][]>; ENUMS: Set<string> } | null = null;

function load(): Map<string, Example> {
  if (examples === null) {
    const data = JSON.parse(readFileSync(process.env.LOOP_EXAMPLES as string, "utf-8"));
    examples = new Map(data.examples.map((e: Example) => [e.id, e]));
    fixtures = Object.fromEntries(
      Object.entries(data.fixtures ?? {}).map(([k, v]: [string, any]) => [k, v.value]));
  }
  return examples;
}

function record(entry: object): void {
  appendFileSync(join(process.env.LOOP_RECORD_DIR ?? ".", "records.jsonl"),
                 JSON.stringify(entry) + "\n", "utf-8");
}

// ---- the canonical form --------------------------------------------------

export function canon(value: unknown): Json {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) return value.map(canon);
  if (typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    return Object.fromEntries(Object.entries(value as object).map(([k, v]) => [k, canon(v)]));
  }
  // A value the comparison cannot see must not compare equal by accident.
  throw new TypeError(`loopcheck: no canonical form for ${Object.prototype.toString.call(value)}`);
}

function resolve(value: any): any {
  if (value !== null && typeof value === "object" && !Array.isArray(value)
      && Object.keys(value).length === 1 && "$" in value) {
    return fixtures[value.$];
  }
  return value;
}

export function equal(e: Json, a: Json, rel = DEFAULT_REL, abs = DEFAULT_ABS): boolean {
  if (typeof e === "boolean" || typeof a === "boolean") return e === a;
  if (typeof e === "number" && typeof a === "number") {
    if (Number.isNaN(e) || Number.isNaN(a)) return Number.isNaN(e) && Number.isNaN(a);
    return Math.abs(e - a) <= Math.max(rel * Math.max(Math.abs(e), Math.abs(a)), abs);
  }
  if (Array.isArray(e) || Array.isArray(a)) {
    return Array.isArray(e) && Array.isArray(a) && e.length === a.length
      && e.every((x, i) => equal(x, a[i], rel, abs));
  }
  if (e !== null && a !== null && typeof e === "object" && typeof a === "object") {
    const ek = Object.keys(e).sort(), ak = Object.keys(a).sort();
    return ek.length === ak.length && ek.every((k, i) => k === ak[i])
      && ek.every(k => equal((e as any)[k], (a as any)[k], rel, abs));
  }
  return e === a;
}

// ---- building inputs -----------------------------------------------------

export function useTypes(module: any): void {
  types = { RECORDS: module.RECORDS, ENUMS: new Set(module.ENUMS) };
}

type Kind = ["prim", string] | ["list" | "optional" | "map", Kind] | ["named", string];

function parse(t: string): Kind {
  t = t.replace(/ /g, "");
  for (const k of ["list", "optional"] as const) {
    if (t.startsWith(k + "<") && t.endsWith(">")) return [k, parse(t.slice(k.length + 1, -1))];
  }
  if (t.startsWith("map<string,") && t.endsWith(">")) return ["map", parse(t.slice(11, -1))];
  return ["int", "float", "string", "bool"].includes(t) ? ["prim", t] : ["named", t];
}

function freeze<T>(v: T): T {
  if (v !== null && typeof v === "object") {
    for (const x of Object.values(v)) freeze(x);
    Object.freeze(v);
  }
  return v;
}

export function decode(value: any, t: string | Kind): any {
  value = resolve(value);
  const k = typeof t === "string" ? parse(t) : t;
  switch (k[0]) {
    case "prim":
      return k[1] === "string" ? String(value) : k[1] === "bool" ? Boolean(value) : Number(value);
    case "optional":
      return value === null ? null : decode(value, k[1]);
    case "list":
      return freeze(value.map((v: any) => decode(v, k[1])));
    case "map":
      return freeze(Object.fromEntries(
        Object.entries(value).map(([key, v]) => [key, decode(v, k[1] as Kind)])));
    case "named": {
      if (types!.ENUMS.has(k[1])) return String(value);
      const fields = types!.RECORDS[k[1]];
      return freeze(Object.fromEntries(fields.map(([f, ft]) => [f, decode(value[f], ft)])));
    }
  }
}

export function arg(ex: Example, step: number, name?: string): any {
  const st = ex.steps[step];
  if (name === undefined) return decode(st.value, st.type);
  return decode(st.args[name], st.arg_types[name]);
}

// ---- what a generated test calls ----------------------------------------

export function start(id: string): Example {
  const ex = load().get(id);
  record({ t: "start", id });
  if (ex === undefined) throw new Error(`loopcheck: no example ${id} in LOOP_EXAMPLES`);
  return ex;
}

// A part of a value (FORMATS 4, "matches"): an object in `e` is compared on
// the fields it has, and the fields it leaves out are not looked at. Lists keep
// their length; everything else is compared as in equal().
export function matches(e: Json, a: Json, rel = DEFAULT_REL, abs = DEFAULT_ABS): boolean {
  if (Array.isArray(e) || Array.isArray(a)) {
    return Array.isArray(e) && Array.isArray(a) && e.length === a.length
      && e.every((x, i) => matches(x, a[i], rel, abs));
  }
  if (e !== null && typeof e === "object") {
    return a !== null && typeof a === "object"
      && Object.keys(e).every(k => k in (a as object) && matches((e as any)[k], (a as any)[k], rel, abs));
  }
  return equal(e, a, rel, abs);
}

// A condition (FORMATS 4, "holds"): JavaScript source of a function that is
// given the observed values, in order, and returns true when they are right.
// It was parsed at the tester's gate (refs.mjs --condition); here it runs. A
// condition that throws, or returns anything but true, is not met -- against a
// stub that is what red looks like.
function holds(source: string, actuals: unknown[]): { ok: boolean; error?: string } {
  try {
    const fn = new Function(`"use strict"; return (${source});`)();
    return { ok: fn(...actuals) === true };
  } catch (e: any) {
    return { ok: false, error: String(e?.message ?? e).slice(0, 300) };
  }
}

export function check(ex: Example, ...actuals: unknown[]): void {
  const then = ex.then;
  const rel = ex.tol?.rel ?? DEFAULT_REL, abs = ex.tol?.abs ?? DEFAULT_ABS;
  const actual = actuals.map(canon);
  let ok: boolean, expected: Json, error: string | undefined;
  if ("equals" in then) {
    expected = then.equals.map((v: any) => canon(resolve(v)));
    ok = equal(expected, actual, rel, abs);
  } else if ("matches" in then) {
    expected = then.matches.map((v: any) => canon(resolve(v)));
    ok = matches(expected, actual, rel, abs);
  } else if ("holds" in then) {
    expected = { holds: then.holds };
    ({ ok, error } = holds(then.holds, actuals));
  } else {
    throw new Error(`${ex.id}: expects an error, use checkRaises`);
  }
  record({ t: "check", id: ex.id, ok, expected, actual, ...(error ? { error } : {}) });
  if (!ok) {
    throw new Error(`${ex.id}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`
                    + (error ? ` (the condition threw: ${error})` : ""));
  }
}

export function checkRaises(ex: Example, call: () => unknown): void {
  const want = ex.then.raises;
  let got: Json;
  try {
    const returned = call();
    try { got = { returned: canon(returned) }; } catch { got = { returned: String(returned) }; }
  } catch (e: any) {
    got = { raises: e?.constructor?.name ?? String(e) };
  }
  const ok = equal({ raises: want }, got);
  record({ t: "check", id: ex.id, ok, expected: { raises: want }, actual: got });
  if (!ok) throw new Error(`${ex.id}: expected ${want} to be raised, got ${JSON.stringify(got)}`);
}
