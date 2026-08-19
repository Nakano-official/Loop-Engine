#!/usr/bin/env python3
"""The loop runner -- v1, deliberately disposable.

    sudo -u runner python3 /srv/loop/runner/loop.py run <step-id>

This is the enforcement layer described in RUNNER_SPEC. It is an ordinary
program, not an agent, and that is the whole point: a gate is worth something
precisely because it does not exercise judgement. Nothing here decides whether a
failure is "close enough".

The phases (RUNNER_SPEC section 3):

    PLAN_LOAD -> TEST_WRITE -> STUB -> RED_GATE -> FREEZE -> IMPL <-> VERIFY -> GREEN

REVIEW_GATE is not implemented in v1; it is a human step and would block the
first end-to-end run. Its absence is written to the ledger on every step rather
than left implicit, so a green produced without review is never mistaken for one
that passed review.

Standard library only. It runs as `runner`, which owns the repository and holds
the one sudo exception that lets it start the solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

LOOP = Path("/srv/loop")
PROJECT = LOOP / "project"
PLAN = PROJECT / "plan"
TESTS = PROJECT / "tests"
SRC = PROJECT / "src"
STATE = PROJECT / ".runner"
BRIEF_DIR = LOOP / "brief"
PYTEST = PROJECT / ".venv" / "bin" / "pytest"
SOLVER_RUN = LOOP / "bin" / "solver-run"
PLANNER_RUN = LOOP / "bin" / "planner-run"
PLANNER_BRIEF = LOOP / "planner" / "brief"
PLANNER_OUT = LOOP / "planner" / "out"

# The human's own channel, and the one the planner cannot write. The
# requirements that start a project arrive here, and later so will the answers
# to escalations -- both are things only a person may say. It is the mirror of
# /srv/loop/planner/out: same shape, opposite direction, different group.
HUMAN_IN = LOOP / "human" / "in"
REQUIREMENTS = HUMAN_IN / "REQUIREMENTS.md"

# The three files the planner may write (BOOTSTRAP, "書いてよいのは次の3つだけ"),
# as a map from the name it writes in out/ to where that file lives in the
# project. This mapping is the allowlist: a proposal cannot name a fourth file
# because there is no fourth entry to send it to.
#
# SYSTEM_SPEC.md lives under plan/ rather than at the repository root, which is
# a deviation from BOOTSTRAP's file table and a deliberate one. The root is
# readable by the solver -- it has to be, it works there -- so a spec sitting in
# it would be a second input channel next to the brief, and the whole design of
# the system would be readable from inside a step that was handed one contract.
# plan/ is 0700 runner, so putting it there costs nothing and closes that.
SYSTEM_SPEC = PLAN / "SYSTEM_SPEC.md"
PROPOSAL_FILES = {
    "SYSTEM_SPEC.md": SYSTEM_SPEC,
    "CONTEXT.md": PLAN / "CONTEXT.md",
    "tasks.json": PLAN / "tasks.json",
}
# ...and the one thing the planner may write that is never applied anywhere: its
# way of saying "this is case (b) or (c), so it is not mine to decide".
ESCALATE_NAME = "ESCALATE.md"

LEDGER = PLAN / "ledger.jsonl"
ESCALATION = PLAN / "ESCALATION.md"

# tests/ must be run with the project venv's pytest and nothing else. A plain
# `python3 -m pytest` would put the solver's own ~/.local packages back on
# sys.path, and that is the single mechanism keeping "when stuck, pip install"
# from working (RUNNER_SPEC 1-3).
PYTEST_ARGS = ["-q", "-p", "no:cacheprovider", "--strict-markers"]

# RUNNER_SPEC section 11 leaves these open. Fixed values to start from, both
# overridable per plan via a top-level "timeouts" object in tasks.json.
#
# A test run that never returns is the expected failure here: an implementation
# with an infinite loop is an ordinary thing for a solver to write, and without a
# ceiling the runner waits for it forever.
#
# The solver's own ceiling lives in solver-run, not here. The runner cannot kill
# a process belonging to another uid, so a timeout enforced only on this side
# would leave the agent running with nothing able to stop it. This value is a
# backstop and is deliberately longer than the one solver-run applies.
TIMEOUTS = {"test": 120, "solver": 960, "planner": 960}

# RUNNER_SPEC 6-2. BOOTSTRAP 1-4 caps the ATTEMPTS inside a step but says nothing
# about the loop outside it, so a planner answering (a) over and over is
# unbounded -- and (a) is the answer a planner will keep reaching for, because it
# is the only one it is allowed to give.
#
# The spec's rule is: from the second escalation on a step, (a) is off the table
# and only (b) or (c) remain, both of which are the human's. So the planner
# answers exactly one escalation per step. Overridable per plan via a top-level
# "limits" object, for the same reason the timeouts are.
#
# "revisions" is a different ceiling for a different failure: the planner is
# handed the linter's verdict and asked to fix it, and an agent that trades one
# violation for another would otherwise do so forever. Three is enough that a
# plan which merely misunderstood the layout converges, and few enough that one
# which cannot satisfy the rules stops costing money.
LIMITS = {"escalations": 1, "revisions": 3}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


class Halt(Exception):
    """Stop the step. Carries the reason that goes into the ledger."""

    def __init__(self, phase: str, reason: str, detail: str = ""):
        super().__init__(reason)
        self.phase = phase
        self.reason = reason
        self.detail = detail


def run(cmd: list[str], cwd: Path = PROJECT, check: bool = False,
        env: dict[str, str] | None = None,
        timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
        env=({**os.environ, **env} if env else None),
        timeout=timeout,
    )


def source_files(path: Path):
    """Every file under `path` except compiled bytecode.

    __pycache__ matters here for a reason that is not obvious: whichever account
    ran the interpreter owns those .pyc files, so a stray one written by the
    solver cannot be chmod'ed by the runner at all. Bytecode is disabled for the
    runner's own pytest invocations as well (see pytest_run); this skip covers
    anything left behind by something else.
    """
    for child in path.rglob("*"):
        if child.is_file() and "__pycache__" not in child.parts:
            yield child


def ledger(event: str, **fields) -> None:
    """Append-only. The ledger is how a step is resumed after the VM dies, and
    under WSL2 that is a matter of when, not if (RUNNER_SPEC 1-6)."""
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **fields}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[{event}] " + " ".join(f"{k}={v}" for k, v in fields.items() if k != "detail"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# the write fence
# --------------------------------------------------------------------------


def set_writable(*, tests: bool | None, src: bool | None) -> None:
    """Grant the solver write access to exactly one of tests/ or src/.

    This is the files_write allowlist as a mechanism rather than an instruction.
    It is coarse -- directory granularity, not per-file -- so `assert_touched`
    below checks the exact paths afterwards. Coarse mechanism plus exact
    assertion beats a fine-grained mechanism that only exists in the prompt.

    `None` means "leave this directory exactly as it is". After FREEZE that is
    the only correct value for tests/: re-applying a mode there, even a
    restrictive one, would hand the write bit back to the owner and quietly
    undo the thing FREEZE just established.
    """
    for path, writable in ((TESTS, tests), (SRC, src)):
        if writable is None:
            continue
        if writable:
            shutil.chown(path, group="solverw")
            path.chmod(0o2775)
            for child in source_files(path):
                child.chmod(0o664)
        else:
            path.chmod(0o2755)
            for child in source_files(path):
                child.chmod(0o444)


def adopt(*dirs: Path) -> list[str]:
    """Take ownership of whatever the solver just wrote.

    A file the solver creates is owned by `solver`, and the runner cannot chmod
    a file it does not own -- so without this step the write fence can be opened
    and never closed again. `chown` would fix it and needs root, which the runner
    deliberately does not have.

    Rewriting the file through the runner gets the same result with no privilege
    at all: the enclosing directories are runner-owned, which is what makes the
    unlink legal, and the file that reappears belongs to the runner. Content is
    byte-identical, so git sees nothing and the freeze manifest is unaffected.
    """
    me = os.getuid()
    adopted = []
    for directory in dirs:
        for f in source_files(directory):
            if f.stat().st_uid != me:
                data = f.read_bytes()
                f.unlink()
                f.write_bytes(data)
                f.chmod(0o664)
                adopted.append(str(f.relative_to(PROJECT)))
    return adopted


def freeze_tests() -> dict[str, str]:
    """FREEZE (RUNNER_SPEC 4-3). chmod is the mechanism; the manifest returned
    here is a tripwire on top of it, not the thing doing the work."""
    shutil.chown(TESTS, group="runner")
    TESTS.chmod(0o2555)
    manifest = {}
    for f in sorted(TESTS.rglob("*.py")):
        f.chmod(0o444)
        manifest[str(f.relative_to(PROJECT))] = sha256(f)
    return manifest


# --------------------------------------------------------------------------
# git-based change detection
# --------------------------------------------------------------------------


# plan/ and .runner/ are 0700 runner. The solver cannot write there, so a change
# under them is by definition the runner's own -- the ledger it just appended to,
# the junit report it just produced. Counting those as solver activity would make
# every step fail on its own bookkeeping.
RUNNER_OWNED = ("plan/", ".runner/")


def touched_paths() -> set[str]:
    out = run(["git", "status", "--porcelain", "--untracked-files=all"]).stdout
    paths = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        # "XY path" or "XY old -> new"
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path.startswith(RUNNER_OWNED):
            continue
        paths.add(path)
    return paths


def assert_touched(phase: str, allowed: list[str]) -> None:
    """The solver may have written only where the step said it could.

    Note what this does NOT do: it does not ask the solver what it changed. The
    question is answered by git, which the solver cannot reach (.git is 0700
    runner).
    """
    allowed_set = set(allowed)
    actual = touched_paths()
    stray = sorted(actual - allowed_set)
    if stray:
        raise Halt(
            phase,
            "solver wrote outside its allowlist",
            "wrote: " + ", ".join(stray) + "\nallowed: " + ", ".join(sorted(allowed_set)),
        )


# --------------------------------------------------------------------------
# running the tests
# --------------------------------------------------------------------------


@dataclass
class TestRun:
    tests: int
    failures: int
    errors: int
    skipped: int
    failure_kinds: list[str]
    passed_names: list[str]
    output: str

    @property
    def green(self) -> bool:
        return self.tests > 0 and self.failures == 0 and self.errors == 0


# R5: only a genuine assertion counts as red. An ImportError or a collection
# error means the stub is broken, which looks like red and means something else
# entirely -- accepting it would let a step "pass" RED_GATE without ever having
# had a working test.
RED_KINDS = re.compile(r"^(AssertionError|Failed)\b")


def pytest_run(tag: str, files_test: list[str]) -> TestRun:
    """RUNNER_SPEC section 4: the verdict is read from the junit XML, never from
    the exit code. Only the step's own test files are run, so an unrelated test
    elsewhere in the tree can neither rescue nor sink this step's gate."""
    STATE.mkdir(parents=True, exist_ok=True)
    xml_path = STATE / f"pytest-{tag}.xml"
    # No bytecode: a .pyc is owned by whoever wrote it, and a solver-owned one
    # under tests/ makes the runner unable to re-apply modes there at all.
    try:
        proc = run([PYTEST, *files_test, *PYTEST_ARGS, "--junitxml", str(xml_path)],
                   env={"PYTHONDONTWRITEBYTECODE": "1"},
                   timeout=TIMEOUTS["test"])
    except subprocess.TimeoutExpired:
        # Reported as an error rather than a failure, which is what it is: the
        # suite produced no verdict at all. R2 rejects it outright at RED_GATE,
        # and VERIFY counts it as a failed attempt and tells the solver why.
        seconds = TIMEOUTS["test"]
        return TestRun(0, 0, 1, 0, [f"<timeout: no verdict after {seconds}s>"], [],
                       f"The test run did not terminate within {seconds}s. The most "
                       f"likely cause is a loop in the implementation that never exits.")
    output = proc.stdout + proc.stderr

    if not xml_path.exists():
        return TestRun(0, 0, 1, 0, ["<no junit report: pytest did not start>"], [], output)

    suite = ET.parse(xml_path).getroot().find("testsuite")
    if suite is None:
        return TestRun(0, 0, 1, 0, ["<malformed junit report>"], [], output)

    kinds: list[str] = []
    passed: list[str] = []
    for case in suite.iter("testcase"):
        failures = case.findall("failure")
        problems = failures + case.findall("error") + case.findall("skipped")
        if not problems:
            passed.append(case.get("name") or "<unnamed>")
        for failure in failures:
            # R5 keys off the exception type. The message is a fallback for
            # junit writers that omit the attribute.
            kinds.append(failure.get("type")
                         or (failure.get("message") or "").strip().splitlines()[0]
                         or "<no type>")

    return TestRun(
        tests=int(suite.get("tests", 0)),
        failures=int(suite.get("failures", 0)),
        errors=int(suite.get("errors", 0)),
        skipped=int(suite.get("skipped", 0)),
        failure_kinds=kinds,
        passed_names=passed,
        output=output,
    )


# --------------------------------------------------------------------------
# calling the solver
# --------------------------------------------------------------------------


def call_solver(phase: str, brief: str) -> str:
    """Hand the solver one brief and nothing else.

    The brief is written to /srv/loop/brief (runner:solverw 0750): the solver can
    read it and cannot write it, and it is the only channel that exists. There is
    no path from here to plan/, which is 0700 runner -- so "the solver must not
    read tasks.json" is not a rule anyone has to follow.
    """
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    brief_path = BRIEF_DIR / f"{phase.lower()}.md"
    brief_path.write_text(brief, encoding="utf-8")
    # Set the group explicitly rather than trusting the directory's setgid bit.
    # A brief the solver cannot read fails as "solver exited 2" -- true, useless,
    # and three layers away from a missing group.
    shutil.chown(brief_path, group="solverw")
    brief_path.chmod(0o640)

    try:
        proc = run(["sudo", "-u", "solver", str(SOLVER_RUN), str(brief_path)],
                   timeout=TIMEOUTS["solver"])
    except subprocess.TimeoutExpired:
        # Reaching this means solver-run's own, shorter ceiling did not fire.
        # Killing the agent from here is not possible -- it belongs to another
        # uid and the runner has no sudo for that -- so say so plainly instead of
        # implying the process is gone.
        raise Halt(phase, f"solver still running after {TIMEOUTS['solver']}s",
                   "solver-run's internal timeout did not fire; a solver process "
                   "may still be alive. Check with: pgrep -a -u solver")
    out = proc.stdout + proc.stderr
    if proc.returncode == 124:
        raise Halt(phase, "solver hit its own timeout in solver-run", out[-4000:])
    if proc.returncode != 0:
        raise Halt(phase, f"solver exited {proc.returncode}", out[-4000:])

    # Adopt before anything else looks at the tree: from here on the runner must
    # be able to re-apply modes, and it can only do that to files it owns.
    taken = adopt(TESTS, SRC)
    if taken:
        ledger("ADOPT", phase=phase, files=taken)
    return out


# --------------------------------------------------------------------------
# briefs (RUNNER_SPEC section 5)
# --------------------------------------------------------------------------


def dep_contracts(step: dict) -> str:
    parts = []
    for dep in step.get("depends_on", []):
        path = STATE / "contracts" / f"{dep}.json"
        if not path.exists():
            raise Halt("PLAN_LOAD", f"step {step['id']} depends on {dep}, which has no contract yet")
        parts.append(f"From {dep}:\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts) if parts else "(none -- this step depends on nothing)"


def render_acceptance(step: dict) -> str:
    return "\n".join(
        f"{i}. [{a['case']}] given {a['given']} then {a['then']}"
        for i, a in enumerate(step["acceptance"], 1)
    )


def render_provides(step: dict) -> str:
    return "\n".join(step["contracts"]["provides"])


def render_invariants(step: dict) -> str:
    inv = step["contracts"].get("invariants") or []
    return "\n".join(f"- {i}" for i in inv) if inv else "(none stated)"


def brief_test_write(step: dict, context: str) -> str:
    # No goal. The tests must come from the acceptance criteria, not from a
    # description of the implementation the solver is about to be asked for.
    acceptance = render_acceptance(step)
    return f"""Write tests. Do not write an implementation.

# Project context
{context}

# Contracts you may rely on
{dep_contracts(step)}

# Invariants that must hold
{render_invariants(step)}

# Acceptance criteria -- write exactly {step["expected_tests"]} tests, at least one per criterion
{acceptance}

# Signatures under test
{render_provides(step)}

# Files you may create or modify
{chr(10).join(step["files_test"])}

Write nothing outside those paths. The implementation does not exist yet, so
every test you write must fail when run against a stub that returns a wrong
value of the right type. Do not weaken a test to make it pass, and do not
create the module under test.
"""


def brief_stub(step: dict) -> str:
    # Signatures only -- no goal, no acceptance, and no invariants. Anything
    # here that carries meaning rather than shape gets faithfully implemented,
    # and the criterion it covers then passes at RED_GATE without ever having
    # been observed to fail (found the hard way on step S1, 2026-08-18).
    return f"""Create stubs only.

# Signatures to provide
{render_provides(step)}

# Files you may create or modify
{chr(10).join(step["files_write"])}

Each function must have exactly the signature above and must return a
CONSPICUOUS SENTINEL: a value of the declared return type that no correct
implementation would produce for any input. For a str return a marker such as
"__stub__"; for an int something like -999999; for a list a list holding one
such marker.

Do NOT return an empty, zero, or default value ("", 0, [], None), and do not
return an argument unchanged. Those are answers a correct implementation gives
for some input, so a test covering that input would pass against the stub -- and
a test that passes here has never shown it can fail, which rejects the step.

Implement no behaviour whatsoever: no validation, no type checks, no special
cases, no branching on the input. Do not raise NotImplementedError; the tests
must fail on an assertion, not on an exception.
"""


def brief_impl(step: dict, context: str, tests_text: str, last_failure: str) -> str:
    return f"""Make the tests pass.

# Project context
{context}

# Goal
{step["goal"]}

# Signatures you must provide
{render_provides(step)}

# Invariants that must hold
{render_invariants(step)}

# Contracts you may rely on
{dep_contracts(step)}

# The tests (frozen -- read-only, and they will not be accepted if modified)
{tests_text}

# What failed on the previous attempt
{last_failure or "(this is the first attempt)"}

# Files you may create or modify
{chr(10).join(step["files_write"])}

Change nothing outside those paths. The tests are the specification: if a test
looks wrong, say so in your final message rather than editing it -- editing it
will be detected and the step will stop.
"""


def frozen_tests_text(step: dict) -> str:
    parts = []
    for rel in step["files_test"]:
        path = PROJECT / rel
        parts.append(f"--- {rel} ---\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# escalation
# --------------------------------------------------------------------------


def escalation_count(step_id: str) -> int:
    """How many times this step has already escalated, read from the ledger.

    From the ledger and not from a counter in memory, because the point of the
    cap is to survive the things that end the process: the VM stopping, a reset,
    a run resumed tomorrow. This is also why `reset` had to stop rolling the
    ledger back -- a cap counted from records that reset destroys is not a cap.
    """
    if not LEDGER.exists():
        return 0
    n = 0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") == "ESCALATED" and rec.get("step") == step_id:
            n += 1
    return n


def escalate(step: dict, halt: Halt, attempt: int, run_: TestRun | None) -> None:
    failed = "\n".join(f"- {k}" for k in (run_.failure_kinds if run_ else [])) or "(none recorded)"
    n = escalation_count(step["id"]) + 1          # including this one
    cap = LIMITS["escalations"]

    # RUNNER_SPEC 6-2 requires this constraint to be stated in the file itself,
    # so that it holds even if whoever reads it has forgotten the rule. It is
    # also enforced in cmd_run_all, which does not ask.
    if n > cap:
        constraint = f"""- This is escalation {n} of at most {cap} for this step, so **(a) is no
  longer available**. Only (b) rewriting the acceptance criteria, or (c)
  rebuilding from further upstream -- and both of those are the human's
  decision, not the planner's (RUNNER_SPEC 6-2).
- If (c) is chosen, name every green step that has to be discarded."""
    else:
        constraint = f"""- The acceptance criteria for this step must NOT be weakened.
- This is escalation {n} of at most {cap} for this step. Permitted responses are
  (a) tighten the goal, or escalate. Rewriting the acceptance criteria is case
  (b) and is a decision for the human, not the planner (RUNNER_SPEC 6-2)."""

    ESCALATION.write_text(
        f"""# ESCALATION: step {step["id"]}

## Facts
- phase: {halt.phase}
- reason: {halt.reason}
- attempt: {attempt} of {step.get("max_attempts", 3)}
- escalation: {n} of {cap}

## Failing tests
{failed}

## Detail
```
{halt.detail[-4000:]}
```

## Constraints on the planner
{constraint}
""",
        encoding="utf-8",
    )
    ledger("ESCALATED", step=step["id"], phase=halt.phase, reason=halt.reason,
           escalation_no=n)
    print(f"\nESCALATION written to {ESCALATION}", file=sys.stderr)


# --------------------------------------------------------------------------
# the step
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# the plan linter (RUNNER_SPEC section 8)
# --------------------------------------------------------------------------

# The name a contract line declares. Both keywords matter: a step that
# introduces the data model provides `class GameState(...)`, and matching only
# `def` made every later step's `requires` fail L3 against a name the linter
# could not see. Found the first time a real plan had a data-model step.
PROVIDES_NAME = re.compile(r"(?:def|class)\s+([A-Za-z_]\w*)")
# "concrete" for L8: a number, a quoted literal, or an exception type. An
# acceptance criterion made only of adjectives cannot be turned into a test that
# two people would write the same way.
CONCRETE = re.compile(r"\d|'[^']*'|\"[^\"]*\"|\b[A-Z]\w*(?:Error|Exception)\b")

CASES = {"normal", "boundary", "error"}
REQUIRED_KEYS = {
    "id": str, "kind": str, "goal": str, "depends_on": list, "acceptance": list,
    "contracts": dict, "files_write": list, "files_test": list,
    "expected_tests": int, "max_attempts": int, "review_gate": bool,
}


def validate_plan(tasks: dict) -> list[str]:
    """Return every violation. The planner's output is checked before it is
    obeyed -- this is the only objective gate on the planning side, and it runs
    without calling any model."""
    problems: list[str] = []
    steps = tasks.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["L1: tasks.json has no non-empty `steps` array"]

    # L1 -- shape
    for i, s in enumerate(steps):
        where = f"step[{i}]" if not isinstance(s.get("id"), str) else f"step {s['id']}"
        for key, typ in REQUIRED_KEYS.items():
            if key not in s:
                problems.append(f"L1: {where} is missing `{key}`")
            elif not isinstance(s[key], typ) or (typ is int and isinstance(s[key], bool)):
                problems.append(f"L1: {where}.{key} must be {typ.__name__}")
        if s.get("kind") not in ("unit", "integration"):
            problems.append(f"L1: {where}.kind must be 'unit' or 'integration'")
        for a in s.get("acceptance", []):
            if not isinstance(a, dict) or {"case", "given", "then"} - a.keys():
                problems.append(f"L1: {where} has an acceptance entry without case/given/then")
            elif a["case"] not in CASES:
                problems.append(f"L1: {where} acceptance case '{a['case']}' is not one of {sorted(CASES)}")
        if not isinstance(s.get("contracts", {}).get("provides"), list):
            problems.append(f"L1: {where}.contracts.provides must be a list of signature strings")

    if problems:
        return problems  # later rules assume the shape holds

    ids = [s["id"] for s in steps]
    seen: set[str] = set()
    provides_by_step = {
        s["id"]: {m.group(1) for p in s["contracts"]["provides"] if (m := PROVIDES_NAME.search(p))}
        for s in steps
    }

    for s in steps:
        sid = s["id"]

        # L2 -- dependencies point backwards only, so cycles cannot exist
        for dep in s["depends_on"]:
            if dep not in seen:
                problems.append(f"L2: step {sid} depends on {dep}, which is not an earlier step")
        seen.add(sid)

        # L3 -- everything required is provided by something it depends on
        available = set().union(*(provides_by_step[d] for d in s["depends_on"] if d in provides_by_step)) \
            if s["depends_on"] else set()
        for req in s["contracts"].get("requires", []):
            name = m.group(1) if (m := PROVIDES_NAME.search(req)) else req
            if name not in available:
                problems.append(f"L3: step {sid} requires `{name}`, which no dependency provides")

        # L5 -- a file is either written or tested, never both
        overlap = set(s["files_write"]) & set(s["files_test"])
        if overlap:
            problems.append(f"L5: step {sid} lists {sorted(overlap)} in both files_write and files_test")

        # L12 -- the write fence only covers src/ and tests/
        #
        # set_writable() chmods exactly those two directories, and adopt() walks
        # exactly those two. A step that writes anywhere else is not fenced at
        # all: the workspace root is group-writable (the solver's patch tool
        # needs it), so the solver could create a package beside src/ and write
        # to it during the phase where writing code is supposed to be
        # impossible. assert_touched would still catch it afterwards, but that
        # turns the primary mechanism into a tripwire, and files created there
        # stay solver-owned -- which the runner can neither chmod nor clean up.
        #
        # A first plan gets this wrong by default, because "put the package at
        # the repository root" is ordinary Python layout. So it is a rule the
        # linter holds, not advice in a brief.
        for f in s["files_write"]:
            if not f.startswith("src/"):
                problems.append(f"L12: step {sid} writes {f}, which is outside src/")
        for f in s["files_test"]:
            if not f.startswith("tests/"):
                problems.append(f"L12: step {sid} tests {f}, which is outside tests/")

        # L6 -- normal, boundary and error are all covered
        missing = CASES - {a["case"] for a in s["acceptance"]}
        if missing:
            problems.append(f"L6: step {sid} has no acceptance case of type {sorted(missing)}")

        # L7
        if s["expected_tests"] < len(s["acceptance"]):
            problems.append(
                f"L7: step {sid} expects {s['expected_tests']} tests for "
                f"{len(s['acceptance'])} acceptance criteria")

        # L8 -- skipping human review requires criteria a machine can check
        if not s["review_gate"]:
            for a in s["acceptance"]:
                if not CONCRETE.search(a["given"] + " " + a["then"]):
                    problems.append(
                        f"L8: step {sid} has review_gate false but the [{a['case']}] criterion "
                        f"states no concrete value")

    # L4 -- one owner per file, across the whole plan
    owners: dict[str, str] = {}
    for s in steps:
        for f in s["files_write"]:
            if f in owners:
                problems.append(f"L4: {f} is written by both {owners[f]} and {s['id']}")
            owners[f] = s["id"]

    # L9 / L10 -- a walking skeleton early, and a join at the end
    kinds = [s["kind"] for s in steps]
    if "integration" not in kinds[:3]:
        problems.append("L9: no integration step within the first three steps")
    if kinds[-1] != "integration":
        problems.append("L10: the final step is not an integration step")

    # L11 -- nothing is built that nothing uses. Integration steps are exempt:
    # tying the pieces together is the deliverable, not an input to a later step.
    used = set().union(*[
        {m.group(1) if (m := PROVIDES_NAME.search(r)) else r for r in s["contracts"].get("requires", [])}
        for s in steps
    ]) if steps else set()
    for s in steps:
        if s["kind"] == "integration":
            continue
        for name in provides_by_step[s["id"]] - used:
            problems.append(f"L11: step {s['id']} provides `{name}`, which no step requires")

    return problems


def load_plan(step_id: str) -> tuple[dict, str]:
    tasks = json.loads((PLAN / "tasks.json").read_text(encoding="utf-8"))
    steps = {s["id"]: s for s in tasks["steps"]}
    if step_id not in steps:
        raise Halt("PLAN_LOAD", f"no step {step_id} in tasks.json")
    context = (PLAN / "CONTEXT.md").read_text(encoding="utf-8")
    return steps[step_id], context


# --------------------------------------------------------------------------
# the planner channel (BOOTSTRAP 1-4, RUNNER_SPEC section 2)
# --------------------------------------------------------------------------


def canon(obj) -> str:
    """Order-independent comparison key. Reindenting tasks.json must not read as
    a change, and reordering the keys of a step must not read as one either."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def green_steps() -> set[str]:
    """Step ids that have already gone green, read from the ledger."""
    done: set[str] = set()
    if not LEDGER.exists():
        return done
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") == "GREEN" and rec.get("step"):
            done.add(rec["step"])
    return done


def clear_proposal() -> None:
    """Empty out/ before asking for a new proposal.

    A leftover file from a previous call would otherwise be applied as if the
    planner had just written it. The runner can do this despite the files
    belonging to `planner`: out/ is sticky, and sticky permits deletion by the
    owner of the file OR the owner of the directory, which is the runner.
    """
    PLANNER_OUT.mkdir(parents=True, exist_ok=True)
    for entry in PLANNER_OUT.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            raise Halt("PLAN_PROPOSE",
                       f"a directory is in the way in {PLANNER_OUT}: {entry.name}",
                       "Remove it by hand; the runner will not recurse into a "
                       "tree written by another uid.")
        entry.unlink()


def call_planner(brief: str) -> str:
    """Hand the planner one brief. Same shape as call_solver, same reasons.

    Note what the brief contains: the whole current plan, acceptance criteria
    included. That is not a leak. The planner is the AUTHOR of the criteria --
    BOOTSTRAP 1-1 separates the account that writes them from the account that
    writes the code, and the planner is in neither `solverw` nor `runner`. What
    the 0700 on plan/ buys is that the planner cannot WRITE tasks.json: every
    change it wants has to come back through check_proposal below.
    """
    PLANNER_BRIEF.mkdir(parents=True, exist_ok=True)
    brief_path = PLANNER_BRIEF / "plan.md"
    brief_path.write_text(brief, encoding="utf-8")
    shutil.chown(brief_path, group="plannerw")
    brief_path.chmod(0o640)

    try:
        proc = run(["sudo", "-u", "planner", str(PLANNER_RUN), str(brief_path)],
                   timeout=TIMEOUTS["planner"])
    except subprocess.TimeoutExpired:
        raise Halt("PLAN_PROPOSE", f"planner still running after {TIMEOUTS['planner']}s",
                   "planner-run's internal timeout did not fire; check with: "
                   "pgrep -a -u planner")
    out = proc.stdout + proc.stderr
    if proc.returncode == 124:
        raise Halt("PLAN_PROPOSE", "planner hit its own timeout in planner-run", out[-4000:])
    if proc.returncode != 0:
        raise Halt("PLAN_PROPOSE", f"planner exited {proc.returncode}", out[-4000:])
    return out


def read_proposal() -> dict[str, str]:
    """Whatever is in out/, checked as a set of filenames before it is read.

    This is the "the change is confined to three files" rule, and it is a
    filename allowlist rather than a diff inspection on purpose: there is no
    proposal that touches a fourth file and then has to be argued about, because
    there is nowhere for a fourth file to go.
    """
    if not PLANNER_OUT.is_dir():
        raise Halt("PLAN_APPLY", f"no proposal directory at {PLANNER_OUT}")
    entries = sorted(PLANNER_OUT.iterdir(), key=lambda p: p.name)
    if not entries:
        raise Halt("PLAN_APPLY", "the planner wrote nothing")

    allowed = set(PROPOSAL_FILES) | {ESCALATE_NAME}
    stray = sorted(e.name for e in entries if e.name not in allowed)
    if stray:
        raise Halt("PLAN_APPLY", "the proposal contains files the planner may not write",
                   "wrote: " + ", ".join(stray) + "\nallowed: " + ", ".join(sorted(allowed)))

    proposal = {}
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise Halt("PLAN_APPLY", f"{entry.name} is not a regular file",
                       "A symlink here would apply content from outside the "
                       "proposal directory.")
        proposal[entry.name] = entry.read_text(encoding="utf-8")

    if ESCALATE_NAME in proposal and len(proposal) > 1:
        raise Halt("PLAN_APPLY",
                   f"{ESCALATE_NAME} was written alongside a proposal",
                   "Escalating and proposing at the same time is ambiguous: "
                   "either the planner can fix this within its remit or it cannot.")
    return proposal


def check_proposal(old: dict, new: dict) -> list[str]:
    """Everything the planner may not change about a step that already exists.

    BOOTSTRAP 1-4 lets the planner answer an escalation with case (a) -- tighten
    the goal, re-plan the approach -- and reserves (b) and (c), which rewrite or
    discard acceptance criteria, for the human. That distinction is enforced
    here, mechanically, because "do not weaken the criteria to make the tests
    pass" is exactly the instruction a stuck agent has the most reason to
    reinterpret.

    Adding steps is allowed; that is how a plan grows.
    """
    problems: list[str] = []
    done = green_steps()
    old_steps = {s["id"]: s for s in old.get("steps", [])}
    new_steps = {s["id"]: s for s in new.get("steps", [])}

    for sid, o in old_steps.items():
        n = new_steps.get(sid)
        if n is None:
            problems.append(
                f"P1: step {sid} was removed. Deleting a step deletes its acceptance "
                f"criteria, which is case (c) and belongs to the human")
            continue
        if canon(o.get("acceptance")) != canon(n.get("acceptance")):
            problems.append(
                f"P2: step {sid} has different acceptance criteria. That is case (b) "
                f"and belongs to the human")
        # expected_tests is what RED_GATE R1 counts against, so lowering it asks
        # for fewer tests over the same criteria. The linter's L7 already forbids
        # dropping below the number of criteria; this forbids drifting down at all.
        if int(n.get("expected_tests", 0)) < int(o.get("expected_tests", 0)):
            problems.append(
                f"P3: step {sid} lowers expected_tests from {o.get('expected_tests')} "
                f"to {n.get('expected_tests')}")
        if o.get("review_gate") and not n.get("review_gate"):
            problems.append(f"P4: step {sid} turns review_gate off")
        # A step that is already green was measured against a definition that is
        # now history. Rewriting it does not change the code -- the runner will
        # not re-run it -- it only makes the ledger describe something that never
        # happened.
        if sid in done and canon(o) != canon(n):
            problems.append(
                f"P5: step {sid} is already green; its definition is a record of what "
                f"was checked and cannot be edited")

    return problems


def brief_plan_revise(step: dict | None, escalation: str, feedback: str = "") -> str:
    spec = SYSTEM_SPEC.read_text(encoding="utf-8") if SYSTEM_SPEC.exists() \
        else "(not written yet)"
    context = (PLAN / "CONTEXT.md").read_text(encoding="utf-8")
    tasks = (PLAN / "tasks.json").read_text(encoding="utf-8")
    done = sorted(green_steps())
    focus = f"step {step['id']}" if step else "the plan"
    return f"""You are the planner. Revise the plan so that {focus} can succeed.

You do not write code and you cannot reach the repository. You write files into
the current directory and the runner decides whether to apply them.

# SYSTEM_SPEC.md
{spec}

# plan/CONTEXT.md
{context}

# plan/tasks.json
{tasks}

# Why the runner stopped
{escalation}

# Steps that are already green
{", ".join(done) if done else "(none)"}

# What you may write, into the current directory
- `tasks.json`      the full revised plan, not a diff
- `CONTEXT.md`      optional, only if the background the solver receives is what
                    was wrong
- `SYSTEM_SPEC.md`  optional, only if an agreed decision has to change
- `{ESCALATE_NAME}`   instead of all of the above; see below

Write no other file. A fourth filename is rejected without being read.

# What you may change about a step that already exists
The goal, the contracts, files_write, files_test, depends_on, max_attempts.
That is: how the step is approached, and how it is described to the solver.

# What is rejected mechanically
- changing any `acceptance` entry of a step that already exists
- removing a step
- lowering `expected_tests`, or turning `review_gate` off
- any change at all to a step that is already green
- a plan that fails the linter (RUNNER_SPEC section 8)

This is BOOTSTRAP 1-4. Case (a) -- the implementation is what is wrong, so
tighten the goal -- is yours. Case (b) -- the acceptance criteria themselves are
wrong or unreachable -- and case (c) -- the upstream design is wrong -- are
decisions for the human, not for you.

So if you conclude that this step cannot be made to pass without changing what
it is required to do, do not try. Write a single file named `{ESCALATE_NAME}`
saying which criterion is unreachable and why, and write nothing else. That is a
correct outcome, and it is the only route to the human.

{feedback_section(feedback)}
Output nothing but the files. Do not restate the plan in your final message.
"""

# --------------------------------------------------------------------------
# bootstrapping a plan from the human's requirements (BOOTSTRAP Phase 0..3)
# --------------------------------------------------------------------------


# Everything the planner needs to produce a plan this runner will accept. It is
# a plain string rather than an f-string because it contains JSON braces, and
# every rule in it is one the runner enforces anyway -- stating them here only
# saves a round trip, it does not make them true.
BOOTSTRAP_RULES = """
# What to write, into the current directory

- `SYSTEM_SPEC.md`  the design, as agreed with the human. Short. The data model,
                    the module boundaries, ONE OR TWO decisions that would be
                    expensive to reverse, and a list of what v1 will not do.
- `CONTEXT.md`      the only background the solver ever receives. It gets the
                    same text on every step and has no memory between steps, so
                    it must be self-contained: language and version, the exact
                    test command, project conventions, domain vocabulary. Under
                    100 lines.
- `tasks.json`      the plan. Format below.
- `ESCALATE.md`     INSTEAD of all of the above, if you cannot plan yet. See the
                    last section.

Write no other file. A fifth filename is rejected without being read.

# tasks.json

Top level:

    "version": 1
    "timeouts": {"test": 120, "solver": 960, "planner": 960}   (optional)
    "limits":   {"escalations": 1}                             (optional)
    "steps":    [ ... ]

Each step:

    "id"              short and stable, e.g. "S1"
    "kind"            "unit" or "integration"
    "goal"            what to build, addressed to the solver. It sees this only
                      while implementing, never while writing the tests.
    "depends_on"      ids of earlier steps; [] for the first
    "contracts"       {"requires": [...], "provides": [...], "invariants": [...]}
    "acceptance"      [{"case": "normal|boundary|error",
                        "given": "...", "then": "..."}, ...]
    "files_write"     exact paths the solver may create or modify
    "files_test"      exact paths for the tests; never overlaps files_write
    "expected_tests"  how many tests this step must produce
    "max_attempts"    3 is normal
    "review_gate"     false unless a human must read the tests before freezing

Aim for 10 to 15 steps. One step is ONE behaviour that can fail on its own. If
an implementation would run past roughly 150 lines, split it.

# Where the code goes -- not negotiable

Every path in `files_write` starts with `src/`, and every path in `files_test`
starts with `tests/`. Those two directories are the only ones the runner can
open and close for writing, so a plan that puts code anywhere else cannot be
enforced and is rejected.

Put the package inside src/, e.g. `src/yourpkg/models.py`, and import it as
`from yourpkg.models import Thing` -- `src` is on sys.path, so the `src.`
prefix does not appear in imports. Say this in CONTEXT.md; the solver has no
other way to learn it.

# Rules the runner checks before it will run the plan

A plan that breaks any of these is rejected without being run, so check them
yourself first.

    L2   a step may depend only on steps listed BEFORE it
    L3   everything in contracts.requires is provided by something it depends on
    L4   no file appears in files_write of two different steps
    L5   files_write and files_test never overlap
    L6   every step has at least one "normal", one "boundary" and one "error"
         acceptance case
    L7   expected_tests is at least the number of acceptance criteria
    L8   with review_gate false, every criterion states a concrete value: a
         number, a quoted literal, or an exception type
    L9   at least one of the FIRST THREE steps is kind "integration"
    L10  the LAST step is kind "integration"
    L11  a "unit" step may not provide something that no later step requires
    L12  files_write is under src/, files_test is under tests/

# Three things that are not obvious

These were each learned by watching a run fail on them.

1. **contracts.provides holds signature strings and nothing else.**
   The solver is asked for a stub before it is asked for an implementation, and
   `provides` is what it is given. Anything in there that carries MEANING rather
   than SHAPE gets faithfully implemented in the stub -- and a criterion that
   the stub already satisfies has never been observed to fail, which stops the
   step. Write `def parse(s: str) -> Config`. Do not write "raises ValueError on
   bad input" here; that belongs in acceptance.

2. **contracts.invariants must be observable through the public contract.**
   Invariants go into the brief for writing the TESTS. An invariant about
   internal structure ("must call normalize() rather than reimplement it")
   makes the solver write a test that reaches inside the module, which then
   errors instead of failing, and the runner rejects the step. State invariants
   as facts about inputs and outputs. Put implementation requirements in `goal`,
   which only the implementation phase sees.

3. **The acceptance criteria are the specification.**
   Write each as an exact input and an exact expected output, concrete enough
   that two engineers who never spoke would write the same test. Prefer values
   you can compute by hand. "the result is correct" is not a criterion;
   "the result is exactly 2011.357" is.

Also: the stub returns a conspicuously wrong value of the right type, so a
criterion whose expected answer is an empty string, zero, an empty list, or the
argument unchanged will PASS against the stub and stop the step. Where a
boundary case genuinely has such an answer, keep it -- but make sure the step
has other criteria that cannot.
"""

BOOTSTRAP_ESCALATE = """
# If you cannot plan yet

BOOTSTRAP Phase 0: do not start designing while an important question is still
open. If the requirements leave something undecided that would change the SHAPE
of the plan -- a representation that is expensive to reverse, a scope boundary,
a format, a rule with no stated behaviour at its edges -- do not guess.

Write a single file named ESCALATE.md containing your questions, and write
nothing else.

Ask as few questions as will do; the human wants to answer once. For each
question, state the assumption you would proceed on if they said nothing, so
that "your assumptions are fine" is a complete answer.
"""


def brief_plan_bootstrap(requirements: str, feedback: str = "") -> str:
    return f"""You are the planner. Turn the requirements below into a plan.

You do not write code and you never will. Implementation is done by a separate
agent that cannot see this conversation, has no memory between steps, and
receives exactly one step's worth of information at a time. Your output has to
work as a standalone instruction for someone in that position.

You write files into the current directory. The runner checks them before
anything is run, and if they do not pass it will come back to you with the
reasons -- so the requirements below are about the thing being built, and
making a plan this machine accepts is your problem, not the author's.

# The requirements, written by the human
{requirements}
{environment_facts()}
{BOOTSTRAP_RULES}
{BOOTSTRAP_ESCALATE}
{feedback_section(feedback)}
Output nothing but the files. Do not restate the plan in your final message.
"""


def environment_facts() -> str:
    """What the project actually looks like, read off the machine.

    The rules in BOOTSTRAP_RULES are a transcription of what the runner
    enforces, which means they are only as complete as whoever wrote them
    remembered -- L12 was missing from the first version and a plan was built
    against the gap. Facts about the tree, the interpreter and the test command
    have no such failure mode, so they are gathered rather than written down.

    The retry loop below is the real answer to that problem: anything the brief
    forgets to mention, the linter still catches, and the planner is told.
    """
    def version(binary: Path) -> str:
        try:
            proc = run([str(binary), "--version"])
            return (proc.stdout + proc.stderr).strip().splitlines()[0]
        except (OSError, IndexError):
            return "(not installed)"

    skip = {".git", ".venv", ".runner", "plan", "__pycache__", ".pytest_cache"}
    listing = []
    for child in sorted(PROJECT.rglob("*")):
        if any(part in skip for part in child.relative_to(PROJECT).parts):
            continue
        rel = child.relative_to(PROJECT)
        listing.append(f"  {rel}/" if child.is_dir() else f"  {rel}")
    tree = "\n".join(listing) or "  (empty apart from the directories above)"

    conftest = PROJECT / "conftest.py"
    conftest_text = conftest.read_text(encoding="utf-8") if conftest.exists() else "(none)"

    return f"""# The environment, as it actually is right now

Interpreter: {version(PROJECT / ".venv" / "bin" / "python")}
Test runner: {version(PYTEST)}

The runner executes the tests itself, as:
    .venv/bin/pytest {" ".join(PYTEST_ARGS)} <the step's files_test>

Everything under the project root, except plan/, .git/, .venv/ and caches --
this is the whole of what exists today:

{tree}

conftest.py at the root, which pytest loads automatically:

{conftest_text}
"""


def prune_proposal() -> list[str]:
    """Delete anything in out/ that is not one of the names a proposal may use.

    Used only between retries. The planner has no way to remove a file it
    wrote -- it can create and edit, and that is all -- so telling it "delete
    that" would be advice it cannot follow. The runner owns the directory, so
    it does the deleting and says so in the feedback.
    """
    allowed = set(PROPOSAL_FILES) | {ESCALATE_NAME}
    removed = []
    for entry in PLANNER_OUT.iterdir():
        if entry.name in allowed and entry.is_file() and not entry.is_symlink():
            continue
        removed.append(entry.name)
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
    return removed


def proposal_problems(proposal: dict[str, str]) -> list[str]:
    """Everything wrong with this proposal, as the runner will judge it.

    Shared by `plan apply`, `plan show` and the retry loop, so that what the
    planner is told to fix is exactly what would have rejected it -- not a
    second implementation of the same rules that can drift from the first.
    """
    existing = PLAN / "tasks.json"
    if existing.exists():
        old = json.loads(existing.read_text(encoding="utf-8"))
    else:
        # With no plan on disk this is a bootstrap: P1..P5 are all about what may
        # not CHANGE, so they have nothing to compare against. In their place, a
        # first plan has to be complete -- no project starts with acceptance
        # criteria and no spec that a human agreed to, nor with a plan whose
        # solver has no background to work from.
        incomplete = sorted(set(PROPOSAL_FILES) - set(proposal))
        if incomplete:
            return [f"B1: a first plan must include {name}" for name in incomplete]
        old = {"steps": []}

    if "tasks.json" in proposal:
        try:
            new = json.loads(proposal["tasks.json"])
        except json.JSONDecodeError as bad:
            return [f"B2: tasks.json is not valid JSON: {bad}"]
    else:
        new = old

    return check_proposal(old, new) + validate_plan(new)


def plan_with_retry(brief_for, tag: str) -> int:
    """Call the planner, check what it wrote, and hand back the violations.

    This is what lets the planner meet the environment on its own terms rather
    than the human having to know the environment in advance. The runner already
    owns the only authoritative statement of the rules -- it is the code that
    rejects a plan -- so instead of hoping the brief described them completely,
    it runs them and says what failed.

    The planner gets no new privilege from this. It does not run the linter and
    could not; it is told the result. Between attempts its previous files are
    LEFT IN PLACE, so it edits a plan it can see rather than inventing a fresh
    one from a prohibition -- which is both cheaper and less likely to trade one
    violation for another.
    """
    limit = LIMITS["revisions"]
    clear_proposal()
    feedback = ""

    for attempt in range(1, limit + 2):
        call_planner(brief_for(feedback))
        names = sorted(p.name for p in PLANNER_OUT.iterdir())
        ledger(tag, attempt=attempt, wrote=names)
        if not names:
            print("the planner wrote no files", file=sys.stderr)
            return 2

        removed = prune_proposal()
        proposal = read_proposal()

        # An escalation is an answer, not a draft. Nothing to check and nothing
        # to fix: it is addressed to the human and `plan apply` will surface it.
        if ESCALATE_NAME in proposal:
            return 0

        problems = proposal_problems(proposal)
        if removed:
            problems = [f"B3: {n} is not a filename a proposal may use; the "
                        f"runner deleted it" for n in removed] + problems
        if not problems:
            if attempt > 1:
                print(f"the plan passed on attempt {attempt}")
            return 0

        ledger("PLAN_SELFCHECK", attempt=attempt, violations=problems)
        if attempt > limit:
            print(f"\nthe planner could not produce an acceptable plan in "
                  f"{attempt} attempts; {PLANNER_OUT} holds the last one",
                  file=sys.stderr)
            for problem in problems:
                print("  " + problem, file=sys.stderr)
            return 2

        feedback = "\n".join(problems)

    return 2   # unreachable; the loop always returns


def feedback_section(feedback: str) -> str:
    if not feedback:
        return ""
    return f"""
# Your previous attempt was rejected

The files you wrote are still in the current directory. Read them and FIX them
in place -- do not start over. The runner checked them and reported exactly
this:

{feedback}

Every line above is a rule the runner enforces in code. There is no arguing
with them and no partial credit: fix all of them, then stop.
"""


def cmd_plan_bootstrap(source: str | None) -> int:
    """Ask the planner for a first plan, from a requirements file the human wrote.

    This is the only path by which a plan comes into existence, and it is
    deliberately the same shape as every other planner call: brief in, proposal
    out, runner decides. The human's authority here is the requirements file --
    not an ability to write plan/ directly, and not a duty to know how the
    runner works. Requirements are about the thing being built; making a plan
    that this machine will accept is the planner's job, and the retry loop is
    what makes that true rather than aspirational.
    """
    path = Path(source) if source else REQUIREMENTS
    if not path.is_file():
        print(f"no requirements at {path}", file=sys.stderr)
        print("write them there, or pass --from <path>", file=sys.stderr)
        return 1

    # A bootstrap replaces the whole plan. If steps are already green, that
    # would leave the ledger describing work against criteria that no longer
    # exist -- the same reason the guard refuses to edit a green step (P5).
    done = green_steps()
    if done:
        print(f"refusing: {', '.join(sorted(done))} already green", file=sys.stderr)
        print("a bootstrap replaces the plan, which would orphan them. Start a "
              "fresh project directory instead.", file=sys.stderr)
        return 1

    requirements = path.read_text(encoding="utf-8")
    ledger("PLAN_BOOTSTRAP", source=str(path))
    return plan_with_retry(
        lambda feedback: brief_plan_bootstrap(requirements, feedback),
        "PLAN_BOOTSTRAP_DRAFT")


def cmd_plan_propose(step_id: str | None) -> int:
    if not ESCALATION.exists():
        print(f"nothing to revise: {ESCALATION} does not exist", file=sys.stderr)
        return 1
    load_settings(json.loads((PLAN / "tasks.json").read_text(encoding="utf-8")))
    step = None
    if step_id:
        step, _ = load_plan(step_id)
    escalation = ESCALATION.read_text(encoding="utf-8")
    ledger("PLAN_PROPOSE", step=step_id or "-")
    return plan_with_retry(
        lambda feedback: brief_plan_revise(step, escalation, feedback),
        "PLAN_PROPOSE_DRAFT")


def cmd_plan_show() -> int:
    proposal = read_proposal()
    for name in sorted(proposal):
        body = proposal[name]
        print(f"--- {name} ({len(body.splitlines())} lines) ---")
        print(body)
    if ESCALATE_NAME in proposal:
        return 0
    problems = proposal_problems(proposal)
    print("--- would it be accepted? ---")
    for problem in problems:
        print("  " + problem)
    print("  yes" if not problems else f"  no: {len(problems)} violation(s)")
    return 0


def cmd_plan_apply() -> int:
    """Check the proposal, then apply it. A rejection leaves out/ exactly as it
    was, so the human can read what was refused."""
    proposal = read_proposal()

    if ESCALATE_NAME in proposal:
        ledger("PLAN_ESCALATE", note="the planner declined; this is case (b) or (c)")
        print("The planner escalated to you rather than proposing a change:\n")
        print(proposal[ESCALATE_NAME])
        return 3

    problems = proposal_problems(proposal)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        ledger("PLAN_REJECT", files=sorted(proposal), violations=problems)
        print(f"\nproposal rejected: {len(problems)} violation(s); "
              f"{PLANNER_OUT} left as it is", file=sys.stderr)
        return 2

    applied = []
    for name, dest in PROPOSAL_FILES.items():
        if name not in proposal:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(proposal[name], encoding="utf-8")
        dest.chmod(0o644)
        applied.append(str(dest.relative_to(PROJECT)))

    # The escalation has been answered, so it stops existing. This is what makes
    # the state readable at a glance and safe to drive from a script:
    # ESCALATION.md is present exactly when there is an open escalation, and
    # `plan propose` refuses to run without one. Leaving it behind would let a
    # second propose answer a question that was already answered.
    escalation_tracked = bool(
        run(["git", "ls-files", "--", str(ESCALATION.relative_to(PROJECT))]).stdout.strip())
    ESCALATION.unlink(missing_ok=True)

    ledger("PLAN_APPLY", files=applied)

    # Commit exactly the plan and nothing else. A proposal normally arrives with
    # a halted step still dirty in the working tree, and sweeping that into the
    # same commit would record an abandoned attempt as part of the plan change.
    paths = applied + [str(LEDGER.relative_to(PROJECT))]
    if escalation_tracked:
        paths.append(str(ESCALATION.relative_to(PROJECT)))
    # `git commit -- <paths>` stages tracked paths only, so on a first plan --
    # where all three files are new -- it commits nothing and exits 1. Add them
    # explicitly first. (Missed until the first bootstrap, because in the
    # fixture project these files had always existed.)
    run(["git", "add", "--"] + paths, check=True)
    run(["git", "commit", "-q", "-m", "plan: apply planner proposal", "--"] + paths,
        check=True)
    for entry in PLANNER_OUT.iterdir():
        entry.unlink()
    print("applied: " + ", ".join(applied))
    return 0



def load_settings(tasks: dict) -> None:
    """Let the plan raise or lower the ceilings, for the keys that exist and no
    others. An unknown key here would be a silently ignored setting."""
    TIMEOUTS.update({k: int(v) for k, v in (tasks.get("timeouts") or {}).items()
                     if k in TIMEOUTS})
    LIMITS.update({k: int(v) for k, v in (tasks.get("limits") or {}).items()
                   if k in LIMITS})


def run_step(step_id: str, unvalidated: bool = False) -> int:
    tasks = json.loads((PLAN / "tasks.json").read_text(encoding="utf-8"))
    load_settings(tasks)
    problems = validate_plan(tasks)
    if problems:
        if not unvalidated:
            raise Halt("PLAN_LOAD", f"plan has {len(problems)} lint violation(s)",
                       "\n".join(problems))
        # Bypassing the linter is allowed and is never silent. A green produced
        # from a plan that failed its own lint has to say so in the ledger, for
        # the same reason a green produced without human review does.
        ledger("PLAN_LINT", skipped=True, violations=problems,
               note="ran with --unvalidated; these violations were not fixed")

    step, context = load_plan(step_id)
    ledger("PLAN_LOAD", step=step_id, files_write=step["files_write"], files_test=step["files_test"])

    if touched_paths():
        raise Halt("PLAN_LOAD", "the working tree is dirty; refusing to start",
                   "\n".join(sorted(touched_paths())))

    attempt = 0
    last_run: TestRun | None = None
    try:
        # --- TEST_WRITE -------------------------------------------------
        set_writable(tests=True, src=False)
        call_solver("TEST_WRITE", brief_test_write(step, context))
        assert_touched("TEST_WRITE", step["files_test"])
        ledger("TEST_WRITE", step=step_id, ok=True)

        # --- STUB -------------------------------------------------------
        set_writable(tests=False, src=True)
        call_solver("STUB", brief_stub(step))
        assert_touched("STUB", step["files_test"] + step["files_write"])
        ledger("STUB", step=step_id, ok=True)

        # --- RED_GATE (RUNNER_SPEC 4-1, R1..R5) --------------------------
        red = pytest_run("red", step["files_test"])
        last_run = red
        expected = step["expected_tests"]
        if red.tests != expected:                                          # R1
            raise Halt("RED_GATE", f"R1: collected {red.tests} tests, expected {expected}",
                       red.output[-4000:])
        if red.errors:                                                     # R2
            raise Halt("RED_GATE", f"R2: {red.errors} test(s) errored instead of failing",
                       red.output[-4000:])
        if red.skipped:                                                    # R3
            raise Halt("RED_GATE", f"R3: {red.skipped} test(s) were skipped", red.output[-4000:])
        if red.passed_names:                                               # R4
            raise Halt(
                "RED_GATE",
                "R4: some tests already pass against the stub, so they never "
                "demonstrated the behaviour they claim to check",
                "passing: " + ", ".join(red.passed_names))
        bad = sorted({k for k in red.failure_kinds if not RED_KINDS.match(k)})
        if bad:                                                            # R5
            raise Halt("RED_GATE",
                       "R5: failures are not assertions -- the calls themselves are broken",
                       "types seen: " + ", ".join(bad))
        ledger("RED_GATE", step=step_id, tests=red.tests, failures=red.failures, ok=True)

        # --- REVIEW_GATE ------------------------------------------------
        ledger("REVIEW_GATE", step=step_id, skipped=True,
               note="not implemented in v1; this green was not human-reviewed")

        # --- FREEZE -----------------------------------------------------
        manifest = freeze_tests()
        (STATE / "freeze").mkdir(parents=True, exist_ok=True)
        (STATE / "freeze" / f"{step_id}.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        ledger("FREEZE", step=step_id, files=len(manifest))

        # --- IMPL / VERIFY ----------------------------------------------
        tests_text = frozen_tests_text(step)
        last_failure = "\n".join(red.failure_kinds)
        max_attempts = step.get("max_attempts", 3)

        while attempt < max_attempts:
            attempt += 1
            set_writable(tests=None, src=True)   # tests/ stays frozen; see set_writable
            call_solver("IMPL", brief_impl(step, context, tests_text, last_failure))

            # Freeze tripwire before anything else: if tests changed, nothing
            # the run says about passing means anything.
            for rel, digest in manifest.items():
                if sha256(PROJECT / rel) != digest:
                    raise Halt("VERIFY", f"frozen test was modified: {rel}")

            assert_touched("VERIFY", step["files_test"] + step["files_write"])

            green = pytest_run(f"verify-{attempt}", step["files_test"])
            last_run = green
            ledger("VERIFY", step=step_id, attempt=attempt, tests=green.tests,
                   failures=green.failures, errors=green.errors, green=green.green)
            if green.green:
                break
            last_failure = green.output[-3000:]
        else:
            raise Halt("IMPL", f"still failing after {max_attempts} attempts",
                       last_run.output[-4000:] if last_run else "")

        # --- GREEN ------------------------------------------------------
        contracts_dir = STATE / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        (contracts_dir / f"{step_id}.json").write_text(
            json.dumps(step["contracts"], ensure_ascii=False, indent=2), encoding="utf-8")

        run(["git", "add", "-A"], check=True)
        run(["git", "commit", "-q", "-m", f"{step_id}: {step['goal'][:60]}"], check=True)
        run(["git", "tag", "-f", f"step-{step_id}"], check=True)
        ledger("GREEN", step=step_id, attempts=attempt)
        print(f"\nstep {step_id}: GREEN in {attempt} attempt(s)")
        return 0

    except Halt as halt:
        escalate(step, halt, attempt, last_run)
        return 2


# --------------------------------------------------------------------------
# the outer loop (RUNNER_SPEC section 9, `run --all`)
# --------------------------------------------------------------------------


# What stops the outer loop. Every one of these is an objective fact about the
# repository or the ledger; none of them is a judgement about whether things are
# going well. BOOTSTRAP 1-6: the stopping conditions are fixed in advance,
# because "ask when unsure" delegates the frequency to the model and ends in
# approving everything out of habit.
ALL_GREEN = "every step in the plan is green"
CAP_REACHED = "the escalation cap for this step is spent (RUNNER_SPEC 6-2)"
PLAN_REFUSED = "the planner's proposal was refused"
PLANNER_ASKED = "the planner handed the decision to you"
BUDGET_SPENT = "the wall-clock budget is spent"


def cmd_run_all(unvalidated: bool = False, budget_minutes: int = 0) -> int:
    """Run steps in plan order until something in the list above stops it.

    The loop is: run a step; if it goes green, move on; if it escalates, let the
    planner answer once and try again; if it escalates past its cap, stop.

    Nothing here decides whether a proposal was reasonable -- `plan apply` does
    that, mechanically, and this only reads its exit code. That separation is the
    reason the outer loop can be allowed to run unattended at all.
    """
    deadline = time.monotonic() + budget_minutes * 60 if budget_minutes else None

    def out_of_budget() -> bool:
        return deadline is not None and time.monotonic() > deadline

    def stop(reason: str, code: int) -> int:
        ledger("RUN_ALL_STOP", reason=reason)
        print(f"\nstopped: {reason}", file=sys.stderr)
        return code

    # Load the plan's settings before announcing them. Reporting the built-in
    # defaults here while the loop below runs on the plan's values would make the
    # ledger disagree with what actually happened.
    load_settings(json.loads((PLAN / "tasks.json").read_text(encoding="utf-8")))
    ledger("RUN_ALL_START", budget_minutes=budget_minutes or "none",
           escalation_cap=LIMITS["escalations"])

    while True:
        # Re-read the plan every time round: a proposal applied in the previous
        # iteration may have rewritten the step that is about to run, and may
        # have added steps after it.
        tasks = json.loads((PLAN / "tasks.json").read_text(encoding="utf-8"))
        load_settings(tasks)
        problems = validate_plan(tasks)
        if problems and not unvalidated:
            raise Halt("PLAN_LOAD", f"plan has {len(problems)} lint violation(s)",
                       "\n".join(problems))

        done = green_steps()
        remaining = [s for s in tasks["steps"] if s["id"] not in done]
        if not remaining:
            ledger("ALL_GREEN", steps=sorted(done))
            print(f"\nall {len(done)} step(s) green")
            return 0

        step_id = remaining[0]["id"]
        if out_of_budget():
            return stop(f"{BUDGET_SPENT}; {len(remaining)} step(s) left, next is {step_id}", 2)

        print(f"\n=== {step_id} ({len(done)} done, {len(remaining)} to go) ===")
        if run_step(step_id, unvalidated=unvalidated) == 0:
            continue

        # The step escalated. run_step has already written ESCALATION.md.
        spent = escalation_count(step_id)
        if spent > LIMITS["escalations"]:
            return stop(f"{CAP_REACHED}: {step_id} escalated {spent} time(s); "
                        f"read {ESCALATION}", 2)
        if out_of_budget():
            return stop(f"{BUDGET_SPENT}; {step_id} is escalated and unanswered", 2)

        if cmd_plan_propose(step_id) != 0:
            return stop(f"the planner produced nothing for {step_id}", 2)

        applied = cmd_plan_apply()
        if applied == 3:
            return stop(f"{PLANNER_ASKED} on {step_id}", 3)
        if applied != 0:
            return stop(f"{PLAN_REFUSED} for {step_id}; {PLANNER_OUT} has it", 2)

        # Back to the last green before retrying, so the next attempt starts from
        # a clean tree rather than inheriting the files that failed. The revised
        # plan survives this: `plan apply` committed it, so it is part of HEAD.
        cmd_reset(step_id)


def cmd_validate() -> int:
    tasks = json.loads((PLAN / "tasks.json").read_text(encoding="utf-8"))
    problems = validate_plan(tasks)
    for problem in problems:
        print(problem)
    print(f"\n{len(problems)} violation(s)" if problems else "plan is valid")
    return 1 if problems else 0


def cmd_reset(step_id: str) -> int:
    """Put the tree back to the last green so a halted step can be re-run.

    A step that stops at RED_GATE leaves tests/ frozen and the working tree
    dirty, and the next attempt refuses to start. Undoing that by hand means
    chmod, git reset and git clean in the right order -- easy to get wrong, and
    wrong in a way that silently carries the previous attempt's files into the
    next one.

    Order matters here: adopt before chmod (the runner cannot chmod what it does
    not own), and chmod before git (FREEZE leaves tests/ read-only, and git
    cannot delete a file it cannot write through).
    """
    adopt(TESTS, SRC)
    set_writable(tests=True, src=True)

    # The ledger is tracked by git (GREEN commits it), so `reset --hard` would
    # roll it back to the last green and take with it every record of the
    # attempt being discarded -- including the ESCALATED entry that says why.
    # An append-only ledger that loses exactly the failures is worse than none.
    kept = LEDGER.read_bytes() if LEDGER.exists() else b""

    run(["git", "reset", "--hard", "HEAD"], check=True)
    run(["git", "clean", "-fdq"], check=True)   # no -x: .venv and .runner stay

    if kept:
        LEDGER.write_bytes(kept)

    manifest = STATE / "freeze" / f"{step_id}.json"
    manifest.unlink(missing_ok=True)
    ESCALATION.unlink(missing_ok=True)

    ledger("RESET", step=step_id, note="tree restored to HEAD; freeze manifest and "
                                       "ESCALATION.md discarded")
    print(f"step {step_id}: reset to {run(['git', 'log', '--oneline', '-1']).stdout.strip()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="loop runner v1")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="lint plan/tasks.json (RUNNER_SPEC section 8)")
    run_cmd = sub.add_parser("run", help="run one step, or the whole plan with --all")
    run_cmd.add_argument("step_id", nargs="?",
                         help="the step to run; omit it and pass --all instead")
    run_cmd.add_argument("--all", action="store_true",
                         help="run every step that is not green yet, answering "
                              "escalations through the planner until one of the "
                              "stopping conditions is met")
    run_cmd.add_argument("--budget", type=int, default=0, metavar="MINUTES",
                         help="with --all: stop between steps once this much wall "
                              "clock has passed (default: no limit)")
    run_cmd.add_argument("--unvalidated", action="store_true",
                         help="run despite lint violations; they are written to the ledger")
    reset_cmd = sub.add_parser("reset", help="discard a halted step and return to the last green")
    reset_cmd.add_argument("step_id")

    # The planner channel. Deliberately three separate verbs rather than one:
    # `propose` spends money and `apply` changes what the loop is measured
    # against, and a human who wants to read a proposal before it lands must be
    # able to do that without either happening.
    plan_cmd = sub.add_parser("plan", help="the planner channel")
    plan_sub = plan_cmd.add_subparsers(dest="plan_cmd", required=True)
    boot_cmd = plan_sub.add_parser(
        "bootstrap", help="ask the planner for a first plan, from the requirements")
    boot_cmd.add_argument("--from", dest="source", default=None, metavar="PATH",
                          help=f"the requirements file (default: {REQUIREMENTS})")
    propose_cmd = plan_sub.add_parser(
        "propose", help="ask the planner to revise the plan in answer to ESCALATION.md")
    propose_cmd.add_argument("--step", default=None,
                             help="the step that halted; named in the brief")
    plan_sub.add_parser("show", help="print the pending proposal without applying it")
    plan_sub.add_parser("apply", help="check the pending proposal and apply it if it passes")

    args = parser.parse_args()

    if os.geteuid() == 0:
        print("refusing to run as root: this must run as `runner`", file=sys.stderr)
        return 1

    try:
        if args.cmd == "validate":
            return cmd_validate()
        if args.cmd == "reset":
            return cmd_reset(args.step_id)
        if args.cmd == "plan":
            if args.plan_cmd == "bootstrap":
                return cmd_plan_bootstrap(args.source)
            if args.plan_cmd == "propose":
                return cmd_plan_propose(args.step)
            if args.plan_cmd == "show":
                return cmd_plan_show()
            return cmd_plan_apply()
        if args.all:
            if args.step_id:
                print("run takes a step id or --all, not both", file=sys.stderr)
                return 1
            return cmd_run_all(unvalidated=args.unvalidated,
                               budget_minutes=args.budget)
        if not args.step_id:
            print("run needs a step id, or --all", file=sys.stderr)
            return 1
        return run_step(args.step_id, unvalidated=args.unvalidated)
    except Halt as halt:
        print(f"HALT [{halt.phase}] {halt.reason}\n{halt.detail}", file=sys.stderr)
        return 2
    except FileNotFoundError as missing:
        # Almost always one thing: a fresh project with no plan in it yet. Say
        # so, rather than printing a traceback about tasks.json.
        print(f"missing: {missing.filename}", file=sys.stderr)
        if str(missing.filename or "").endswith("tasks.json"):
            print(f"there is no plan yet. Write the requirements to "
                  f"{REQUIREMENTS} and run: plan bootstrap", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
