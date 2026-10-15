"""Briefs for the upstream roles: the analyst, the definer and the designer (DESIGN 2).

    analyze(request, findings)                               -> the analyst's brief
    define(concepts, platform, findings)                     -> the definer's brief
    examples(definition, concepts, findings)                 -> the tester's brief
    design(definition, findings, previous, verdict, concepts) -> the designer's brief

A part, not a flow. A brief is all a role sees, so what it says about the
formats is said here, once, and is the same every time: FORMATS.md, shortened
to what a writer needs, plus the platform's own declaration verbatim. What a
role is told after a failure is decided here too -- the gate's findings, or
for the designer the verdict of used-up attempts: which module, which kind of
reason, which example ids. Never what an implementation returned (DESIGN 5).
"""
from __future__ import annotations

import json
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
                  "requirement with its id and text, and the rest empty", "one concept or a few requirements"),
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
    the examples are the tester's."""
    plat = _platform(platform)
    parts = [
        "# Task",
        "You are the definer. Read the concept file below -- what a person asked for, what their",
        "words mean, and what they need -- and decide WHAT TO MAKE to meet those needs. Write it as",
        "the DEFINITION of the app: what it is, what it remembers (its state), and item by item what",
        "must hold of it. That is all you write. The machine adds the platform's types and",
        "functions; a tester writes the examples each item is checked by, from your statements",
        "alone; a designer turns it into modules later. Do not write examples, functions or modules.",
        "",
        "Write exactly one file, `definition.json`, in the current directory. Nothing else.",
        "Write the summary, titles, statements and any text shown to the user in Japanese.",
        "",
        *_writing("definition.json", "title, summary, state, types, errors, raises, and every item with its "
                  "id and title and an empty statement", "one item or one type"),
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
        "  tester can check only what the statement says",
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


def examples(definition: dict, concepts: dict, findings: list[str] | None = None) -> str:
    """The tester's brief (DECISIONS 44): the examples each item of the
    definition is checked by. The tester reads the items -- what the definer
    wrote -- and what they answer to, and not the concept file as a whole:
    what a statement leaves unsaid shows up as an example the definer did not
    mean, where the loop can see it."""
    platform = definition.get("shell", {}).get("platform", "browser-dom")
    plat = _platform(platform)
    answers = _answers(concepts)
    contract = {k: definition[k] for k in ("types", "errors", "interface") if k in definition}
    items = []
    for item in definition.get("items", []):
        items += ["", f"## {item['id']} {item.get('title', '')}", item.get("statement", "")]
        for ref in item.get("concepts", []):
            a = answers.get(ref)
            if not a:
                continue
            how = "examples must show it" if a["check"] == "example" else "checked later by using the app"
            items.append(f"- answers to {ref} ({how}): {a['text']}")
            if a.get("not"):
                items.append(f"  not {a['concept']}: " + " / ".join(a["not"]))
    parts = [
        "# Task",
        "You are the tester. The definition below says what an app must do, item by item. Write",
        "its EXAMPLES: for each item, concrete calls of the app's functions and how their results",
        "are judged. They become the tests the finished app is held to -- the app is built until",
        "they pass, so an example that is wrong or too weak lets a wrong app through.",
        "",
        "Write exactly one file, `examples.json`, in the current directory. Nothing else.",
        "",
        *_writing("examples.json", "the format and every item id with an empty list", "one item's examples"),
        "",
        f"# The definition: {definition.get('title', '')}",
        definition.get("summary", ""),
        "",
        "The app's types, errors and functions (the functions are what the examples call):",
        json.dumps(contract, ensure_ascii=False, indent=1),
        "",
        "# The items",
        "Each statement, and what it answers to. A counter-example (\"not\") must fail your examples:",
        "if one could pass them, they are too weak.",
        *items,
        "",
        "# What to write",
        "- every item that answers to something examples must show gets examples that show it --",
        "  each such property, not just the item as a whole. An item that answers only to what is",
        "  checked by using the app needs none",
        "- every function of the interface is called by at least one example",
        "- call only these functions; a literal value of a record type has every field",
        "- example ids are <item id>.E<n>",
        "",
        f"# The platform: {platform}",
        *["- " + line for line in plat["brief"]],
        *["- " + line for line in plat.get("examples", [])],
        *(["Conventions:"] + plat["conventions"] if plat.get("conventions") else []),
        "",
        "# The format of examples.json",
        """{"format": "loop/examples@1",
 "items": {"D1": [<example>, ...], "D2": [...], ...}}""",
        "",
        TYPES,
        "",
        EXAMPLES,
    ]
    parts += _findings(findings or [], "examples")
    return "\n".join(parts) + "\n"


def design(definition: dict, findings: list[str] | None = None, previous: dict | None = None,
           verdict: dict | None = None, concepts: dict | None = None) -> str:
    example = json.loads(EXAMPLE_DESIGN.read_text(encoding="utf-8"))
    sample = next(m for m in example["modules"] if m["name"] == "economy")
    platform = definition.get("shell", {}).get("platform", "browser-dom")
    parts = [
        "# Task",
        "You are the designer. Turn the definition below into a DESIGN: modules, each with",
        "contracts, a description of HOW each function works, and concrete examples.",
        "",
        "Write exactly one file, `design.json`, in the current directory. Nothing else.",
        "",
        *_writing("design.json", "format, definition, target, types, errors, shell, and every module with "
                  "its id, name, kind and depends_on, empty functions and examples", "one module"),
        "",
        "# Who implements it",
        "A small local model (9B parameters) implements ONE module at a time, seeing only that",
        "module's contracts, its docs, its examples, and the contracts and docs of the modules it",
        "depends on. It does not see the definition. Design for that reader:",
        "- keep modules small: one to three functions, one idea each. A function with a tricky",
        "  algorithm (a loop, a scale of units, a parser) gets its own module and many examples",
        "- every function's \"doc\" says HOW, completely: which dependency functions it calls and in",
        "  what order, every formula, every branch, what it throws and when. If the doc is followed",
        "  literally, the examples must come out. Nothing may be left to guess",
        "- give each function examples of its own: the normal case, the edges, every error",
        "",
        "# The definition",
        json.dumps(definition, ensure_ascii=False, indent=1),
        "",
        *(["# The concept file the definition answers to",
           "What the words mean and what the person needs. A module must not narrow them either.",
           json.dumps(concepts, ensure_ascii=False, indent=1), ""] if concepts else []),
        "# The format of design.json",
        """{"format": "loop/design@1",
 "definition": "definition.json",
 "target": {"language": "typescript", "platform": "%s"},
 "types": {<every type of the definition, identical>, <your own>},
 "errors": {<every error of the definition>, <your own>},
 "fixtures": {"NAME": {"type": ..., "value": ...}},        (optional: named values for examples)
 "modules": [{"id": "M1", "name": "snake_case", "kind": "pure" | "assembly",
              "depends_on": ["M2", ...],
              "functions": {"<fn>": {"params": [...], "returns": ..., "raises": [...], "doc": "<how>"}},
              "examples": [<example>, ...]}, ...],
 "shell": {"calls": "<the assembly's id>"}}""" % platform,
        "- exactly one module has kind \"assembly\". Its functions are the definition's interface",
        "  EXACTLY (same names, parameters, returns, raises), each with its own doc saying how it",
        "  composes the other modules. The definition's examples are already its tests: do NOT",
        "  copy them into its \"examples\" (leave it [] or add only new ones -- a copy is dropped).",
        "  Every other module must be reachable from it through depends_on; no cycles",
        "- in examples, call your own functions by name and a dependency's as \"module_name.fn\"",
        "- example ids are <module id>.E<n>; fixtures are referenced as {\"$\": \"NAME\"}",
        "",
        TYPES,
        "",
        EXAMPLES,
        "",
        "# A module in this format (from another app, for the shape only)",
        json.dumps(sample, ensure_ascii=False, indent=1),
    ]
    if previous is not None:
        parts += ["", "# Your previous design", json.dumps(previous, ensure_ascii=False, indent=1)]
    if verdict:
        parts += ["", "# The previous design did not work",
                  f"Module `{verdict.get('module')}` could not be implemented in the attempts allowed.",
                  f"Reason: {verdict.get('reason')}",
                  f"Its examples that stayed red: {', '.join(verdict.get('examples', [])) or '(none listed)'}",
                  "Change the design where that points: split the module (granularity), add a",
                  "missing dependency or move a function (boundary), or change how the assembly",
                  "composes the parts (decomposition). Make the docs more literal. Keep what worked."]
    parts += _findings(findings or [], "design")
    return "\n".join(parts) + "\n"
