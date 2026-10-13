"""What one Python module reaches for (DESIGN 5, the reference check).

    python refs.py <module.py>

Prints one JSON line:
    {"imports": [modules], "forbidden": [what it may not use]}
    {"error": "..."}            the file does not parse (the tests will say so)

A module of the design is a pure function of its arguments: the clock, the
randomness, files and the network are not its to touch. So what a module may
use is listed -- the builtins that compute, and the standard library modules
that compute -- and everything else is refused. A list of what is allowed, not
of what is not: a list of what is not misses whatever nobody thought of.

Which modules of the design it may import depends on the design (the types
and the modules it depends on); that check is the adapter's
(emit.check_references). This file reports `loop_types` and `app.*` imports
and refuses any other import that is not on the list.

The file is parsed, never run.
"""
from __future__ import annotations

import ast
import json
import sys

ALLOWED_BUILTINS = set("""
abs all any ascii bin bool bytes callable chr complex dict divmod enumerate filter float format
frozenset hash hex int isinstance issubclass iter len list map max min next object oct ord pow
range repr reversed round set slice sorted str sum tuple type zip super property staticmethod
classmethod NotImplemented Ellipsis
BaseException Exception ArithmeticError AssertionError AttributeError IndexError KeyError
LookupError NotImplementedError OverflowError RuntimeError StopIteration TypeError ValueError
ZeroDivisionError
""".split())

# Standard library modules that only compute. random, time and datetime are
# not here: what changes from call to call comes in through the arguments.
ALLOWED_STDLIB = set("""
__future__ abc bisect collections copy dataclasses decimal enum fractions functools heapq
itertools json math numbers operator re statistics string textwrap typing
""".split())

DESIGN_PACKAGES = {"loop_types", "app"}

# Dunder attributes lead from any value back to the interpreter
# (().__class__.__base__.__subclasses__()). These few do not.
ALLOWED_DUNDERS = {"__init__", "__name__", "__class__", "__post_init__"}


def inspect(tree: ast.AST) -> dict:
    bound: set[str] = set()
    loads: set[str] = set()
    imports: list[str] = []
    forbidden: set[str] = set()

    def imported(spec: str) -> None:
        top = spec.split(".")[0]
        if top in ALLOWED_STDLIB:
            return
        if top in DESIGN_PACKAGES:
            imports.append(spec)
        else:
            forbidden.add(f"import {spec}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
                imported(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                      # from . import x, from .x import y
                module = "app" + (f".{node.module}" if node.module else "")
            else:
                module = node.module or ""
            for alias in node.names:
                bound.add(alias.asname or alias.name)
                imported(f"{module}.{alias.name}" if module == "app" else module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name):
            (loads if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
        elif isinstance(node, ast.Attribute):
            a = node.attr
            if a.startswith("__") and a.endswith("__") and a not in ALLOWED_DUNDERS:
                forbidden.add(f".{a}")

    forbidden |= {n for n in loads - bound if n not in ALLOWED_BUILTINS}
    return {"imports": imports, "forbidden": sorted(forbidden)}


def main(argv: list[str]) -> int:
    try:
        source = open(argv[0], encoding="utf-8").read()
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as e:
        print(json.dumps({"error": str(e)[:500]}))
        return 0
    print(json.dumps(inspect(tree)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
