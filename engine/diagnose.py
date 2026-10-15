"""Where a failure points (DESIGN 5). A part, not a flow: records in, a
verdict out. No model, no state, no I/O -- so it is fixed by its tests.

    red_gate(design, module, run)              after generating tests, against stubs
    attempt(design, module, run, green)        after one implementation attempt
    exhausted(design, module, attempts)        when the attempts are used up

`run` is what the window returns for one test run: {"records": [...],
"output": "..."} -- the comparison function's record (FORMATS 10) and the test
framework's output, which is read only for the message, never for the verdict.

Who is at fault, by where it failed:

    red gate, generated tests      the engine (adapter or generator) -> a person
    attempt                        the implementation -> try again (also when
                                   the reference check refused it)
    attempts used up               the module design: boundary or granularity
    assembly's attempts used up    the module design: decomposition / assembly
"""
from __future__ import annotations

from dataclasses import dataclass, field

GREEN = "green"
RED = "red"                      # the red gate passed: tests fail properly
ENGINE = "エンジン"
IMPLEMENTATION = "実装"
DESIGN = "モジュール設計"


@dataclass(frozen=True)
class Verdict:
    stage: str                   # GREEN, RED, or the stage at fault
    reason: str
    # For the implementation only: what failed, with expected and actual
    # values. DESIGN 5: the design is never shown what an implementation
    # returned, or it would bend its examples to match.
    feedback: tuple = ()
    # Facts about one attempt, kept for exhausted().
    facts: dict = field(default_factory=dict)

    def for_design(self) -> dict:
        """What may be passed back to the designer: ids and the kind of reason."""
        return {"stage": self.stage, "reason": self.reason,
                "examples": sorted(self.facts.get("failed", []))}


def _split(run: dict) -> tuple[set, dict]:
    started, checks = set(), {}
    for r in run.get("records", []):
        if r.get("t") == "start":
            started.add(r["id"])
        elif r.get("t") == "check":
            checks[r["id"]] = r
    return started, checks


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join((text or "").splitlines()[-lines:])


# ---- the red gate ----------------------------------------------------------

def red_gate(design, module: dict, run: dict) -> Verdict:
    """The generated tests against the stub. Both are made by the machine from
    the same contract, so any way this goes wrong is the machine's."""
    expected = [ex["id"] for ex in design.examples(module)]
    started, checks = _split(run)
    missing = [i for i in expected if i not in started]
    if missing:
        return Verdict(ENGINE, f"generated tests did not run: {missing[:5]}",
                       facts={"output": _tail(run.get("output", ""))})
    crashed = [i for i in expected if i not in checks]
    if crashed:
        return Verdict(ENGINE, f"a generated test could not call the stub: {crashed[:5]}",
                       facts={"output": _tail(run.get("output", ""))})
    for ex in design.examples(module):
        ok = checks[ex["id"]]["ok"]
        if design.is_condition(ex):
            continue
        if design.observes_a_result(ex) and ok:
            return Verdict(ENGINE, f"{ex['id']} passes against the stub -- a sentinel collides")
        if not design.observes_a_result(ex) and not ok:
            return Verdict(ENGINE, f"{ex['id']} observes only its input, yet fails against the stub")
    return Verdict(RED, f"{len(expected)} examples red against the stub, as they must be")


# ---- one attempt -----------------------------------------------------------

def attempt(design, module: dict, run: dict, green: list[dict]) -> Verdict:
    """One implementation attempt: this module's examples, and every example of
    the modules already green (they must not stop passing)."""
    own = [ex["id"] for ex in design.examples(module)]
    previous = [ex["id"] for m in green for ex in design.examples(m)]
    started, checks = _split(run)

    undeclared, forbidden = run.get("undeclared", []), run.get("forbidden", [])
    if undeclared or forbidden:
        # The reference check refused it before it ran (DESIGN 5).
        feedback = []
        if undeclared:
            feedback.append(f"imports {', '.join(undeclared)}, which the design does not let this module "
                            "import: import only the types and the modules you depend on")
        if forbidden:
            feedback.append(f"uses {', '.join(forbidden)}, which a module may not use: everything that "
                            "changes from call to call comes in through the parameters")
        return Verdict(IMPLEMENTATION, "refused before it ran: it reaches for what it may not",
                       feedback=tuple(feedback),
                       facts={"built": True, "failed": own, "broke": [],
                              "undeclared": undeclared, "forbidden": forbidden})

    if not any(i in started for i in own):
        # Nothing of this module ran: it does not build or load.
        return Verdict(IMPLEMENTATION, "the module does not build or load",
                       feedback=(_tail(run.get("output", "")),),
                       facts={"built": False, "failed": own, "broke": []})

    failed, feedback = [], []
    for i in own:
        r = checks.get(i)
        if r is None:
            failed.append(i)
            feedback.append(f"{i}: raised an error before comparing (see the output)")
        elif not r["ok"]:
            failed.append(i)
            feedback.append(f"{i}: expected {r['expected']}, got {r['actual']}")
    broke = [i for i in previous if not (checks.get(i) or {}).get("ok")]
    for i in broke:
        feedback.append(f"{i}: passed before this attempt and does not now")
    if not failed and not broke:
        return Verdict(GREEN, f"{len(own)} examples green, {len(previous)} earlier ones still green",
                       facts={"built": True, "failed": [], "broke": []})
    if failed and any(checks.get(i) is None for i in failed):
        feedback.append(_tail(run.get("output", "")))
    return Verdict(IMPLEMENTATION, f"{len(failed)} examples red, {len(broke)} earlier ones broken",
                   feedback=tuple(feedback),
                   facts={"built": True, "failed": failed, "broke": broke})


# ---- the attempts used up ---------------------------------------------------

def exhausted(design, module: dict, attempts: list[Verdict]) -> Verdict:
    """Every attempt failed. At this point the tests are the design's examples,
    transcribed and verified against a stub, so what remains is the design's
    (DESIGN 5, "使い切ったら、なぜ設計なのか")."""
    failed = sorted({i for a in attempts for i in a.facts.get("failed", [])})
    facts = {"failed": failed}
    if module is design.assembly:
        return Verdict(DESIGN, "decomposition: every part is green, the definition's examples are not",
                       facts=facts)
    if attempts and all(a.facts.get("undeclared") for a in attempts):
        return Verdict(DESIGN, "boundary: every attempt needed a module the design does not declare",
                       facts=facts)
    if attempts and all(a.facts.get("forbidden") for a in attempts):
        # The module was asked for something only the shell has (the time,
        # randomness, I/O): the design must pass it in as a parameter.
        return Verdict(DESIGN, "boundary: every attempt reached outside the module -- what it needs "
                               "must come in as a parameter", facts=facts)
    if attempts and all(a.facts.get("broke") for a in attempts):
        return Verdict(DESIGN, "boundary: every attempt broke a module that was already green",
                       facts=facts)
    return Verdict(DESIGN, "granularity: too much for the implementer in one module -- split it",
                   facts=facts)
