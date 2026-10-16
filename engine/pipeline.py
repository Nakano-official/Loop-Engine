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


UNTIL = "until"                       # an Outcome's stage when a run stopped where it was told to


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
        should_stop: Callable[[], bool] = lambda: False, tag: str = "",
        greens: dict | None = None, earlier: dict | None = None) -> Outcome:
    """`tag` names this design round among a run's files (attempts/<tag>/...)
    when one run goes through more than one design.

    `greens`: {fingerprint: files} of implementations that went green before
    -- an earlier design of the same run. A module whose fingerprint is there
    is tried with that implementation first, and only written again if it is
    not green here (DECISIONS 46). Every module that goes green is added.

    `earlier`: {module name: files} of the same: a module whose design changed
    starts from what was green under the earlier one, and is told so. Within
    one design, an attempt after a failed one starts from that one's file."""
    greens = {} if greens is None else greens
    earlier = {} if earlier is None else earlier
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

        # 2a'. What an earlier design had green, if this module is the same:
        #      its tests against that implementation, before any solver.
        fingerprint = d.fingerprint(module)
        kept = greens.get(fingerprint)
        if kept:
            log("BEGIN", step="reuse", module=name)
            result = window.call("verify", ws, name, {"files": kept, "green": [m["name"] for m in green]})
            verdict = diagnose.attempt(d, module, result, green) if "engine" not in result and "refused" not in result \
                else None
            if verdict is not None and verdict.stage == diagnose.GREEN:
                window.call("accept", ws, name, None)
                green.append(module)
                log("REUSED", module=name, reason=verdict.reason)
                log("GREEN", module=name, attempts=0, reused=True)
                continue
            log("REUSE_FAILED", module=name, reason=verdict.reason if verdict else str(result.get("engine")
                                                                                        or result.get("refused")))

        # 2b. Attempts, until green or used up. Each starts from a file to
        #     fix when there is one: what was green under the design before,
        #     then the attempt before (DECISIONS 46).
        attempts: list[diagnose.Verdict] = []
        feedback: tuple = ()
        start_files, start = (earlier.get(name), "earlier") if earlier.get(name) else (None, None)
        for n in range(1, max_attempts + 1):
            names = [m["name"] for m in green]
            if should_stop():
                log("STOPPED", module=name, n=n)
                return Outcome("stopped", "stopped by a person", names)
            here = f"attempts/{tag + '/' if tag else ''}{_part(name)}/{n}"
            if solver == "box":
                # The solver role, in the box: the brief is composed here, on
                # the host, and the window stages, solves and verifies.
                brief = briefs.implement(d, module, feedback, start=start)
                log.keep(f"{here}/brief.md", brief)
                log("BEGIN", step="attempt", module=name, n=n, start=start)
                result = window.call("attempt", ws, name, {
                    "brief": brief, "green": names,
                    **({"start": next(iter(start_files.values()))} if start_files else {})})
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
                   if verdict.facts.get(k)},
                **({"stripped": result["stripped"]} if result.get("stripped") else {}))
            if verdict.stage == diagnose.GREEN:
                window.call("accept", ws, name, None)
                green.append(module)
                greens[fingerprint] = result.get("accepted") or files
                earlier[name] = greens[fingerprint]
                log("GREEN", module=name, attempts=n)
                break
            attempts.append(verdict)
            feedback = verdict.feedback
            last = result.get("accepted") or files
            if last and any(str(t).strip() for t in last.values()):
                start_files, start = last, "previous"      # an empty file is no start: the stub again
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
# The upstream stages (DESIGN 2): requirements -> concepts -> definition (what
# to make, then its examples) -> design, each written by a role in the box
# (run-role) and held at the host's gate; then
# run() above; and when run() sends the loop back to the design, the designer
# is told which module and why -- ids and the kind of reason, never what the
# implementation returned -- and the design is written again.

EDIT_BACK = """
# Your previous {name} is in this directory, at edit/{name}
It is the file the gate refused. Do not write a new {name} from the start: open
edit/{name} and fix each finding above in it with the Edit tool, changing nothing
else. What is in edit/{name} when you finish is what is read.
"""


def _write_by_role(window, ws: str, role: str, name: str, brief_for, gate, rounds: int, log,
                   tag: str = "", start: str | None = None, part: str | None = None) -> tuple:
    """Ask a role for one JSON file until its gate passes. -> (doc, findings)

    `start`: a file the role is to change rather than write -- the design
    the implementation sent back. Staged in its edit/ from the first round;
    the brief says how (DECISIONS 46)."""
    findings: list[str] = []
    doc = None
    refused = None              # the text the gate refused last round, to be fixed in place
    for n in range(1, rounds + 1):
        here = f"upstream/{tag or role}/{n}"
        brief = brief_for(findings)
        payload = {"brief": brief}
        if n == 1 and start is not None:
            payload = {"brief": brief, "stage": {name: start}}
        elif refused is not None:
            # Not written again from nothing: the role gets back what it wrote
            # and fixes the findings in it (the window puts it in its out/edit/).
            # Writing it again cost a whole round of thinking, and could bring
            # new mistakes where nothing was wrong.
            brief += EDIT_BACK.format(name=name)
            payload = {"brief": brief, "stage": {name: refused}}
        log.keep(f"{here}/brief.md", brief)
        log("BEGIN", step=role, n=n, **({"part": part} if part else {}))
        res = window.call("run-role", ws, role, payload)
        text = res.get("files", {}).get(name)
        refused = text
        log.keep(f"{here}/{name}", text)
        log.keep(f"{here}/output.txt", res.get("output") or None)
        log.keep(f"{here}/trace.jsonl", res.get("trace") or None)
        if text is None:
            findings = [f"{role} wrote no {name} (exit {res.get('code')}); write exactly that file"]
        else:
            try:
                doc = json.loads(text)
                findings = [str(f) for f in gate(doc)]
            except json.JSONDecodeError as e:
                findings = [f"{name} is not JSON: {e}"]
        log(role.upper(), n=n, findings=findings[:20], dir=here, **({"part": part} if part else {}),
            **({"usage": res["usage"]} if res.get("usage") else {}))
        if not findings:
            return doc, []
    return doc, findings


def run_from_requirements(requirements: str, workdir: Path | str, window, ws: str,
                          solver: Solver = "box", max_attempts: int = 3, gate_rounds: int = 3,
                          redesigns: int = 2, ledger: Ledger | None = None,
                          output: Path | str | None = None, build: bool = True,
                          should_stop: Callable[[], bool] = lambda: False,
                          platform: str = "browser-dom", until: str | None = None,
                          resume: dict | None = None) -> Outcome:
    """`until`: "analysis", "definition" (with its examples) or "design" --
    stop once that stage has passed its gate, to try one stage without the
    rest. The run is a run like any other (ledger, kept files), so the
    dashboard shows it.

    `resume`: {"from": run id, "concepts": ..., "definition": ...} -- start at
    the design, from a concept file and a definition (with its examples) that
    an earlier run wrote. They are held at their gates again before the
    designer sees them: what passed then must still pass now."""
    log = ledger or Ledger(None)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if resume is not None:
        return _from_definition(requirements, workdir, window, ws, solver, max_attempts, gate_rounds, redesigns,
                                log, output, build, should_stop, platform, until, resume)

    # 0. The concept file, by the analyst, held at its gate (DESIGN 4): what
    #    the request's words mean and what the person needs. The request is put
    #    in by the machine, verbatim -- the one original everyone reads.
    def concepts_gate(doc):
        if isinstance(doc, dict):
            doc["request"] = requirements.strip()
        return artifacts.check_concepts(doc)

    concepts, findings = _write_by_role(
        window, f"{ws}-ana", "analyst", "concepts.json",
        lambda f: upstream_briefs.analyze(requirements, findings=f), concepts_gate, gate_rounds, log)
    if findings:
        return Outcome(artifacts.ANALYSIS, "the concept file did not pass its gate", detail={"findings": findings})
    (workdir / "concepts.json").write_text(json.dumps(concepts, ensure_ascii=False, indent=1), encoding="utf-8")
    if until == "analysis":
        log("UNTIL", stage="analysis")
        return Outcome(UNTIL, "stopped after the analysis, as asked")

    # 1. The definition, by the definer: what to make, decided against the
    #    concept file -- the summary, the state, item by item what must hold
    #    (DECISIONS 44). The platform's types and functions are the machine's.
    draft, findings = _write_by_role(
        window, f"{ws}-def", "definer", "definition.json",
        lambda f: upstream_briefs.define(concepts, platform=platform, findings=f),
        lambda doc: artifacts.check_draft(doc, platform, concepts), gate_rounds, log)
    if findings:
        return Outcome(artifacts.DEFINITION, "the definition did not pass its gate",
                       detail={"findings": findings})
    definition = artifacts.complete(draft, platform)

    # The examples are the designer's now, with the assembly: what each item
    # is checked by, held to the concept file by the coverage gate on the
    # design (DECISIONS 48).
    (workdir / "definition.json").write_text(json.dumps(definition, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    if until == "definition":
        log("UNTIL", stage="definition")
        return Outcome(UNTIL, "stopped after the definition, as asked")
    return _design_and_build(concepts, definition, workdir, window, ws, solver, max_attempts, gate_rounds,
                             redesigns, log, output, build, should_stop, until)


def _conditions_read(window, ws: str, examples: list) -> list[str]:
    """The conditions among `examples`, read in the box (parsed, never run
    here on the host). Whether one is strong enough is the loop's to see."""
    conditions = artifacts.conditions_in(examples)
    if not conditions:
        return []
    read = window.call("check-conditions", ws, "typescript", {"conditions": conditions})
    if "engine" in read or "error" in read:
        raise RuntimeError(f"check-conditions: {read.get('engine') or read.get('error')}")
    return [f"[{artifacts.DESIGN}] examples[{eid}].holds: {why}" for eid, why in sorted(read.get("findings", {}).items())]


def _design_in_parts(window, ws: str, concepts: dict, definition: dict, gate_rounds: int, log, round_: int,
                     previous: dict | None, verdict: dict | None) -> tuple:
    """The designer, in parts (DECISIONS 47): first the plan -- the modules,
    what each depends on, their contracts and what each function does --
    then one call per module for how it works and its examples. Sent back by
    the implementation, it changes the plan where the verdict points, and only
    the modules whose plan entry changed (and the one the verdict names) are
    written again; the rest keep what they had (DECISIONS 46). -> (design, findings)"""
    def plan_gate(doc):
        if isinstance(doc, dict):
            doc["definition"] = "definition.json"
        return artifacts.check_plan(doc, definition)

    plan, findings = _write_by_role(
        window, f"{ws}-des{round_}-plan", "designer", "design.json",
        lambda f: upstream_briefs.design_plan(definition, concepts, findings=f, verdict=verdict,
                                             editing=previous is not None),
        plan_gate, gate_rounds, log, tag=f"designer-r{round_}/plan", part="plan",
        start=json.dumps(artifacts.plan_of(previous), ensure_ascii=False, indent=1) if previous else None)
    if findings:
        return None, findings
    plan["definition"] = "definition.json"

    old = {m["name"]: m for m in (previous or {}).get("modules", [])}
    old_plan = {m["name"]: m for m in artifacts.plan_of(previous).get("modules", [])} if previous else {}
    design = json.loads(json.dumps(plan))
    design["fixtures"] = {}
    for module in plan["modules"]:
        name = module["name"]
        kept = old.get(name)
        unchanged = kept is not None and old_plan.get(name) == module and (verdict or {}).get("module") != name
        if unchanged:
            part = {"functions": {fn: {"doc": sig.get("doc")} for fn, sig in kept["functions"].items()},
                    "examples": kept.get("examples", []),
                    "fixtures": {k: v for k, v in (previous.get("fixtures") or {}).items()
                                 if k in json.dumps(kept.get("examples", []))}}
            design = artifacts.with_module(design, name, part)
            log("KEPT", module=name, round=round_)
            continue

        def gate(doc, name=name, design=design, module=module):
            found = [str(f) for f in artifacts.check_module(design, definition, name, doc)]
            if not found and module["kind"] == "assembly":
                # The items are checked here: every property and requirement
                # the concept file checks by example is shown by one of the
                # assembly's examples (DECISIONS 48).
                found = [str(f) for f in artifacts.check_design_coverage(concepts, doc.get("examples") or [])]
            return found or _conditions_read(window, f"{ws}-des", list(doc.get("examples") or []))

        part, findings = _write_by_role(
            window, f"{ws}-des{round_}-{name.replace('_', '-')}", "designer", "module.json",
            lambda f, name=name, design=design: upstream_briefs.design_module(design, name, definition, concepts,
                                                                                findings=f),
            gate, gate_rounds, log, tag=f"designer-r{round_}/{name}", part=name)
        if findings:
            return None, findings
        design = artifacts.with_module(design, name, part)
    findings = [str(f) for f in artifacts.check_design(design, definition)]
    return design, findings


def _from_definition(requirements, workdir, window, ws, solver, max_attempts, gate_rounds, redesigns, log,
                     output, build, should_stop, platform, until, resume) -> Outcome:
    """The design onwards, from what an earlier run left (`resume`)."""
    concepts, definition = resume["concepts"], resume["definition"]
    found = [str(f) for f in artifacts.check_concepts(concepts)]
    found += [str(f) for f in artifacts.check_definition(definition)]
    got = definition.get("shell", {}).get("platform") if isinstance(definition, dict) else None
    if got != platform:
        found.append(f"the definition is for {got!r}, the app for {platform!r}")
    if found:
        log("FROM", run=resume.get("from"), findings=found[:20])
        return Outcome(artifacts.DEFINITION, f"what {resume.get('from')} left does not pass its gates",
                       detail={"findings": found})
    for name, doc in (("concepts.json", concepts), ("definition.json", definition)):
        (workdir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    log("FROM", run=resume.get("from"), stages=["analysis", "definition"])
    if until in ("analysis", "definition"):
        log("UNTIL", stage=until)
        return Outcome(UNTIL, f"stopped after the {until}, as asked")
    return _design_and_build(concepts, definition, workdir, window, ws, solver, max_attempts, gate_rounds,
                             redesigns, log, output, build, should_stop, until)


def _design_and_build(concepts, definition, workdir, window, ws, solver, max_attempts, gate_rounds, redesigns,
                      log, output, build, should_stop, until) -> Outcome:
    # 2-4. The design, by the designer; then the modules; back to the designer
    #      when the loop says the design is at fault.
    previous, verdict = None, None
    out = Outcome("none", "")
    greens: dict = {}                    # what went green, by fingerprint, for the next design
    earlier: dict = {}                   # ... and by module name, to start from when it changed
    for round_ in range(redesigns + 1):
        if should_stop():
            log("STOPPED")
            return Outcome("stopped", "stopped by a person")

        design, findings = _design_in_parts(window, ws, concepts, definition, gate_rounds, log, round_,
                                            previous, verdict)
        if findings:
            return Outcome(artifacts.DESIGN, "the design did not pass its gate", detail={"findings": findings})
        design["definition"] = "definition.json"
        (workdir / "design.json").write_text(json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8")
        log("DESIGN_ROUND", round=round_)
        if until == "design":
            log("UNTIL", stage="design")
            return Outcome(UNTIL, "stopped after the design, as asked")

        out = run(workdir / "design.json", solver, window, f"{ws}-r{round_}", max_attempts=max_attempts,
                  ledger=log, output=output, build=build, should_stop=should_stop, tag=f"r{round_}",
                  greens=greens, earlier=earlier)
        if out.stage != diagnose.DESIGN:
            return out
        module = out.reason.split(":", 1)[0]
        previous, verdict = design, {"module": module, **out.detail}
        log("BACK_TO_DESIGN", round=round_, **verdict)
    return out
