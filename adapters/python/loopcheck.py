"""The comparison function for Python (DESIGN 5, FORMATS 10).

A generated test does three things with it, and nothing else:

    ex = start("M2.E1")                       # record START, load the example
    p = current_cost(...)                     # the call, built from the example
    check(ex, p)                              # compare once, record CHECK

or, for an example that expects an error:

    ex = start("M2.E5")
    check_raises(ex, lambda: production_rate(...))

The expected value is never in the test. It is read from the examples file the
window prepares (LOOP_EXAMPLES), so nobody types it -- that is what makes the
test a transcription rather than a judgement.

The verdict is the RECORD, not the test framework's report: one JSON object per
line in $LOOP_RECORD_DIR/records.jsonl, flushed as it is written, so a test that
crashes after START leaves exactly that behind. Its shape is the same in every
language (FORMATS 10); only this file is Python's.
"""
from __future__ import annotations

import dataclasses
import enum
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

DEFAULT_REL = 1e-9
DEFAULT_ABS = 1e-12

_examples: dict[str, dict] | None = None
_fixtures: dict[str, Any] = {}


def _load() -> dict[str, dict]:
    global _examples, _fixtures
    if _examples is None:
        data = json.loads(Path(os.environ["LOOP_EXAMPLES"]).read_text(encoding="utf-8"))
        _examples = {e["id"]: e for e in data["examples"]}
        _fixtures = {k: v["value"] for k, v in data.get("fixtures", {}).items()}
    return _examples


def _record(entry: dict) -> None:
    path = Path(os.environ.get("LOOP_RECORD_DIR", ".")) / "records.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()


# ---- the canonical form -------------------------------------------------

def canon(value: Any) -> Any:
    """A Python value in the language-neutral shape FORMATS 2 describes.

    record -> object with its fields; enum -> its value; tuple -> list.
    Anything else that JSON cannot hold is an error, not a guess: a value the
    comparison cannot see must not compare equal by accident.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # A field whose design name is a Python keyword is generated as name_,
        # and carries the design's name in its metadata.
        return {f.metadata.get("design", f.name): canon(getattr(value, f.name))
                for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canon(v) for v in value]
    raise TypeError(f"loopcheck: no canonical form for {type(value).__name__}")


def _resolve(value: Any) -> Any:
    """Expected values may name a fixture: {"$": "CATALOG"}."""
    if isinstance(value, dict) and set(value) == {"$"}:
        return _fixtures[value["$"]]
    return value


def equal(expected: Any, actual: Any, rel: float = DEFAULT_REL, abs_: float = DEFAULT_ABS) -> bool:
    """Canonical equality. bool is not a number here (True != 1); int and float
    compare by value, floats within the tolerance; map order does not matter,
    list order does."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is type(actual) and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if math.isnan(expected) or math.isnan(actual):
            return math.isnan(expected) and math.isnan(actual)
        return math.isclose(expected, actual, rel_tol=rel, abs_tol=abs_)
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(
            equal(expected[k], actual[k], rel, abs_) for k in expected)
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(
            equal(e, a, rel, abs_) for e, a in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


# ---- building inputs ------------------------------------------------------
#
# A generated test does not spell out its inputs either. It asks for each
# argument by step and name, and gets the example's value built into the
# design's types -- records as the generated dataclasses, enums as the
# generated Enum classes. The registry of those comes from the generated
# loop_types module, handed over once with use_types().

_types: Any = None


def use_types(module: Any) -> None:
    global _types
    _types = module


def _parse(t: str) -> tuple:
    t = t.replace(" ", "")
    for kind in ("list", "optional"):
        if t.startswith(kind + "<") and t.endswith(">"):
            return (kind, _parse(t[len(kind) + 1:-1]))
    if t.startswith("map<string,") and t.endswith(">"):
        return ("map", _parse(t[len("map<string,"):-1]))
    return ("prim", t) if t in ("int", "float", "string", "bool") else ("named", t)


def decode(value: Any, t: str | tuple) -> Any:
    """A canonical value, built into the design's type `t`."""
    value = _resolve(value)
    kind = _parse(t) if isinstance(t, str) else t
    if kind[0] == "prim":
        return {"int": int, "float": float, "string": str, "bool": bool}[kind[1]](value)
    if kind[0] == "optional":
        return None if value is None else decode(value, kind[1])
    if kind[0] == "list":
        return [decode(v, kind[1]) for v in value]
    if kind[0] == "map":
        return {k: decode(v, kind[1]) for k, v in value.items()}
    name = kind[1]
    if name in _types.ENUMS:
        return _types.ENUMS[name](value)
    cls, fields = _types.RECORDS[name]
    return cls(**{_types.pyname(f): decode(value[f], ft) for f, ft in fields})


def arg(ex: dict, step: int, name: str | None = None) -> Any:
    """Step `step`'s argument `name`, or a value step's value when `name` is None."""
    st = ex["steps"][step]
    if name is None:
        return decode(st["value"], st["type"])
    return decode(st["args"][name], st["arg_types"][name])


# ---- what a generated test calls ----------------------------------------

def start(example_id: str) -> dict:
    ex = _load().get(example_id)
    _record({"t": "start", "id": example_id})
    if ex is None:
        raise KeyError(f"loopcheck: no example {example_id!r} in LOOP_EXAMPLES")
    return ex


def check(ex: dict, *actuals: Any) -> None:
    """Compare the observed values with the example's `then.equals`, once."""
    then = ex["then"]
    if "equals" not in then:
        raise AssertionError(f"{ex['id']}: expects {then}, use check_raises")
    expected = [canon(_resolve(v)) for v in then["equals"]]
    actual = [canon(a) for a in actuals]
    tol = ex.get("tol", {})
    ok = equal(expected, actual, tol.get("rel", DEFAULT_REL), tol.get("abs", DEFAULT_ABS))
    _record({"t": "check", "id": ex["id"], "ok": ok, "expected": expected, "actual": actual})
    if not ok:
        raise AssertionError(f"{ex['id']}: expected {expected}, got {actual}")


def check_raises(ex: dict, call: Callable[[], Any]) -> None:
    """The last step must raise the error the example names. The error's name
    is the design's error name; the adapter generates classes by that name."""
    want = ex["then"]["raises"]
    try:
        returned = call()
    except Exception as e:  # noqa: BLE001 -- every outcome is recorded
        got: dict = {"raises": type(e).__name__}
    else:
        try:
            got = {"returned": canon(returned)}
        except TypeError:
            got = {"returned": repr(returned)}
    ok = got == {"raises": want}
    _record({"t": "check", "id": ex["id"], "ok": ok, "expected": {"raises": want}, "actual": got})
    if not ok:
        raise AssertionError(f"{ex['id']}: expected {want} to be raised, got {got}")
