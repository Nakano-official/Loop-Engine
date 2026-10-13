"""Conformance: the reference check (DESIGN 5) in the Python adapter.

refs.py reads one module file and reports what it imports and which names it
may not use; emit.check_references holds the imports against the design. The
correct idle game passes untouched; each way of reaching outside a pure
module is refused, and the language's own tools for computing are not.
"""
import ast
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import emit  # noqa: E402
import refs  # noqa: E402

DESIGN = emit.Design(HERE.parents[2] / "docs" / "formats" / "examples" / "idlegame.design.json")
CORRECT = {p.stem: p.read_text(encoding="utf-8") for p in (HERE / "idlegame").glob("*.py")}


def check(module: str, source: str) -> dict:
    return emit.check_references(DESIGN, DESIGN.by_name[module], refs.inspect(ast.parse(source)))


@pytest.mark.parametrize("module", sorted(CORRECT))
def test_the_correct_idle_game_passes(module):
    assert check(module, CORRECT[module]) == {"undeclared": [], "forbidden": []}


@pytest.mark.parametrize("source, refused", [
    ("import os\n", "import os"),
    ("import random\n", "import random"),
    ("from time import time\n", "import time"),
    ("import datetime\n", "import datetime"),
    ("import urllib.request\n", "import urllib.request"),
    ("def f():\n    return open('x').read()\n", "open"),
    ("def f(s):\n    return eval(s)\n", "eval"),
    ("def f():\n    print('hi')\n", "print"),
    ("def f():\n    return input()\n", "input"),
    ("def f(s):\n    return __import__(s)\n", "__import__"),
    ("def f(x):\n    return getattr(x, 'y')\n", "getattr"),
    ("def f():\n    return ().__class__.__base__.__subclasses__()\n", ".__base__"),
])
def test_reaching_outside_is_refused(source, refused):
    assert refused in check("format", source)["forbidden"]


def test_a_module_the_design_does_not_declare_is_refused():
    # format depends on scale only.
    found = check("format", "from app import economy as m_economy\n")
    assert found["undeclared"] == ["app.economy"]
    assert check("format", "from app import scale as m_scale\nimport loop_types\n")["undeclared"] == []


def test_computing_is_allowed():
    source = (
        "from __future__ import annotations\n"
        "import dataclasses, math, json\n"
        "from functools import reduce\n"
        "import loop_types\n\n"
        "def f(xs, now):\n"
        "    total = sum(x * 2 for x in xs if isinstance(x, int))\n"
        "    best = max(xs, default=0)\n"
        "    try:\n"
        "        v = math.floor(now)\n"
        "    except ValueError as e:\n"
        "        raise loop_types.CorruptSave(str(e)) from None\n"
        "    return json.dumps(sorted({k: v for k, v in enumerate(xs)}.items())), total, best, v\n"
    )
    assert check("format", source) == {"undeclared": [], "forbidden": []}


def test_a_file_that_does_not_parse_is_left_to_its_tests(tmp_path, capsys):
    f = tmp_path / "x.py"
    f.write_text("def f(:\n", encoding="utf-8")
    refs.main([str(f)])
    assert '"error"' in capsys.readouterr().out
