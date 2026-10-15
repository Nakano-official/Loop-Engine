"""Briefs: what a role is told (SYSTEM 5). A part, not a flow.

    implement(design, module, feedback) -> str     the solver's brief for one module

A brief is the only input a role has, so what goes into it is decided here,
in code, and fixed by tests -- DESIGN 5's rule in particular: the
implementer is shown the examples it must satisfy and, after a failed
attempt, what failed with expected and actual values; nothing else of the
design's or the loop's.

The format is the one solver-local reads (provision/bin/solver-local): it
ends with the heading "# Files you may create or modify" and the paths the
solver may write, one per line. solver-local adds the current contents of
those files and the output instructions itself.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
FILES_HEADING = "# Files you may create or modify"     # solver-local's FILES_HEADING


def _adapter(language: str):
    spec = importlib.util.spec_from_file_location(f"emit_{language}", ADAPTERS / language / "emit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _value(v) -> str:
    if isinstance(v, dict) and set(v) == {"$"}:
        return v["$"]                       # a fixture or an earlier step, by name
    return json.dumps(v, ensure_ascii=False)


def render_example(d, module: dict, ex: dict) -> str:
    """One example as two lines a model can read: the calls, then what must hold."""
    calls = []
    for st in ex["steps"]:
        if "value" in st:
            calls.append(f"{st['let']} = {_value(st['value'])}")
        else:
            args = ", ".join(f"{k}={_value(v)}" for k, v in st["args"].items())
            calls.append(f"{st['let']} = {st['call']}({args})")
    then = ex["then"]
    if "raises" in then:
        last = ex["steps"][-1]
        expect = f"the call to {last['call']} throws {then['raises']}"
    elif "holds" in then:
        expect = f"({then['holds']})({', '.join(then['observe'])}) returns true"
    elif "matches" in then:
        expect = " and ".join(f"{name} has {_value(v)}" for name, v in zip(then["observe"], then["matches"]))
        expect += " (a part: fields not written there are not checked)"
    else:
        expect = " and ".join(f"{name} == {_value(v)}" for name, v in zip(then["observe"], then["equals"]))
    return f"{ex['id']}:  " + "; ".join(calls) + f"\n    must hold: {expect}"


def what_it_does(doc: str | None) -> str:
    """The first sentence of a function's doc: what it does. A design's doc
    says what first and then how (FORMATS 3)."""
    text = (doc or "").strip()
    if not text:
        return "(no description)"
    cut = [i for i in (text.find("。"), text.find(". ")) if i >= 0]
    return text[: min(cut) + 1] if cut else text


def implement(d, module: dict, feedback: tuple = ()) -> str:
    language = d.data["target"]["language"]
    emit = _adapter(language)
    path = f"app/{module['name']}{emit.EXTENSION}"
    examples = d.examples(module)
    used = {v["$"] for ex in examples for st in ex["steps"]
            for v in st.get("args", {}).values() if isinstance(v, dict) and set(v) == {"$"}}
    used |= {v["$"] for ex in examples for v in ex["then"].get("equals", []) + ex["then"].get("matches", [])
             if isinstance(v, dict) and set(v) == {"$"}}
    fixtures = {k: fx for k, fx in d.fixtures.items() if k in used}

    parts = [
        f"# Task",
        f"Implement the module `{module['name']}` ({module['id']}) so that every example below holds.",
        "The functions, their parameters and their return types are fixed by the contract: the file",
        "you are given already has them, returning placeholder values. Replace the bodies.",
        "",
        "# What each function must do",
    ]
    parts += [f"- {fn}: {sig.get('doc', '(no description)')}" for fn, sig in module["functions"].items()]
    deps = [d.modules[m] for m in module["depends_on"]]
    if deps:
        # What each one does -- the first sentence of its doc -- and not how:
        # how it works names the modules IT calls, and a 9B implementer that
        # read them imported them too, unused, and was refused three times
        # for it (2026-10-15, wall_list).
        parts += ["", "# What the functions you may call do"]
        parts += [f"- {dep['name']}.{fn}: {what_it_does(sig.get('doc'))}"
                  for dep in deps for fn, sig in dep["functions"].items()]
    if module is d.assembly:
        # The assembly's examples are the definition's; it gets the statements
        # they were written from as well -- what the app is for.
        parts += ["", "# What the app must do (from its definition)"]
        parts += [f"- {item['id']} {item['title']}: {item['statement']}" for item in d.definition["items"]]
    parts += [
        "",
        "# How to write it",
        emit.implementation_guide(d, module),
        "",
        f"# Examples ({len(examples)}) -- every one must hold",
        "Each line shows calls in order, then what must be true afterwards. Names on the left",
        "of `=` are results you can refer to later in the same example.",
        "",
    ]
    parts += [render_example(d, module, ex) for ex in examples]
    if fixtures:
        parts += ["", "Named values used above:"]
        parts += [f"{k} = {json.dumps(fx['value'], ensure_ascii=False)}" for k, fx in fixtures.items()]
    if feedback:
        parts += ["", "# Your previous attempt failed", "Fix these and keep the rest working:"]
        parts += [str(f) for f in feedback]
    parts += ["", FILES_HEADING, path, ""]
    return "\n".join(parts)
