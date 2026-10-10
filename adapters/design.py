"""The language-neutral side of every adapter: reading a design (FORMATS.md).

An adapter for a language turns a design into that language's types, stubs and
tests. Everything that does not depend on the language lives here, once:

    parse_type(t)          "list<GeneratorSpec>" -> ("list", ("named", "GeneratorSpec"))
    Design(path)           the design, with its definition beside it
      .order()             modules in the order they are built (dependencies first)
      .examples(m)         a module's examples; for the assembly, the definition's
      .resolve(m, call)    "rules.buy" or "buy" -> (module, function, contract)
      .examples_file()     the LOOP_EXAMPLES content: every example, each step
                           annotated with the types its arguments must be decoded as
      .leaves()            every primitive value any expected value contains --
                           a stub's sentinels are chosen outside these (DESIGN 5)

It assumes the design has passed the exit gates (FORMATS 7). It does not check
them again; it fails loudly where a gate should have.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PRIMITIVES = {"int", "float", "string", "bool"}


def parse_type(t: str) -> tuple:
    t = t.replace(" ", "")
    m = re.fullmatch(r"(list|optional)<(.+)>", t)
    if m:
        return (m.group(1), parse_type(m.group(2)))
    m = re.fullmatch(r"map<string,(.+)>", t)
    if m:
        return ("map", parse_type(m.group(1)))
    return ("prim", t) if t in PRIMITIVES else ("named", t)


def is_ref(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"$"}


def _same(example: dict) -> str:
    """What an example says, without its id."""
    return json.dumps({"steps": example["steps"], "then": example["then"]}, sort_keys=True)


class Design:
    def __init__(self, path: Path | str):
        path = Path(path)
        self.data = json.loads(path.read_text(encoding="utf-8"))
        self.definition = json.loads(
            (path.parent / self.data["definition"]).read_text(encoding="utf-8"))
        self.types: dict = self.data["types"]
        self.errors: dict = self.data["errors"]
        self.fixtures: dict = self.data.get("fixtures", {})
        self.modules: dict = {m["id"]: m for m in self.data["modules"]}
        self.by_name: dict = {m["name"]: m for m in self.data["modules"]}
        self.assembly = next(m for m in self.data["modules"] if m["kind"] == "assembly")

    # ---- structure -------------------------------------------------------

    def order(self) -> list[dict]:
        done: list[str] = []

        def visit(mid: str) -> None:
            if mid in done:
                return
            for dep in self.modules[mid]["depends_on"]:
                visit(dep)
            done.append(mid)

        for mid in self.modules:
            visit(mid)
        return [self.modules[mid] for mid in done]

    def examples(self, module: dict) -> list[dict]:
        own = list(module["examples"])
        if module is self.assembly:
            # The definition's examples are the assembly's already. A designer
            # that copies them in as well (maze3d did, all 16) would double the
            # tests and the solver's brief -- the copy goes, the definition's id
            # stays, since that is where the example was written.
            defined = [e for item in self.definition["items"] for e in item["examples"]]
            seen = {_same(e) for e in defined}
            own = defined + [e for e in own if _same(e) not in seen]
        return own

    def resolve(self, module: dict, call: str) -> tuple[dict, str, dict]:
        """A call in one of `module`'s examples: its own function by bare name, a
        dependency's as "<module name>.<function>" (FORMATS 3)."""
        if "." in call:
            name, fn = call.split(".", 1)
            target = self.by_name[name]
            if target["id"] not in module["depends_on"]:
                raise ValueError(f"{module['id']}: {call} is not a dependency")
        else:
            target, fn = module, call
        return target, fn, target["functions"][fn]

    # ---- what the comparison function reads ------------------------------

    def examples_file(self) -> dict:
        out = []
        for module in self.order():
            for ex in self.examples(module):
                steps = []
                for st in ex["steps"]:
                    if "value" in st:
                        steps.append(dict(st))
                        continue
                    target, fn, sig = self.resolve(module, st["call"])
                    steps.append({**st, "module": target["name"], "function": fn,
                                  "arg_types": {p["name"]: p["type"] for p in sig["params"]},
                                  "returns": sig["returns"]})
                out.append({**ex, "module": module["name"], "steps": steps})
        return {"types": self.types, "fixtures": self.fixtures, "examples": out}

    # ---- sentinels --------------------------------------------------------

    def leaves(self) -> dict[str, set]:
        """Every primitive any expected value contains, by kind. A stub that
        returns something built only from values outside these cannot equal
        any expected value -- except an empty container, which has no leaves,
        so a stub's containers are never empty."""
        found: dict[str, set] = {"number": set(), "string": set(), "bool": set()}

        def walk(v: Any) -> None:
            if is_ref(v):
                walk(self.fixtures[v["$"]]["value"])
            elif isinstance(v, bool):
                found["bool"].add(v)
            elif isinstance(v, (int, float)):
                found["number"].add(float(v))
            elif isinstance(v, str):
                found["string"].add(v)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
            elif isinstance(v, dict):
                for k, x in v.items():
                    found["string"].add(k)
                    walk(x)

        for module in self.data["modules"]:
            for ex in self.examples(module):
                for v in ex["then"].get("equals", []):
                    walk(v)
        return found

    def sentinels(self) -> dict:
        """The primitives a stub builds everything from: a float, an int and a
        string that no expected value in the design contains. Every adapter
        uses these same three, so a stub means the same thing in every
        language."""
        leaves = self.leaves()
        number = -987654.25
        while number in leaves["number"]:
            number -= 1.0
        integer = -987654
        while float(integer) in leaves["number"]:
            integer -= 1
        string = "__stub__"
        while string in leaves["string"]:
            string += "_"
        return {"float": number, "int": integer, "string": string,
                "unused_enum": {name: [v for v in decl["enum"] if v not in leaves["string"]]
                                for name, decl in self.types.items() if "enum" in decl}}

    def observes_a_result(self, ex: dict) -> bool:
        """Whether an example looks at something a call returned. Only those
        must fail against a stub; one that observes an input it passed in
        (to show the input was left alone) passes against a stub that does
        nothing, and is right to (DESIGN 5)."""
        called = {st["let"] for st in ex["steps"] if "call" in st}
        if "raises" in ex["then"]:
            return True
        return any(name in called for name in ex["then"]["observe"])
