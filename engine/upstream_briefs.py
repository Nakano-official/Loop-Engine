"""Briefs for the upstream roles: the definer and the designer (DESIGN 2).

    define(requirements, platform, findings)                 -> the definer's brief
    design(definition, findings, previous, verdict)          -> the designer's brief

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


def define(requirements: str, platform: str = "browser-dom", findings: list[str] | None = None) -> str:
    plat = _platform(platform)
    sig = "\n".join(f"  {fn}({', '.join(p['name'] + ': ' + p['type'] for p in s['params'])}) -> {s['returns']}"
                    for fn, s in plat["interface"].items())
    parts = [
        "# Task",
        "You are the definer. Read the requirements below and write the DEFINITION of the app: its",
        "external interface (what the app's shell can call) and, item by item, what it must do, each",
        "with concrete examples. A designer will turn it into modules later; you do not design them.",
        "",
        "Write exactly one file, `definition.json`, in the current directory. Nothing else.",
        "Write titles, statements and any text shown to the player in Japanese.",
        "",
        "# The requirements",
        requirements.strip(),
        "",
        f"# The platform: {platform}",
        "How the app is delivered is fixed: one HTML file, drawn by a generic shell. Ignore any",
        "requirement about servers, build steps or files -- the platform decides those. The shell",
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
 "types": {...}, "errors": {"ErrorName": "<what it means>", ...},
 "interface": {"<fn>": {"params": [{"name": ..., "type": ...}], "returns": ..., "raises": [...]}, ...},
 "items": [{"id": "D1", "title": ..., "statement": "<what must hold, Japanese>",
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
           verdict: dict | None = None) -> str:
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
