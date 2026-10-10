"""The window's operations (REDESIGN 6). Runs inside the box, as runner.

    prepare-tests <ws> <module>    stdin: {"design": ..., "definition": ...}
                                   (re)build the workspace from the design and
                                   run <module>'s tests against its stub
    verify <ws> <module>           stdin: {"files": {path: text}, "green": [names]}
                                   put one candidate implementation in place and
                                   run <module>'s tests and every green module's
    accept <ws> <module>           keep <module>'s current implementation: it is
                                   green, and every later build restores it

Each answers one JSON object on stdout: {"records": [...], "output": "..."} for
the two that run tests, {"ok": true} for accept. A part, not a flow: it never
decides what happens next -- pipeline.py does, from diagnose.py's verdict.

The workspace is the window's alone to write (REDESIGN 7-5). Its state is
kept inside it: .loop/design.json and .loop/definition.json, and in
.loop/impl/ the implementation of every module that went green. A build
regenerates everything else from the design, so a failed candidate never
outlives the next prepare-tests.

Tests run as exec through a runner function. In the box that is exec-run (no
network, read-only workspace); the host's tests pass a local one, so the flow
can be tested without the box.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ADAPTERS = Path(os.environ.get("LOOP_ADAPTERS", HERE.parent / "adapters"))
sys.path.insert(0, str(ADAPTERS))
from design import Design  # noqa: E402

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# The toolchains, frozen by provisioning. Overridable for the host's tests.
TOOLS = {
    "python": os.environ.get("LOOP_PYTHON", "/srv/loop/python/venv/bin/python"),
    "typescript": os.environ.get("LOOP_VITEST", "/srv/loop/node/node_modules/.bin/vitest"),
}

Runner = Callable[[Path, list], dict]   # (workspace, argv) -> {"records", "output"}


def adapter(language: str):
    """The emit module of a language's adapter."""
    import importlib.util
    path = ADAPTERS / language / "emit.py"
    spec = importlib.util.spec_from_file_location(f"emit_{language}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def exec_runner(ws: Path, argv: list) -> dict:
    """In the box: run as exec, read exec's record. The record file is cleared
    first -- runner owns out/, so it may remove what exec left there."""
    record = Path("/srv/loop/roles/exec/out/records.jsonl")
    record.unlink(missing_ok=True)
    proc = subprocess.run(["sudo", "-n", "-u", "exec", "/srv/loop/bin/exec-run", str(ws), "300", *argv],
                          capture_output=True, text=True, cwd="/")
    records = [json.loads(l) for l in record.read_text().splitlines()] if record.exists() else []
    return {"records": records, "output": (proc.stdout + proc.stderr)[-20000:]}


def local_runner(ws: Path, argv: list) -> dict:
    """On the host, for the engine's own tests: the same, without exec."""
    record = ws / ".loop" / "records.jsonl"
    record.unlink(missing_ok=True)
    env = {**os.environ, "LOOP_EXAMPLES": str(ws / "examples.json"), "LOOP_RECORD_DIR": str(record.parent)}
    proc = subprocess.run(argv, cwd=ws, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", shell=sys.platform == "win32")
    records = [json.loads(l) for l in record.read_text(encoding="utf-8").splitlines()] if record.exists() else []
    return {"records": records, "output": (proc.stdout + proc.stderr)[-20000:]}


class Window:
    def __init__(self, root: Path, runner: Runner):
        self.root = Path(root)
        self.runner = runner

    def _ws(self, name: str) -> Path:
        if not NAME.match(name):
            raise ValueError(f"bad workspace name: {name!r}")
        return self.root / name

    def _load(self, ws: Path) -> tuple[Design, object]:
        d = Design(ws / ".loop" / "design.json")
        return d, adapter(d.data["target"]["language"])

    def _build(self, ws: Path) -> tuple[Design, object]:
        d, emit = self._load(ws)
        impl_dir = ws / ".loop" / "impl"
        impls = {p.stem: p.read_text(encoding="utf-8") for p in impl_dir.glob("*")} if impl_dir.exists() else {}
        emit.build_workspace(d, ws, impls)
        return d, emit

    def _module(self, d: Design, name: str) -> dict:
        if name not in d.by_name:
            raise ValueError(f"no module named {name!r} in the design")
        return d.by_name[name]

    def _run(self, ws: Path, emit, modules: list[str]) -> dict:
        language = emit.__name__.removeprefix("emit_")
        return self.runner(ws, emit.run_command(TOOLS[language], ws, modules))

    # ---- the operations ---------------------------------------------------

    def prepare_tests(self, ws_name: str, module: str, payload: dict) -> dict:
        ws = self._ws(ws_name)
        (ws / ".loop").mkdir(parents=True, exist_ok=True)
        (ws / ".loop" / "design.json").write_text(json.dumps(payload["design"]), encoding="utf-8")
        (ws / ".loop" / payload["design"]["definition"]).write_text(
            json.dumps(payload["definition"]), encoding="utf-8")
        d, emit = self._load(ws)
        self._module(d, module)
        # The module being prepared has no implementation yet: its stub.
        (ws / ".loop" / "impl" / f"{module}{emit.EXTENSION}").unlink(missing_ok=True)
        d, emit = self._build(ws)
        return self._run(ws, emit, [module])

    def verify(self, ws_name: str, module: str, payload: dict) -> dict:
        ws = self._ws(ws_name)
        d, emit = self._build(ws)
        self._module(d, module)
        allowed = f"app/{module}{emit.EXTENSION}"
        files = payload.get("files", {})
        # files_write is the module's one file. Anything else is refused, not
        # copied: the candidate does not get to touch tests, types or neighbours.
        if set(files) != {allowed}:
            return {"refused": f"a candidate for {module} may write {allowed} and nothing else, "
                               f"got {sorted(files)}", "records": [], "output": ""}
        (ws / allowed).write_text(files[allowed], encoding="utf-8")
        green = [g for g in payload.get("green", []) if g in d.by_name]
        return self._run(ws, emit, green + [module])

    def accept(self, ws_name: str, module: str) -> dict:
        ws = self._ws(ws_name)
        d, emit = self._load(ws)
        self._module(d, module)
        impl = ws / ".loop" / "impl"
        impl.mkdir(exist_ok=True)
        shutil.copyfile(ws / "app" / f"{module}{emit.EXTENSION}", impl / f"{module}{emit.EXTENSION}")
        return {"ok": True}

    def call(self, op: str, ws: str, module: str, payload: dict | None) -> dict:
        if op == "prepare-tests":
            return self.prepare_tests(ws, module, payload)
        if op == "verify":
            return self.verify(ws, module, payload)
        if op == "accept":
            return self.accept(ws, module)
        raise ValueError(f"unknown operation {op!r}")


def main(argv: list[str]) -> int:
    """loop-window hands over: <op> <ws> <module>, the payload on stdin."""
    if len(argv) != 3 or not all(NAME.match(a) for a in argv[1:]):
        print(json.dumps({"error": "usage: <op> <workspace> <module>"}))
        return 2
    op, ws, module = argv
    payload = json.loads(sys.stdin.read() or "{}") if op in ("prepare-tests", "verify") else None
    try:
        out = Window(Path("/srv/loop/work"), exec_runner).call(op, ws, module, payload)
    except (ValueError, KeyError) as e:
        out = {"error": str(e)}
    print(json.dumps(out, ensure_ascii=False))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
