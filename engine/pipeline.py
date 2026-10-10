"""The loop's flow, top to bottom (REDESIGN 6: the flow lives in this one file).

Everything this calls is a part with no flow of its own: artifacts (the exit
gates), diagnose (where a failure points), a window (prepare-tests / verify /
accept, in the box or local), a solver (a function from a module to its one
file), and a ledger. Read this file to know what happens in what order and
where the loop goes back to.

Not here yet: the upstream stages (analysis, definition, design -- the
definer and designer roles). run() starts from a design that exists.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "adapters"))
import artifacts  # noqa: E402
import briefs  # noqa: E402
import diagnose  # noqa: E402
from design import Design  # noqa: E402

# A solver is either "box" -- the solver role in the box, through the window's
# attempt operation -- or a stand-in function for tests:
# (design, module, feedback from the last attempt) -> {path: text}.
Solver = Callable[[Design, dict, tuple], dict] | str


@dataclass
class Outcome:
    stage: str                       # "done", or the stage the loop goes back to
    reason: str
    green: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)


class Ledger:
    """One JSON line per event, on the host (REDESIGN 6: the ledger is the host's)."""

    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None

    def __call__(self, event: str, **fields) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "event": event, **fields}, ensure_ascii=False) + "\n")


class RemoteWindow:
    """The window in the box, over the runner key (loop-window)."""

    def __init__(self, host: str = "loop-runner"):
        self.host = host

    def call(self, op: str, ws: str, module: str, payload: dict | None) -> dict:
        proc = subprocess.run(["ssh", "-o", "BatchMode=yes", self.host, f"{op} {ws} {module}"],
                              input=json.dumps(payload or {}), capture_output=True, text=True,
                              encoding="utf-8")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"loop-window {op} failed: {proc.stderr.strip() or proc.stdout[:500]}")


def run(design_path: Path | str, solver: Solver, window, ws: str,
        max_attempts: int = 3, ledger: Ledger | None = None) -> Outcome:
    log = ledger or Ledger(None)
    design_path = Path(design_path)

    # 1. The exit gates. A finding names the stage to go back to.
    findings = artifacts.check_files(design_path)
    if findings:
        log("GATE_FAILED", findings=[str(f) for f in findings])
        return Outcome(findings[0].stage, "an exit gate refused it",
                       detail={"findings": [str(f) for f in findings]})
    log("GATES_PASSED")

    d = Design(design_path)
    payload = {"design": d.data, "definition": d.definition}
    green: list[dict] = []

    # 2. Module by module, dependencies first.
    for module in d.order():
        name = module["name"]

        # 2a. Generate the tests and run them against the stub.
        red = window.call("prepare-tests", ws, name, payload)
        verdict = diagnose.red_gate(d, module, red)
        log("RED_GATE", module=name, stage=verdict.stage, reason=verdict.reason)
        if verdict.stage != diagnose.RED:
            return Outcome(verdict.stage, f"{name}: {verdict.reason}", [m["name"] for m in green],
                           detail=verdict.facts)

        # 2b. Attempts, until green or used up.
        attempts: list[diagnose.Verdict] = []
        feedback: tuple = ()
        for n in range(1, max_attempts + 1):
            names = [m["name"] for m in green]
            if solver == "box":
                # The solver role, in the box: the brief is composed here, on
                # the host, and the window stages, solves and verifies.
                brief = briefs.implement(d, module, feedback)
                result = window.call("attempt", ws, name, {"brief": brief, "green": names})
                if "engine" in result:
                    log("ATTEMPT", module=name, n=n, stage=diagnose.ENGINE, reason=result["engine"])
                    return Outcome(diagnose.ENGINE, f"{name}: {result['engine']}", names,
                                   detail={"output": result.get("output", "")[-3000:]})
            else:
                # A stand-in: a function that returns the module's file.
                files = solver(d, module, feedback)
                result = window.call("verify", ws, name, {"files": files, "green": names})
            if "refused" in result:
                verdict = diagnose.Verdict(diagnose.IMPLEMENTATION, result["refused"],
                                           feedback=(result["refused"],),
                                           facts={"built": False, "failed": [], "broke": []})
            else:
                verdict = diagnose.attempt(d, module, result, green)
            log("ATTEMPT", module=name, n=n, stage=verdict.stage, reason=verdict.reason)
            if verdict.stage == diagnose.GREEN:
                window.call("accept", ws, name, None)
                green.append(module)
                log("GREEN", module=name, attempts=n)
                break
            attempts.append(verdict)
            feedback = verdict.feedback
        else:
            # 2c. Used up: the design is at fault, and is told only ids and why.
            verdict = diagnose.exhausted(d, module, attempts)
            log("EXHAUSTED", module=name, **verdict.for_design())
            return Outcome(verdict.stage, f"{name}: {verdict.reason}", [m["name"] for m in green],
                           detail=verdict.for_design())

    log("ALL_GREEN", modules=[m["name"] for m in green])
    return Outcome("done", "every module green, the definition's examples included",
                   [m["name"] for m in green])
