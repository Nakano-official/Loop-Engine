"""The idle game in the shapes the upstream roles write now (DECISIONS 44): what
the definer writes (what to make) and what the tester writes (the examples),
made from the full definition in docs/formats/examples.

The full idle game calls functions of its own (new_game, buy, ...) that only a
hand-written definition has: from requirements, the interface is the
platform's five. So the draft keeps the item whose examples call those five
(D7) and gives it everything the concept file checks by example, and
`platform_design` cuts the assembly down to the same five.
"""
import copy

PLATFORM = ("start", "step", "act", "screen", "save")
PLATFORM_TYPES = ("NodeKind", "Node", "Screen")


def draft_of(full: dict, items=("D7",)) -> dict:
    refs = sorted({r for i in full["items"] for r in i.get("concepts") or []})
    raises = {fn: sig["raises"] for fn, sig in full["interface"].items() if fn in PLATFORM and sig.get("raises")}
    out = {"format": "loop/definition@1", "title": full["title"], "summary": full["summary"],
           "state": "GameState",
           "types": {k: v for k, v in full["types"].items() if k not in PLATFORM_TYPES},
           "errors": dict(full["errors"]),
           "items": [{"id": i["id"], "title": i["title"], "statement": i["statement"], "concepts": refs}
                     for i in full["items"] if i["id"] in items]}
    if raises:
        out["raises"] = raises
    return out


def examples_of(full: dict, items=("D7",)) -> dict:
    return {"format": "loop/examples@1",
            "items": {i["id"]: copy.deepcopy(i["examples"]) for i in full["items"] if i["id"] in items}}


def platform_design(design: dict) -> dict:
    ds = copy.deepcopy(design)
    asm = next(m for m in ds["modules"] if m["kind"] == "assembly")
    asm["functions"] = {k: v for k, v in asm["functions"].items() if k in PLATFORM}
    return ds
