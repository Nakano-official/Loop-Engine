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

LEDGER = PLAN / "ledger.jsonl"
ESCALATION = PLAN / "ESCALATION.md"

# tests/ must be run with the project venv's pytest and nothing else. A plain
# `python3 -m pytest` would put the solver's own ~/.local packages back on
# sys.path, and that is the single mechanism keeping "when stuck, pip install"
# from working (RUNNER_SPEC 1-3).
PYTEST_ARGS = ["-q", "-p", "no:cacheprovider", "--strict-markers"]


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
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
        env=({**os.environ, **env} if env else None),
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
    proc = run([PYTEST, *files_test, *PYTEST_ARGS, "--junitxml", str(xml_path)],
               env={"PYTHONDONTWRITEBYTECODE": "1"})
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

    proc = run(["sudo", "-u", "solver", str(SOLVER_RUN), str(brief_path)])
    out = proc.stdout + proc.stderr
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


def escalate(step: dict, halt: Halt, attempt: int, run_: TestRun | None) -> None:
    failed = "\n".join(f"- {k}" for k in (run_.failure_kinds if run_ else [])) or "(none recorded)"
    ESCALATION.write_text(
        f"""# ESCALATION: step {step["id"]}

## Facts
- phase: {halt.phase}
- reason: {halt.reason}
- attempt: {attempt} of {step.get("max_attempts", 3)}

## Failing tests
{failed}

## Detail
```
{halt.detail[-4000:]}
```

## Constraints on the planner
- The acceptance criteria for this step must NOT be weakened.
- Permitted responses are (a) tighten the goal, or escalate. Rewriting the
  acceptance criteria is case (b) and is a decision for the human, not the
  planner (HANDOFF, 2026-08-18).
""",
        encoding="utf-8",
    )
    ledger("ESCALATED", step=step["id"], phase=halt.phase, reason=halt.reason)
    print(f"\nESCALATION written to {ESCALATION}", file=sys.stderr)


# --------------------------------------------------------------------------
# the step
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# the plan linter (RUNNER_SPEC section 8)
# --------------------------------------------------------------------------

PROVIDES_NAME = re.compile(r"def\s+([A-Za-z_]\w*)")
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


def run_step(step_id: str, unvalidated: bool = False) -> int:
    problems = validate_plan(json.loads((PLAN / "tasks.json").read_text(encoding="utf-8")))
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


def cmd_validate() -> int:
    tasks = json.loads((PLAN / "tasks.json").read_text(encoding="utf-8"))
    problems = validate_plan(tasks)
    for problem in problems:
        print(problem)
    print(f"\n{len(problems)} violation(s)" if problems else "plan is valid")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="loop runner v1")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="lint plan/tasks.json (RUNNER_SPEC section 8)")
    run_cmd = sub.add_parser("run", help="run one step end to end")
    run_cmd.add_argument("step_id")
    run_cmd.add_argument("--unvalidated", action="store_true",
                         help="run despite lint violations; they are written to the ledger")
    args = parser.parse_args()

    if os.geteuid() == 0:
        print("refusing to run as root: this must run as `runner`", file=sys.stderr)
        return 1

    if args.cmd == "validate":
        return cmd_validate()

    try:
        return run_step(args.step_id, unvalidated=args.unvalidated)
    except Halt as halt:
        print(f"HALT [{halt.phase}] {halt.reason}\n{halt.detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
