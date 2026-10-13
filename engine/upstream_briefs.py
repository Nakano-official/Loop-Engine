"""Briefs for the upstream roles: the analyst, the definer and the designer (DESIGN 2).

    analyze(request, findings)                               -> the analyst's brief
    define(concepts, platform, findings)                     -> the definer's brief
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
- "then" is either {"observe": [names], "equals": [values]} (compared once, exactly; floats
  within 1e-9) or {"raises": "ErrorName"} -- the LAST step must throw it, and its function
  must declare it in "raises"
- the same call on the same input must never expect two different results
- compute every expected value yourself, exactly. Avoid values that need rounding at a
  tie (x.xx5) -- languages round them differently"""


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
        "  - properties: what must always hold of it, each checkable. check \"example\" when a",
        "    concrete input and its expected result could show it; \"evaluation\" when only using",
        "    the finished thing could (how it looks, whether it is clear)",
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


def define(concepts: dict, platform: str = "browser-dom", findings: list[str] | None = None) -> str:
    plat = _platform(platform)
    sig = "\n".join(f"  {fn}({', '.join(p['name'] + ': ' + p['type'] for p in s['params'])}) -> {s['returns']}"
                    for fn, s in plat["interface"].items())
    parts = [
        "# Task",
        "You are the definer. Read the concept file below -- what a person asked for, what their",
        "words mean, and what they need -- decide WHAT TO MAKE to meet those needs, and write it",
        "as the DEFINITION of the app: its external interface (what the app's shell can call) and,",
        "item by item, what it must do, each with concrete examples. A designer will turn it into",
        "modules later; you do not design them.",
        "",
        "Write exactly one file, `definition.json`, in the current directory. Nothing else.",
        "Write the summary, titles, statements and any text shown to the user in Japanese.",
        "",
        "# The concept file",
        "It binds you. Do not narrow a concept to whatever is easiest to define: its meaning,",
        "properties and counter-examples (\"not\") say what it must be, and an example set that a",
        "counter-example could satisfy is wrong. Whatever the request specifies stays as specified.",
        json.dumps(concepts, ensure_ascii=False, indent=1),
        "",
        "# What the definition must cover",
        "- \"summary\": in a sentence or two, what you make and for what",
        "- every property and requirement whose check is \"example\" is listed in the \"concepts\"",
        "  field of at least one item, and that item's examples actually show it. A gate checks the",
        "  listing; the examples have to make it true",
        "- \"evaluation\" ones are checked later by using the app; list them where they apply",
        "",
        f"# The platform: {platform}",
        "How the app is delivered is fixed: one HTML file, drawn by a generic shell. Ignore any",
        "need for servers, build steps or files -- the platform decides those. The shell",
        "calls exactly these functions, which your interface must contain with exactly these",
        "parameters ($State is a record type you declare: the app's whole state):",
        sig,
        # How this platform calls the app, from its platform.json: the brief
        # says what is true of the platform the definition declared, and only
        # that.
        *["- " + line for line in plat["brief"]],
        "Declare these types exactly as written:",
        json.dumps(plat["types"], ensure_ascii=False, indent=1),
        *(["Conventions:"] + plat["conventions"] if plat.get("conventions") else []),
        "",
        "# The format of definition.json",
        """{"format": "loop/definition@1",
 "title": "<the app's name, Japanese>",
 "summary": "<what is made, and for what -- a sentence or two, Japanese>",
 "types": {...}, "errors": {"ErrorName": "<what it means>", ...},
 "interface": {"<fn>": {"params": [{"name": ..., "type": ...}], "returns": ..., "raises": [...]}, ...},
 "items": [{"id": "D1", "title": ..., "statement": "<what must hold, Japanese>",
            "concepts": ["C1.P1", "R2", ...],
            "examples": [<example>, ...]}, ...],
 "shell": {"platform": "%s", "duties": ["<what the shell does, one line each>"]}}""" % platform,
        "- the interface may have functions beyond the platform's five; every one needs examples",
        "- example ids are <item id>.E<n>; every item has at least one example; every interface",
        "  function is called by at least one example",
        "",
        TYPES,
        "",
        EXAMPLES,
    ]
    parts += _findings(findings or [], "definition")
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
