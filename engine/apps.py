"""Where the apps live on the host, and what each one's runs say. A part, not a
flow: it reads and writes files, and decides nothing.

    apps/<name>/
      app.json            {"name", "title", "platform"} -- platform only for apps from requirements
      requirements.md     what a person asked for -- the analyst's input
      concepts.json       the latest concept file: what the request's words mean, what is needed
      definition.json     the latest definition -- the host holds the canonical copy (SYSTEM 5)
      design.json         the latest design; its "definition" field names definition.json
      decisions.jsonl     what a person decided about a run: append-only
      runs/<run>/
        ledger.jsonl      the pipeline's ledger for that run
        definition.json   the definition and design this run wrote (from requirements)
        design.json
        outcome.json      how it ended
        app.html          the output, when it built and booted
        attempts/<module>/<n>/   what each attempt was told and wrote: brief.md, the
                          module's file, records.json, feedback.txt, solver.log
        upstream/<role>/<n>/     each round of the definer and designer: brief.md and
                          what it wrote -- all for a person reading the run (pipeline.Ledger.keep)
        run.pid           while it runs

The dashboard reads this and the command line writes it; neither keeps state
of its own. A run's status is read from its files, never remembered.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")   # also a workspace name in the box
ROOT = Path(os.environ.get("LOOP_APPS", Path(__file__).resolve().parents[2] / "apps"))
# What an app from requirements may be built as: the platforms that exist
# (a directory with a platform.json), the same list the gate accepts.
PLATFORMS = sorted(p.name for p in (Path(__file__).resolve().parents[1] / "adapters" / "platforms").glob("*")
                   if (p / "platform.json").exists())

FINAL = {"ALL_GREEN", "OUTPUT", "OUTPUT_FAILED", "EXHAUSTED", "GATE_FAILED", "STOPPED"}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue                      # a line half-written while being read
    return out


def _alive(pid: int) -> bool:
    """Whether a process is still running -- without touching it.

    Not os.kill(pid, 0) on Windows: there it is TerminateProcess with exit code
    0, so asking whether a run is alive would end it. The query is made
    through the process handle instead."""
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)        # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259                    # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class Run:
    app: "App"
    id: str

    @property
    def dir(self) -> Path:
        return self.app.dir / "runs" / self.id

    @property
    def workspace(self) -> str:
        """The workspace in the box: one per run, named after both."""
        return f"{self.app.name}-{self.id}"

    def started(self) -> float:
        """When the run began: run.json, written at creation; for a run made
        before that existed, the first ledger entry, else the directory."""
        try:
            return float(json.loads((self.dir / "run.json").read_text(encoding="utf-8"))["started"])
        except (OSError, ValueError, KeyError):
            pass
        first = self.ledger()[:1]
        if first and "t" in first[0]:
            return float(first[0]["t"])
        return self.dir.stat().st_mtime

    def ledger(self) -> list[dict]:
        return _read_jsonl(self.dir / "ledger.jsonl")

    def outcome(self) -> dict | None:
        p = self.dir / "outcome.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def output(self) -> Path | None:
        p = self.dir / "app.html"
        return p if p.exists() else None

    def pid(self) -> int | None:
        p = self.dir / "run.pid"
        try:
            return int(p.read_text().strip())
        except (OSError, ValueError):
            return None

    def status(self) -> str:
        """running | done | partial | stopped | failed | interrupted -- from the files,
        never remembered. "failed" is a run that ended and said where it went
        back to; "interrupted" is one that ended without saying anything --
        its process died."""
        out = self.outcome()
        if out is not None:
            if out.get("stage") == "done":
                return "done"
            if out.get("stage") == "until":
                return "partial"
            return "stopped" if out.get("stage") == "stopped" else "failed"
        pid = self.pid()
        if pid and _alive(pid):
            return "running"
        return "interrupted"

    def modules(self) -> list[dict]:
        """Per module, in the order the ledger met them: attempts and where it ended."""
        mods: dict[str, dict] = {}
        for e in self.ledger():
            name = e.get("module")
            if not name:
                continue
            m = mods.setdefault(name, {"module": name, "attempts": 0, "state": "red", "reason": ""})
            if e["event"] == "BEGIN" and e.get("step") == "attempt":
                m["attempts"] = e.get("n", m["attempts"])
                m["state"] = "trying"
            elif e["event"] == "ATTEMPT":
                m["attempts"] = e.get("n", m["attempts"])
                m["reason"] = e.get("reason", "")
                m["state"] = "trying"
            elif e["event"] == "GREEN":
                m["state"] = "green"
            elif e["event"] == "EXHAUSTED":
                m["state"] = "exhausted"
                m["reason"] = e.get("reason", "")
            elif e["event"] == "RED_GATE" and e.get("stage") != "red":
                m["state"] = "engine"
                m["reason"] = e.get("reason", "")
        return list(mods.values())

    def upstream(self) -> list[dict]:
        """The definer's and designer's rounds and every return to the design."""
        keep = {"ANALYST", "DEFINER", "DESIGNER", "DESIGN_ROUND", "BACK_TO_DESIGN"}
        return [{k: v for k, v in e.items() if k != "t"} for e in self.ledger() if e.get("event") in keep]

    def now(self) -> dict | None:
        """What a running run is doing: the last BEGIN, if nothing has ended it
        since, with when it started; else the last event. None unless running.
        `since` is a time, so the page can count the seconds itself."""
        if self.status() != "running":
            return None
        ledger = self.ledger()
        last = ledger[-1] if ledger else None
        if last is None:
            return {"step": "start", "since": self.started()}
        if last.get("event") == "BEGIN":
            return {k: last.get(k) for k in ("step", "module", "n")} | {"since": last.get("t")}
        return {"step": "between", "after": last.get("event"), "module": last.get("module"),
                "since": last.get("t")}

    # ---- what the ledger points at (pipeline.Ledger.keep) -----------------

    KEPT = re.compile(r"^(?:(?:attempts|upstream)/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"
                      r"|concepts\.json|design\.json|definition\.json)$")

    def file(self, rel: str) -> str:
        """One file the ledger points at, as text. Only what the pipeline keeps
        beside the ledger -- attempts/, upstream/, the run's definition and
        design -- and nothing that climbs out of the run."""
        if not self.KEPT.match(rel) or any(part in ("", ".", "..") for part in rel.split("/")):
            raise KeyError(rel)
        p = (self.dir / rel).resolve()
        if self.dir.resolve() not in p.parents or not p.is_file() or p.stat().st_size > 2_000_000:
            raise KeyError(rel)
        return p.read_text(encoding="utf-8", errors="replace")

    def _files_in(self, rel: str | None) -> list[str]:
        if not rel or not self.KEPT.match(rel):
            return []
        d = self.dir / rel
        return sorted(p.name for p in d.iterdir() if p.is_file()) if d.is_dir() else []

    def steps(self) -> list[dict]:
        """Every attempt, red gate and upstream round, with how long it took
        (from the BEGIN before it) and the files kept for it."""
        out, began = [], {}
        for e in self.ledger():
            if e.get("event") == "BEGIN":
                began[(e.get("step"), e.get("module"), e.get("n"))] = e.get("t")
                continue
            step = {"ATTEMPT": "attempt", "RED_GATE": "red_gate", "ANALYST": "analyst", "DEFINER": "definer",
                    "DESIGNER": "designer"}.get(e.get("event"))
            if not step:
                continue
            start = began.get((step, e.get("module"), e.get("n")))
            out.append({k: v for k, v in e.items() if k != "t"} | {
                "step": step, "end": e.get("t"),
                "seconds": round(e["t"] - start, 1) if start and e.get("t") else None,
                "files": self._files_in(e.get("dir"))})
        return out

    def products(self) -> dict:
        """What each upstream stage of this run produced, counted: for the
        stage cards (how much the analyst, the definer and the designer wrote)."""
        def load(name):
            try:
                doc = json.loads((self.dir / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            return doc if isinstance(doc, dict) else None
        out = {}
        c = load("concepts.json")
        if c:
            props = [p for k in c.get("concepts", []) for p in k.get("properties", [])]
            out["analysis"] = {"concepts": len(c.get("concepts", [])), "properties": len(props),
                               "by_example": sum(1 for p in props if p.get("check") == "example"),
                               "requirements": len(c.get("requirements", []))}
        d = load("definition.json")
        if d:
            items = d.get("items", [])
            out["definition"] = {"items": len(items), "examples": sum(len(i.get("examples", [])) for i in items)}
        ds = load("design.json")
        if ds:
            out["design"] = {"modules": len(ds.get("modules", []))}
        return out

    def design_summary(self) -> dict | None:
        """The run's design, as much of it as a picture needs: modules, what
        each depends on, its functions, which one is the assembly."""
        try:
            d = json.loads((self.dir / "design.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        mods = d.get("modules", [])
        by_id = {m.get("id"): m.get("name") for m in mods}
        return {"target": d.get("target", {}), "modules": [
            {"id": m.get("id"), "name": m.get("name"), "assembly": m.get("kind") == "assembly",
             "depends_on": [by_id.get(x, x) for x in m.get("depends_on", [])],
             "functions": sorted((m.get("functions") or {}).keys())} for m in mods]}

    def summary(self) -> dict:
        out = self.outcome() or {}
        return {"id": self.id, "status": self.status(), "stage": out.get("stage"),
                "reason": out.get("reason"), "green": out.get("green", []),
                "output": bool(self.output()), "modules": self.modules(), "upstream": self.upstream(),
                "now": self.now(), "started": self.started(),
                "decision": self.app.decision(self.id)}


@dataclass(frozen=True)
class App:
    dir: Path

    @property
    def name(self) -> str:
        return self.dir.name

    def meta(self) -> dict:
        p = self.dir / "app.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"name": self.name}

    @property
    def design_path(self) -> Path:
        return self.dir / "design.json"

    def requirements(self) -> str | None:
        p = self.dir / "requirements.md"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def platform(self) -> str:
        """What the definer is told to build for. Apps made before platforms
        could be chosen are browser-dom."""
        return self.meta().get("platform", "browser-dom")

    def runs(self) -> list[Run]:
        """Newest first, by when each run started -- not by its id, which is a
        name: an id given by hand ("real-5") sorts after every timestamp."""
        d = self.dir / "runs"
        if not d.exists():
            return []
        return sorted((Run(self, p.name) for p in d.iterdir() if p.is_dir() and NAME.match(p.name)),
                      key=lambda r: r.started(), reverse=True)

    def run(self, run_id: str) -> Run:
        if not NAME.match(run_id) or not (self.dir / "runs" / run_id).is_dir():
            raise KeyError(run_id)
        return Run(self, run_id)

    def new_run(self) -> Run:
        """A run id is its start time. Two runs started in the same second (a
        double click) get -2, -3 ...; mkdir without exist_ok makes the claim
        atomic, so two starts can never share a directory."""
        base = time.strftime("r%Y%m%d-%H%M%S")
        (self.dir / "runs").mkdir(parents=True, exist_ok=True)
        for n in range(1, 100):
            run_id = base if n == 1 else f"{base}-{n}"
            try:
                (self.dir / "runs" / run_id).mkdir()
            except FileExistsError:
                continue
            (self.dir / "runs" / run_id / "run.json").write_text(json.dumps({"started": time.time()}),
                                                                 encoding="utf-8")
            return Run(self, run_id)
        raise RuntimeError("too many runs started in one second")

    # ---- what a person decided ---------------------------------------------

    def decisions(self) -> list[dict]:
        return _read_jsonl(self.dir / "decisions.jsonl")

    def decision(self, run_id: str) -> dict | None:
        """The latest decision about a run, if any."""
        found = [d for d in self.decisions() if d.get("run") == run_id]
        return found[-1] if found else None

    def decide(self, run_id: str, verdict: str, note: str, user: str, scope: str) -> dict:
        """Append-only. A rejection may come from anywhere; an approval only
        from this machine (the dashboard enforces where scope comes from)."""
        if verdict not in ("approve", "reject"):
            raise ValueError("a decision is approve or reject")
        if verdict == "approve" and scope != "local":
            raise PermissionError("an approval is made at this machine, where the app can be played")
        run = self.run(run_id)
        if verdict == "approve" and not run.output():
            raise ValueError("there is no app to approve in this run")
        entry = {"t": time.time(), "run": run_id, "verdict": verdict, "note": note[:2000],
                 "user": user, "scope": scope}
        with (self.dir / "decisions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def summary(self) -> dict:
        runs = self.runs()
        return {"name": self.name, "title": self.meta().get("title", self.name),
                "from_requirements": self.requirements() is not None,
                "runs": len(runs), "latest": runs[0].summary() if runs else None}


class Store:
    def __init__(self, root: Path | str = ROOT):
        self.root = Path(root)

    # ---- one run at a time ---------------------------------------------------
    #
    # Across every app, not per app: the box has one solver, and its staging
    # directory (the solver's out/) is one place. Two runs attempting at once
    # would overwrite each other's candidates.

    @property
    def lock_path(self) -> Path:
        return self.root / ".running"

    def running(self) -> dict | None:
        """The run holding the lock, or None. A lock whose process is gone is
        stale and is cleared."""
        try:
            held = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if _alive(int(held.get("pid", 0))):
            return held
        self.lock_path.unlink(missing_ok=True)
        return None

    def acquire(self, app: str, pid: int) -> None:
        """Take the lock atomically, or raise if another run holds it."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.running()                        # clears a stale lock
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = self.running() or {}
            raise RuntimeError(f"another run is going: {held.get('app')} (pid {held.get('pid')})") from None
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"app": app, "pid": pid, "t": time.time()}, f)

    def release(self, pid: int) -> None:
        held = self.running()
        if held and int(held.get("pid", 0)) == pid:
            self.lock_path.unlink(missing_ok=True)

    def apps(self) -> list[App]:
        if not self.root.exists():
            return []
        return [App(p) for p in sorted(self.root.iterdir())
                if p.is_dir() and NAME.match(p.name) and (p / "app.json").exists()]

    def app(self, name: str) -> App:
        if not NAME.match(name) or not (self.root / name / "app.json").exists():
            raise KeyError(name)
        return App(self.root / name)

    def create_from_requirements(self, name: str, title: str, requirements: str,
                                 platform: str = "browser-dom") -> App:
        """A new app from what a person asked for, to be built for one
        platform. The definer and the designer write the rest, on its first run."""
        if not NAME.match(name):
            raise ValueError(f"an app name is lower case letters, digits, - and _: {name!r}")
        if platform not in PLATFORMS:
            raise ValueError(f"the platform is one of {PLATFORMS}: {platform!r}")
        if not requirements.strip():
            raise ValueError("the requirements are empty")
        if len(requirements) > 20000:
            raise ValueError("the requirements are too long")
        d = self.root / name
        try:
            d.mkdir(parents=True)
        except FileExistsError:
            raise FileExistsError(name) from None
        (d / "requirements.md").write_text(requirements, encoding="utf-8")
        (d / "app.json").write_text(json.dumps({"name": name, "title": title[:100] or name, "platform": platform},
                                               ensure_ascii=False), encoding="utf-8")
        return App(d)

    def create(self, name: str, title: str, definition: Path, design: Path) -> App:
        """A new app from a definition and a design (until the upstream stages
        write them). The design is pointed at definition.json."""
        if not NAME.match(name):
            raise ValueError(f"an app name is lower case letters, digits, - and _: {name!r}")
        d = self.root / name
        if d.exists():
            raise FileExistsError(name)
        d.mkdir(parents=True)
        shutil.copyfile(definition, d / "definition.json")
        ds = json.loads(Path(design).read_text(encoding="utf-8"))
        ds["definition"] = "definition.json"
        (d / "design.json").write_text(json.dumps(ds, ensure_ascii=False, indent=1), encoding="utf-8")
        (d / "app.json").write_text(json.dumps({"name": name, "title": title}, ensure_ascii=False),
                                    encoding="utf-8")
        return App(d)
