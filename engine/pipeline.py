"""The loop's flow, top to bottom (SYSTEM 6: the flow lives in this one file).

Everything this calls is a part with no flow of its own: artifacts (the exit
gates), diagnose (where a failure points), a window (prepare-tests / verify /
accept, in the box or local), a solver (a function from a module to its one
file), and a ledger. Read this file to know what happens in what order and
where the loop goes back to.

run() starts from a design that exists; run_from_requirements() starts from
requirements and puts the definer and the designer in front of it.
"""
from __future__ import annotations

import json
import re
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
import upstream_briefs  # noqa: E402
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
    """One JSON line per event, on the host (SYSTEM 7: the ledger is the host's).

    Beside it, the files an event points at (keep): what a role was told and
    what it wrote, what each test compared. The ledger says what happened;
    these say with what. They are for a person reading the run -- no stage
    reads them back, so keeping them shows no role anything it was not shown.
    """

    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None

    def __call__(self, event: str, **fields) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "event": event, **fields}, ensure_ascii=False) + "\n")

    def keep(self, rel: str, text: str | None, once: bool = False) -> None:
        """Write `text` at `rel` beside the ledger. `once`: not over a file
        that is already there."""
        if not self.path or text is None:
            return
        p = self.path.parent / rel
        if once and p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _part(name: str) -> str:
    """A name a role wrote, made safe as one path component."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name).lstrip(".") or "_"


# A run started from the dashboard has no console (so it outlives the
# dashboard). On Windows, a process without a console that starts a console
# program -- ssh -- gets a NEW console window for it: one popped up for every
# call to the box. CREATE_NO_WINDOW starts ssh with none.
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


class RemoteWindow:
    """The window in the box, over the runner key (loop-window)."""

    def __init__(self, host: str = "loop-runner"):
        self.host = host

    def call(self, op: str, ws: str, module: str, payload: dict | None) -> dict:
        proc = subprocess.run(["ssh", "-o", "BatchMode=yes", self.host, f"{op} {ws} {module}"],
                              input=json.dumps(payload or {}), capture_output=True, text=True,
                              encoding="utf-8", **NO_WINDOW)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"loop-window {op} failed: {proc.stderr.strip() or proc.stdout[:500]}")


def _keep_attempt(log: Ledger, here: str, files: dict, result: dict) -> None:
    """One attempt's files, for a person: the code it wrote, what each test
    compared, the test framework's and the solver's own output."""
    for path, text in (files or {}).items():
        log.keep(f"{here}/{_part(Path(path).name)}", text)
    log.keep(f"{here}/records.json", json.dumps(result.get("records", []), ensure_ascii=False, indent=1))
    log.keep(f"{here}/output.txt", result.get("output") or None)
    log.keep(f"{here}/solver.log", result.get("solver") or None)


def run(design_path: Path | str, solver: Solver, window, ws: str,
        max_attempts: int = 3, ledger: Ledger | None = None,
        output: Path | str | None = None, build: bool = True,
        should_stop: Callable[[], bool] = lambda: False, tag: str = "") -> Outcome:
    """`tag` names this design round among a run's files (attempts/<tag>/...)
    when one run goes through more than one design."""
    log = ledger or Ledger(None)
    design_path = Path(design_path)
    # What this run was built from, for whoever reads it later. A run from
    # requirements has already written its own; a run from the app's design
    # gets a copy, since the app's design may change after it.
    try:
        log.keep("design.json", design_path.read_text(encoding="utf-8"), once=True)
        definition_name = json.loads(design_path.read_text(encoding="utf-8")).get("definition")
        if definition_name:
            log.keep("definition.json", (design_path.parent / definition_name).read_text(encoding="utf-8"),
                     once=True)
    except (OSError, ValueError):
        pass                                # the gate below says what is wrong with it

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
        if should_stop():
            log("STOPPED", module=name)
            return Outcome("stopped", "stopped by a person", [m["name"] for m in green])

        # 2a. Generate the tests and run them against the stub.
        # BEGIN marks where a long step starts, so what the loop is doing can
        # be seen while it does it -- not only once the step is over.
        log("BEGIN", step="red_gate", module=name)
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
            if should_stop():
                log("STOPPED", module=name, n=n)
                return Outcome("stopped", "stopped by a person", names)
            here = f"attempts/{tag + '/' if tag else ''}{_part(name)}/{n}"
            if solver == "box":
                # The solver role, in the box: the brief is composed here, on
                # the host, and the window stages, solves and verifies.
                brief = briefs.implement(d, module, feedback)
                log.keep(f"{here}/brief.md", brief)
                log("BEGIN", step="attempt", module=name, n=n)
                result = window.call("attempt", ws, name, {"brief": brief, "green": names})
                files = result.get("files", {})
            else:
                # A stand-in: a function that returns the module's file.
                files = solver(d, module, feedback)
                log("BEGIN", step="attempt", module=name, n=n)
                result = window.call("verify", ws, name, {"files": files, "green": names})
            _keep_attempt(log, here, files, result)
            if "engine" in result:
                log("ATTEMPT", module=name, n=n, stage=diagnose.ENGINE, reason=result["engine"], dir=here)
                return Outcome(diagnose.ENGINE, f"{name}: {result['engine']}", names,
                               detail={"output": result.get("output", "")[-3000:]})
            if "refused" in result:
                verdict = diagnose.Verdict(diagnose.IMPLEMENTATION, result["refused"],
                                           feedback=(result["refused"],),
                                           facts={"built": False, "failed": [], "broke": []})
            else:
                verdict = diagnose.attempt(d, module, result, green)
            if verdict.stage != diagnose.GREEN:
                log.keep(f"{here}/feedback.txt", "\n".join(verdict.feedback))
            log("ATTEMPT", module=name, n=n, stage=verdict.stage, reason=verdict.reason, dir=here,
                **{k: verdict.facts[k] for k in ("failed", "broke", "forbidden", "undeclared")
                   if verdict.facts.get(k)})
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

    names = [m["name"] for m in green]
    log("ALL_GREEN", modules=names)
    if not build:
        return Outcome("done", "every module green (no output built)", names)

    # 3. The output (DESIGN 1): one HTML file that opens as the app. The
    #    window bundles it with the platform's generic shell and opens it once
    #    in happy-dom. Every example is green here, so an app that does not
    #    boot points at the shell or the bundling -- the engine.
    log("BEGIN", step="build")
    built = window.call("build-app", ws, d.assembly["name"], None)
    if "error" in built:
        log("OUTPUT_FAILED", reason=built["error"])
        return Outcome(diagnose.ENGINE, f"building the app: {built['error']}", names,
                       detail={"output": built.get("output", "")[-3000:]})
    boot = built["boot"]
    if not boot.get("ok"):
        log("OUTPUT_FAILED", reason="the app did not boot", boot=boot)
        return Outcome(diagnose.ENGINE, "the app did not boot", names, detail={"boot": boot})
    path = None
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(built["html"], encoding="utf-8")
    log("OUTPUT", path=str(path) if path else None, boot=boot)
    return Outcome("done", "every module green, and the app boots", names,
                   detail={"output": str(path) if path else None, "boot": boot})


# ---- from requirements -------------------------------------------------------
#
# The upstream stages (DESIGN 2): requirements -> definition -> design, each
# written by a role in the box (run-role) and held at the host's gate; then
# run() above; and when run() sends the loop back to the design, the designer
# is told which module and why -- ids and the kind of reason, never what the
# implementation returned -- and the design is written again.

def _on_platform(definition, platform: str) -> list:
    """The definition gate, and the platform the person chose: a definition
    for another platform is refused like any other finding."""
    findings = artifacts.check_definition(definition)
    got = definition.get("shell", {}).get("platform") if isinstance(definition, dict) else None
    if got != platform:
        findings.append(artifacts.Finding(artifacts.DEFINITION, "shell.platform",
                                          f"must be {platform!r}, the platform this app is built for (got {got!r})"))
    return findings


def _write_by_role(window, ws: str, role: str, name: str, brief_for, gate, rounds: int, log,
                   tag: str = "") -> tuple:
    """Ask a role for one JSON file until its gate passes. -> (doc, findings)"""
    findings: list[str] = []
    doc = None
    for n in range(1, rounds + 1):
        here = f"upstream/{tag or role}/{n}"
        brief = brief_for(findings)
        log.keep(f"{here}/brief.md", brief)
        log("BEGIN", step=role, n=n)
        res = window.call("run-role", ws, role, {"brief": brief})
        text = res.get("files", {}).get(name)
        log.keep(f"{here}/{name}", text)
        log.keep(f"{here}/output.txt", res.get("output") or None)
        if text is None:
            findings = [f"{role} wrote no {name} (exit {res.get('code')}); write exactly that file"]
        else:
            try:
                doc = json.loads(text)
                findings = [str(f) for f in gate(doc)]
            except json.JSONDecodeError as e:
                findings = [f"{name} is not JSON: {e}"]
        log(role.upper(), n=n, findings=findings[:20], dir=here)
        if not findings:
            return doc, []
    return doc, findings


def run_from_requirements(requirements: str, workdir: Path | str, window, ws: str,
                          solver: Solver = "box", max_attempts: int = 3, gate_rounds: int = 3,
                          redesigns: int = 2, ledger: Ledger | None = None,
                          output: Path | str | None = None, build: bool = True,
                          should_stop: Callable[[], bool] = lambda: False,
                          platform: str = "browser-dom") -> Outcome:
    log = ledger or Ledger(None)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. The definition, by the definer, held at the definition gate.
    definition, findings = _write_by_role(
        window, f"{ws}-def", "definer", "definition.json",
        lambda f: upstream_briefs.define(requirements, platform=platform, findings=f),
        lambda doc: _on_platform(doc, platform), gate_rounds, log)
    if findings:
        return Outcome(artifacts.DEFINITION, "the definition did not pass its gate",
                       detail={"findings": findings})
    (workdir / "definition.json").write_text(json.dumps(definition, ensure_ascii=False, indent=1),
                                             encoding="utf-8")

    # 2-4. The design, by the designer; then the modules; back to the designer
    #      when the loop says the design is at fault.
    previous, verdict = None, None
    out = Outcome("none", "")
    for round_ in range(redesigns + 1):
        if should_stop():
            log("STOPPED")
            return Outcome("stopped", "stopped by a person")

        def brief(f, prev=previous, v=verdict):
            return upstream_briefs.design(definition, findings=f, previous=prev, verdict=v)

        def gate(ds):
            ds["definition"] = "definition.json"
            return artifacts.check_design(ds, definition)

        design, findings = _write_by_role(window, f"{ws}-des{round_}", "designer", "design.json",
                                          brief, gate, gate_rounds, log, tag=f"designer-r{round_}")
        if findings:
            return Outcome(artifacts.DESIGN, "the design did not pass its gate", detail={"findings": findings})
        design["definition"] = "definition.json"
        (workdir / "design.json").write_text(json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8")
        log("DESIGN_ROUND", round=round_)

        out = run(workdir / "design.json", solver, window, f"{ws}-r{round_}", max_attempts=max_attempts,
                  ledger=log, output=output, build=build, should_stop=should_stop, tag=f"r{round_}")
        if out.stage != diagnose.DESIGN:
            return out
        module = out.reason.split(":", 1)[0]
        previous, verdict = design, {"module": module, **out.detail}
        log("BACK_TO_DESIGN", round=round_, **verdict)
    return out
