"""Briefs for the upstream roles: the analyst, the definer and the designer (DESIGN 2).

    analyze(request, findings)                               -> the analyst's brief
    define(concepts, platform, findings)                     -> the definer's brief
    design_plan(definition, concepts, findings, verdict)     -> the designer's plan
    design_module(design, name, definition, concepts)        -> the designer's brief, one module

A part, not a flow. A brief is all a role sees, so what it says about the
formats is said here, once, and is the same every time: FORMATS.md, shortened
to what a writer needs, plus the platform's own declaration verbatim. What a
role is told after a failure is decided here too -- the gate's findings, or
for the designer the verdict of used-up attempts: which module, which kind of
reason, which example ids. Never what an implementation returned (DESIGN 5).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ROOT / "adapters" / "platforms"
EXAMPLE_DESIGN = ROOT / "docs" / "formats" / "examples" / "idlegame.design.json"

TYPES = """\
Types are written as strings:
  int, float, string, bool
  list<T>            ordered
  map<string,T>      unordered -- use a list whenever order matters
  optional<T>        null or a T
  Name               a type declared under "types": {"record": [{"name": ..., "type": ...}, ...]}
                     (fields in order) or {"enum": ["a", "b"]}
Names: types and errors are CapWords; functions, parameters, fields and module names are
snake_case. There are no classes, no methods, no callbacks, and nothing is changed in place:
a function receives values and returns new values. Time is never read; it is passed in as
`now` (seconds, float)."""

EXAMPLES = """\
An example is data, not code:
  {"id": "D3.E1",
   "steps": [{"let": "s", "call": "start", "args": {"now": 0.0, "saved": null}},
             {"let": "a", "call": "act", "args": {"state": {"$": "s"}, "action": "click", "now": 0.0}}],
   "then": {"observe": ["a"], "equals": [{"resource": 1.0, "owned": {}, "last_update": 0.0}]}}
- steps run in order; "args" names every parameter; {"$": "s"} refers to an earlier step's result
- a step may also bind a literal: {"let": "s", "value": {...}, "type": "GameState"}
- "then" says how the result is judged -- one of:
  {"observe": [names], "equals": [values]}   the whole value, exactly (floats within 1e-9)
  {"observe": [names], "matches": [values]}  a part: a record may leave out fields, and only the
                                             fields written are compared (lists keep their length)
  {"observe": [names], "holds": "(a, b) => ..."}
                                             a condition: JavaScript source of a function that is
                                             given the observed values in order and returns true
                                             when they are right
  {"raises": "ErrorName"}                    the LAST step must throw it, and its function must
                                             declare it in "raises"
- choose the form by what the statement says. equals when exactly one answer is right and it is
  short to write. matches to look at the part the statement is about and nothing else. holds
  when many answers are right (anything generated, a relation between two results, "there is a
  path") or when working the exact answer out would take more than simple arithmetic: say what
  must be true and let the machine judge it
- a condition uses only the language's tools for computing (Math, JSON, Number, String, Array,
  Object, Map, Set); no Date, no Math.random, no I/O. It must return true, not just something
  truthy. Write it as strong as the statement: one that any result meets checks nothing
- the same call on the same input must never expect two different results
- compute every value you compare with the run tool, never in your head, and try each condition
  on the values it must accept and on one it must refuse. Still prefer inputs whose results are
  plain (whole numbers, right angles, short durations), and avoid values that need rounding at
  a tie (x.xx5) -- languages differ"""


def _writing(name: str, skeleton: str, part: str) -> list[str]:
    """How to write the file (DECISIONS 45): in parts, computing with the run
    tool. One response has a limited length: a designer that composed a
    whole design in its head before writing anything was cut off twice at
    about 64k tokens of thinking, and had written nothing (2026-10-15)."""
    return [
        "# How to write it",
        f"- Write `{name}` in parts. First Write a skeleton: {skeleton}. Then fill it in with Edit,",
        f"  {part} per Edit, until it is complete. Do not compose the whole file before writing",
        "  anything: one response has a limited length, and a long one is cut off unwritten. Keep",
        "  the file valid JSON after every Edit",
        "- You have a `run` tool: it runs a short Python or JavaScript program in a sandbox and",
        "  returns what it printed. Use it for every number you have to work out -- arithmetic,",
        "  geometry, a layout -- instead of working it out by hand",
    ]


def _platform(name: str) -> dict:
    return json.loads((PLATFORMS / name / "platform.json").read_text(encoding="utf-8"))


def _findings(findings: list[str], what: str) -> list[str]:
    if not findings:
        return []
    return ["", f"# Your previous {what} was refused by the gate",
            "Fix every one of these and keep everything else:"] + [f"- {f}" for f in findings]


# The shape of a concept file, from a domain no app here is about: an example
# from the app being built would hand the analyst its own answer.
CONCEPTS_SHAPE = """\
{"format": "loop/concepts@1",
 "request": "(filled in by the machine: the request, verbatim)",
 "background": "(optional, free text: context the request gives about the person or the situation)",
 "concepts": [
  {"id": "C1", "name": "家計の支出", "kind": "thing", "status": "active",
   "source": "毎月なににいくら使ったか分からない",
   "meaning": "ある日に、ある目的で、ある金額を払ったという記録の集まり。日付・金額・使い道を持つ",
   "properties": [
    {"id": "C1.P1", "text": "同じ月の支出を合計すると、その月に使った金額になる", "check": "example"},
    {"id": "C1.P2", "text": "使い道ごとに分けて合計できる", "check": "example"}],
   "not": ["金額だけで日付の無い記録は支出の記録ではない"]},
  {"id": "C2", "name": "迷わず記録できる", "kind": "quality", "status": "active",
   "source": "（共通の質の概念: アプリは説明なしで開かれる）",
   "meaning": "開いた人が、説明を読まずに、支出を一件記録するところまで進める",
   "properties": [
    {"id": "C2.P1", "text": "最初の画面で、何を入力すればよいかが分かる", "check": "evaluation"}],
   "not": ["最初の画面に入力する場所が無い"]}],
 "requirements": [
  {"id": "R1", "text": "月ごとに、いくら使ったかが分かる", "status": "active",
   "source": "毎月なににいくら使ったか分からない", "reason": "要求にある",
   "check": "example", "concepts": ["C1.P1"]},
  {"id": "R2", "text": "閉じて開き直しても、記録した支出が残っている", "status": "active",
   "source": "implied", "reason": "記録を後で見返すことが目的なので、消えれば意味が無い",
   "check": "example", "concepts": []}],
 "out_of_scope": ["銀行口座との連携", "家族での共有"]}"""


def analyze(request: str, findings: list[str] | None = None) -> str:
    """The analyst's brief (DESIGN 4): what the request's words mean and what
    the person needs to reach their goal -- not what to make. That is the
    definer's, and it is decided against this file."""
    parts = [
        "# Task",
        "You are the analyst. Read the request below, written by a person, and write the CONCEPT",
        "FILE: what the words of the request mean, and what the person needs in order to reach",
        "what they are after. You do NOT decide what to make -- a definer decides that later, and",
        "is held to this file. Everyone downstream reads your file and nothing else of the request.",
        "",
        "Write exactly one file, `concepts.json`, in the current directory. Nothing else.",
        "Write every text in Japanese.",
        "",
        *_writing("concepts.json", "format and request, every concept with its id, name and kind, every "
                  "requirement with its id and text, and the rest empty", "a few concepts or requirements"),
        "",
        "# The request",
        request.strip(),
        "",
        "# What to write",
        "- concepts: each word or idea of the request that carries meaning. kind \"thing\" for what",
        "  the request is about, \"quality\" for how it must feel to the person using it. For each:",
        "  - source: the request's own words it comes from, quoted exactly",
        "  - meaning: what it is made of and what it is, in full -- assume the reader does not know",
        "    the word. A downstream model will take the easiest reading it can; write down what",
        "    makes the concept what it is, so the easy reading is visibly wrong",
        "  - the request's own specifications (sizes, keys, colours, positions) are NOT the",
        "    meaning of its words. For the thing the request is about, write what anyone means by",
        "    that word even where the request does not say it -- what makes it that thing and not",
        "    a lesser one -- as properties and counter-examples. A request may fix the details and",
        "    still rely on the word for everything else: record the details too, never instead",
        "  - properties: what must always hold of it, each checkable, ONE thing per property.",
        "    check \"example\" when a concrete input and its expected result could show it -- every",
        "    property about structure, arrangement, connections, counts or rules is one, however",
        "    hard it seems to state. \"evaluation\" only for what using the finished thing alone",
        "    can show: how it looks, whether it is clear, how it feels",
        "  - not: counter-examples -- what is NOT this concept, above all the shrunken forms a",
        "    careless reading would produce",
        "- requirements: what the person needs in order to reach their goal. Write each as a STATE",
        "  the person wants to be in (\"月ごとにいくら使ったかが分かる\"), never as a feature, screen or",
        "  button -- choosing those is the definer's job. source is the request's words, or",
        "  \"implied\" for something the request does not say but plainly needs; an implied one",
        "  needs its reason. Never invent what the person wants beyond what the request supports",
        "- whatever the request specifies is binding: record it, never change or contradict it",
        "- out_of_scope: what will not be made, so improvement does not spread without end",
        "- background is optional free text. Leave it out unless the request gives context",
        "- ids: concepts C<n>, properties C<n>.P<m>, requirements R<n>. Every text stands on its",
        "  own: never refer to another entry by its id inside a sentence; references go only in",
        "  the \"concepts\" field of a requirement",
        "",
        "# The format of concepts.json (an example from another domain, for the shape only)",
        CONCEPTS_SHAPE,
    ]
    parts += _findings(findings or [], "concept file")
    return "\n".join(parts) + "\n"


def _signatures(plat: dict, state: str = "$State") -> str:
    return "\n".join(f"  {fn}({', '.join(p['name'] + ': ' + p['type'].replace('$State', state) for p in s['params'])})"
                     f" -> {s['returns'].replace('$State', state)}"
                     for fn, s in plat["interface"].items())


def define(concepts: dict, platform: str = "browser-dom", findings: list[str] | None = None) -> str:
    """The definer's brief (DECISIONS 44): what to make, item by item, and
    nothing that is not a decision -- the platform's part is the machine's,
    the examples are the designer's (DECISIONS 48)."""
    plat = _platform(platform)
    parts = [
        "# Task",
        "You are the definer. Read the concept file below -- what a person asked for, what their",
        "words mean, and what they need -- and decide WHAT TO MAKE to meet those needs. Write it as",
        "the DEFINITION of the app: what it is, what it remembers (its state), and item by item what",
        "must hold of it. That is all you write. The machine adds the platform's types and",
        "functions; the designer writes the examples each item is checked by, from your statements",
        "alone; a designer turns it into modules later. Do not write examples, functions or modules.",
        "",
        "Write exactly one file, `definition.json`, in the current directory. Nothing else.",
        "Write the summary, titles, statements and any text shown to the user in Japanese.",
        "",
        *_writing("definition.json", "title, summary, state, types, errors, raises, and every item with its "
                  "id and title and an empty statement", "a few items or types"),
        "",
        "# The concept file",
        "It binds you. Do not narrow a concept to whatever is easiest to make: its meaning,",
        "properties and counter-examples (\"not\") say what it must be, and an app a counter-example",
        "describes is wrong. Whatever the request specifies stays as specified.",
        json.dumps(concepts, ensure_ascii=False, indent=1),
        "",
        "# What the definition must cover",
        "- \"summary\": in a sentence or two, what you make and for what",
        "- every property and requirement whose check is \"example\" is listed in the \"concepts\"",
        "  field of at least one item, and that item's statement says what makes it true. The",
        "  examples can check only what the statement says",
        "- \"evaluation\" ones are checked later by using the app; list them where they apply",
        "- every item lists at least one property or requirement it answers to",
        "",
        "# Items",
        "- a statement says what must hold of the app, in terms of what it can be shown to do:",
        "  what start gives, what an action does to the state, what the screen shows, what is",
        "  always true. Not how it is built",
        "- say it so exactly that someone who has not read the concept file could write the checks:",
        "  which action, from which state, with what result. Where several answers are right (a",
        "  generated layout, a random choice), say what every right answer has in common",
        "- one item per thing that must hold. Every text stands on its own: no ids inside sentences",
        "",
        f"# The platform: {platform}",
        "How the app is delivered is fixed: one HTML file, drawn by a generic shell. Ignore any",
        "need for servers, build steps or files -- the platform decides those. The shell calls",
        "exactly these functions, which the machine adds to the definition ($State is the record",
        "type you name under \"state\": the app's whole state):",
        _signatures(plat),
        *["- " + line for line in plat["brief"]],
        "The platform's own types, which the machine adds too (use them, do not declare them):",
        json.dumps(plat["types"], ensure_ascii=False, indent=1),
        *(["Conventions:"] + plat["conventions"] if plat.get("conventions") else []),
        "",
        "# The format of definition.json",
        """{"format": "loop/definition@1",
 "title": "<the app's name, Japanese>",
 "summary": "<what is made, and for what -- a sentence or two, Japanese>",
 "state": "<the name of the record type that is the app's whole state>",
 "types": {<that record>, <any other type of your own>},
 "errors": {"ErrorName": "<what it means>", ...},                (optional)
 "raises": {"act": ["ErrorName", ...], ...},                       (optional: which platform function throws which)
 "items": [{"id": "D1", "title": "<Japanese>", "statement": "<what must hold, Japanese>",
            "concepts": ["C1.P1", "R2", ...]}, ...]}""",
        "",
        TYPES,
    ]
    parts += _findings(findings or [], "definition")
    return "\n".join(parts) + "\n"


def _answers(concepts: dict) -> dict:
    """Every property and requirement, by id: its text, its check, and for a
    property the concept it belongs to (name and counter-examples)."""
    out = {}
    for k in concepts.get("concepts", []):
        for p in k.get("properties", []):
            out[p["id"]] = {"text": p.get("text"), "check": p.get("check"),
                            "concept": k.get("name"), "not": k.get("not", [])}
    for r in concepts.get("requirements", []):
        out[r["id"]] = {"text": r.get("text"), "check": r.get("check")}
    return out


# When the implementation sends the loop back, the designer changes the plan
# it has, where the verdict points, instead of writing one again (DECISIONS
# 46): the modules whose entry it leaves alone keep their docs, examples and
# implementation.
REDESIGN = [
    "# How to write it",
    "- Your previous plan is in this directory, at edit/design.json. Do not write a new",
    "  design.json: open edit/design.json and change it with Edit where the verdict at the end",
    "  of this brief points, and nowhere else. What is in edit/design.json when you finish is",
    "  what is read. Keep it valid JSON after every Edit",
    "- You have a `run` tool: it runs a short Python or JavaScript program in a sandbox and",
    "  returns what it printed. Use it for every number you have to work out -- arithmetic,",
    "  geometry, a layout -- instead of working it out by hand",
]


def _run_tool() -> list[str]:
    return ["- You have a `run` tool: it runs a short Python or JavaScript program in a sandbox and",
            "  returns what it printed. Use it for every number you have to work out -- arithmetic,",
            "  geometry, a layout -- instead of working it out by hand"]


def _one_call(name: str) -> list[str]:
    """How a part is written (DECISIONS 47): it is small, so in one go."""
    return ["# How to write it",
            f"- Write `{name}` with Write, in one go, once you know what goes in it. Everything you",
            "  need is in this brief: there is nothing to look up in other files",
            *_run_tool()]


def _render(ex: dict) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from briefs import render_example
    return render_example(None, None, ex)


def _items_text(definition: dict, concepts: dict, only: list[str] | None = None) -> list[str]:
    answers = _answers(concepts)
    out = []
    for item in definition.get("items", []):
        if only is not None and item["id"] not in only:
            continue
        out += ["", f"## {item['id']} {item.get('title', '')}", item.get("statement", "")]
        for ref in item.get("concepts", []):
            a = answers.get(ref)
            if not a:
                continue
            how = "examples must show it" if a["check"] == "example" else "checked later by using the app"
            out.append(f"- answers to {ref} ({how}): {a['text']}")
            if a.get("not"):
                out.append(f"  not {a['concept']}: " + " / ".join(a["not"]))
    return out


def _contract(definition: dict) -> str:
    return json.dumps({k: definition[k] for k in ("types", "errors", "interface") if k in definition},
                      ensure_ascii=False, indent=1)


SMALL_VALUES = """\
- build the state an example needs by calling the app's functions (start, act, step) where you
  can. Where you must write a state as a literal value, make it as small as the statement
  allows: a maze of 2 x 2 cells shows a wall as well as one of 10 x 10. Never paste a large value
  you computed: a condition can compute it instead"""


WHO_IMPLEMENTS = [
    "# Who implements it",
    "A small local model (9B parameters) implements ONE module at a time, seeing only that",
    "module's contracts, its docs, its examples, and the contracts of the modules it depends on",
    "with what each of their functions does. It does not see the definition. Design for that reader:",
    "- keep modules small: one to three functions, one idea each. A function with a tricky",
    "  algorithm (a loop, a scale of units, a parser) gets its own module and many examples",
]


def _definition_for_design(definition: dict) -> str:
    """The definition without its examples' contents: the designer plans
    against the contract and the statements; the examples are the
    assembly's tests, run by the machine (DECISIONS 47)."""
    lean = {k: v for k, v in definition.items() if k != "items"}
    lean["items"] = [{k: v for k, v in i.items() if k != "examples"} | {"examples": len(i.get("examples", []))}
                     for i in definition.get("items", [])]
    return json.dumps(lean, ensure_ascii=False, indent=1)


def design_plan(definition: dict, concepts: dict | None = None, findings: list[str] | None = None,
                verdict: dict | None = None, editing: bool = False) -> str:
    """The designer's first call (DECISIONS 47): the PLAN -- the modules, what
    each depends on, their contracts and what each function does in a
    sentence. How each works and its examples come after, one module per call.
    `editing`: the implementation sent the loop back; the plan it had is in
    edit/design.json, to be changed where the verdict points."""
    platform = definition.get("shell", {}).get("platform", "browser-dom")
    parts = [
        "# Task",
        "You are the designer. Turn the definition below into the PLAN of a design: its modules,",
        "what each depends on, the contract of each function, and in one sentence what each does.",
        "How each function works, and its examples, are written next -- one module at a time, from",
        "this plan. Do not write them here.",
        "",
        *(["Change exactly one file, `edit/design.json`. Nothing else.", "", *REDESIGN] if editing else
          ["Write exactly one file, `design.json`, in the current directory. Nothing else.", "",
           *_one_call("design.json")]),
        "",
        *WHO_IMPLEMENTS,
        "- a function's \"doc\" in the plan is ONE sentence: what it does, what it returns",
        "",
        "# The definition (its examples are counted, not shown: they are the assembly's tests)",
        _definition_for_design(definition),
        "",
        *(["# The concept file the definition answers to",
           "What the words mean and what the person needs. A module must not narrow them either.",
           json.dumps(concepts, ensure_ascii=False, indent=1), ""] if concepts else []),
        "# The format of design.json (the plan)",
        """{"format": "loop/design@1",
 "definition": "definition.json",
 "target": {"language": "typescript", "platform": "%s"},
 "types": {<every type of the definition, identical>, <your own>},
 "errors": {<every error of the definition>, <your own>},
 "modules": [{"id": "M1", "name": "snake_case", "kind": "pure" | "assembly",
              "depends_on": ["M2", ...],
              "functions": {"<fn>": {"params": [...], "returns": ..., "raises": [...], "doc": "<what, one sentence>"}},
              "examples": []}, ...],
 "shell": {"calls": "<the assembly's id>"}}""" % platform,
        "- exactly one module has kind \"assembly\". Its functions are the definition's interface",
        "  EXACTLY (same names, parameters, returns, raises). Every other module must be reachable",
        "  from it through depends_on; no cycles",
        "",
        TYPES,
    ]
    if verdict:
        parts += ["", "# The previous design did not work",
                  f"Module `{verdict.get('module')}` could not be implemented in the attempts allowed.",
                  f"Reason: {verdict.get('reason')}",
                  f"Its examples that stayed red: {', '.join(verdict.get('examples', [])) or '(none listed)'}",
                  "Change the plan where that points: split the module (granularity), add a missing",
                  "dependency or move a function (boundary), or change how the assembly composes the",
                  "parts (decomposition). That module is written again in any case, more literally.",
                  "Leave every other module exactly as it is: one whose entry in the plan is unchanged",
                  "keeps its docs, its examples and its implementation. One you touch is written again."]
    parts += _findings(findings or [], "plan")
    return "\n".join(parts) + "\n"


def design_module(design: dict, name: str, definition: dict, concepts: dict | None = None,
                  findings: list[str] | None = None) -> str:
    """The designer's call for ONE module (DECISIONS 47): the plan, this
    module's contract, and what its dependencies do -- and for the assembly,
    the definition's examples it will be tested by, one line each."""
    example = json.loads(EXAMPLE_DESIGN.read_text(encoding="utf-8"))
    sample = next(m for m in example["modules"] if m["name"] == "economy")
    sample = {k: sample[k] for k in ("functions", "examples")}
    by_id = {m["id"]: m for m in design["modules"]}
    module = next(m for m in design["modules"] if m["name"] == name)
    plan = [f"- {m['id']} {m['name']}{' (assembly)' if m['kind'] == 'assembly' else ''}"
            f" -> {', '.join(by_id[d]['name'] for d in m['depends_on']) or '(nothing)'}: "
            + "; ".join(f"{fn}: {sig.get('doc', '')}" for fn, sig in m["functions"].items())
            for m in design["modules"]]
    deps = [by_id[d] for d in module["depends_on"]]
    assembly = module["kind"] == "assembly"
    parts = [
        "# Task",
        f"You are the designer. The plan of a design is below. Write module `{name}` ({module['id']}):",
        "for each of its functions, a doc that says HOW it works, and the module's examples.",
        "",
        "Write exactly one file, `module.json`, in the current directory. Nothing else.",
        "",
        *_one_call("module.json"),
        "",
        *WHO_IMPLEMENTS,
        "- every function's \"doc\" starts with ONE sentence saying what it does, then says HOW,",
        "  completely: which dependency functions it calls and in what order, every formula, every",
        "  branch, what it throws and when. If the doc is followed literally, the examples must come",
        "  out. Nothing may be left to guess",
        *(["- give each function examples of its own: the normal case, the edges, every error"] if not assembly else
          ["- its examples are the tests the FINISHED APP is held to: they check the definition's items",
           "  (below). Give each example a \"concepts\" field naming the properties and requirements it",
           "  shows. Every one whose check is \"example\" must be named by at least one example, and a",
           "  counter-example (\"not\") must fail them. Call every function of this module at least once",
           "- a property that holds of anything generated (a maze, a layout) is shown best by ONE",
           "  condition that tries a few inputs and checks each result, not by many examples. One",
           "  example per property is the aim",
           SMALL_VALUES]),
        "",
        f"# The app: {definition.get('title', '')}",
        definition.get("summary", ""),
        *[f"- {i['id']} {i.get('title', '')}: {i.get('statement', '')}" for i in definition.get("items", [])],
        "",
        "# The plan",
        *plan,
        "",
        f"# Module {name}: its contract (fixed by the plan)",
        json.dumps({fn: {k: v for k, v in sig.items() if k != "doc"} for fn, sig in module["functions"].items()},
                   ensure_ascii=False, indent=1),
        "",
        "# The types and errors",
        json.dumps({"types": design.get("types", {}), "errors": design.get("errors", {})}, ensure_ascii=False,
                   indent=1),
    ]
    if deps:
        parts += ["", "# What it depends on (call them as module_name.fn)"]
        for dep in deps:
            for fn, sig in dep["functions"].items():
                params = ", ".join(f"{p['name']}: {p['type']}" for p in sig["params"])
                parts.append(f"- {dep['name']}.{fn}({params}) -> {sig['returns']}"
                             f"{' raises ' + ', '.join(sig['raises']) if sig.get('raises') else ''}: "
                             f"{sig.get('doc', '')}")
    if design.get("fixtures"):
        parts += ["", "# Fixtures other modules already declared (use them by name, or add your own)",
                  *[f"- {k}: {fx.get('type')}" for k, fx in design["fixtures"].items()]]
    if assembly:
        plat = _platform(definition.get("shell", {}).get("platform", "browser-dom"))
        parts += ["", "# The items its examples check, and what each answers to", *_items_text(definition, concepts or {}),
                  "", "# How the platform calls the app, and how to pin it in examples",
                  *["- " + line for line in plat["brief"] + plat.get("examples", [])],
                  *(["Conventions:"] + plat["conventions"] if plat.get("conventions") else [])]
        exs = [e for i in definition.get("items", []) for e in i.get("examples", [])]
        if exs:
            parts += ["", f"# Examples the definition already has: tests this module is held to ({len(exs)})",
                      "Do not copy them into its examples.", *[_render(e) for e in exs]]
    parts += [
        "",
        "# The format of module.json",
        """{"functions": {"<fn>": {"doc": "<what, in one sentence; then how>"}, ...},
 "examples": [<example>, ...],                                  (the assembly's: each with "concepts": [...])
 "fixtures": {"NAME": {"type": ..., "value": ...}}}            (optional: named values for examples)""",
        f"- every function of {name} gets its doc; the contract stays as the plan has it",
        "- in examples, call this module's functions by name and a dependency's as \"module_name.fn\"",
        f"- example ids are {module['id']}.E<n>; fixtures are referenced as {{\"$\": \"NAME\"}}",
        "",
        TYPES,
        "",
        EXAMPLES,
        "",
        "# A module part in this format (from another app, for the shape only)",
        json.dumps(sample, ensure_ascii=False, indent=1),
    ]
    parts += _findings(findings or [], "module")
    return "\n".join(parts) + "\n"
