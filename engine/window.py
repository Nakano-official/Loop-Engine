"""The window's operations (SYSTEM 4). Runs inside the box, as runner.

    prepare-tests <ws> <module>    stdin: {"design": ..., "definition": ...}
                                   (re)build the workspace from the design and
                                   run <module>'s tests against its stub
    verify <ws> <module>           stdin: {"files": {path: text}, "green": [names]}
                                   put one candidate implementation in place,
                                   refuse it if it reaches for what it may not
                                   (undeclared modules, forbidden globals), and
                                   run <module>'s tests and every green module's
    accept <ws> <module>           keep <module>'s current implementation: it is
                                   green, and every later build restores it

Each answers one JSON object on stdout: {"records": [...], "output": "..."} for
the two that run tests, {"ok": true} for accept. A part, not a flow: it never
decides what happens next -- pipeline.py does, from diagnose.py's verdict.

The workspace is the window's alone to write (SYSTEM 8-5). Its state is
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
    # Building and checking the app (build-app): the bundler vite itself uses,
    # node, and happy-dom -- all from the frozen toolchain.
    "rolldown": os.environ.get("LOOP_ROLLDOWN", "/srv/loop/node/node_modules/.bin/rolldown"),
    "node": os.environ.get("LOOP_NODE", "/usr/bin/node"),
    "happy-dom": os.environ.get("LOOP_HAPPY_DOM", "/srv/loop/node/node_modules/happy-dom/lib/index.js"),
    "node_modules": os.environ.get("LOOP_NODE_MODULES", "/srv/loop/node/node_modules"),
}


def _link_modules(ws: Path) -> None:
    """ws/node_modules -> the frozen toolchain's. A junction on Windows, which
    needs no privilege (a symlink would); a symlink elsewhere."""
    link = ws / "node_modules"
    if link.exists() or link.is_symlink():
        return
    target = TOOLS["node_modules"]
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)

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


def solver_runner(brief: Path) -> tuple[int, str]:
    """In the box: start the solver role on one brief. Exit 7 is solver-local's
    "the inference server did not answer" -- after the VM restarts, llama-server
    is still loading the weights and answers 503 for a while -- so that one is
    waited out; every other code is passed on."""
    import time
    for _ in range(18):
        proc = subprocess.run(["sudo", "-n", "-u", "solver", "/srv/loop/bin/solver-run", str(brief), "600"],
                              capture_output=True, text=True, cwd="/")
        if proc.returncode != 7:
            break
        time.sleep(10)
    return proc.returncode, (proc.stdout + proc.stderr)[-8000:]


SOLVER_IN = Path("/srv/loop/roles/solver/in")
SOLVER_OUT = Path("/srv/loop/roles/solver/out")


def exec_tool(ws: Path, argv: list) -> tuple[int, str, Path]:
    """In the box: run a tool as exec. What it writes goes to exec's out/."""
    proc = subprocess.run(["sudo", "-n", "-u", "exec", "/srv/loop/bin/exec-run", str(ws), "300", *argv],
                          capture_output=True, text=True, cwd="/")
    return proc.returncode, (proc.stdout + proc.stderr)[-20000:], Path("/srv/loop/roles/exec/out")


def local_tool(ws: Path, argv: list) -> tuple[int, str, Path]:
    out = ws / ".loop"
    proc = subprocess.run(argv, cwd=ws, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", shell=sys.platform == "win32")
    return proc.returncode, (proc.stdout + proc.stderr)[-20000:], out


def tool_out(tool) -> Path:
    """Where a tool runner lets the tool write: exec's out/ in the box."""
    return Path("/srv/loop/roles/exec/out") if tool is exec_tool else None


UPSTREAM = {"definer", "designer"}           # the roles run-role may start
ROLES = Path("/srv/loop/roles")


def role_runner(role: str, brief: Path) -> tuple[int, str]:
    """In the box: start a Claude role on one brief, through its launcher."""
    proc = subprocess.run(["sudo", "-n", "-u", role, f"/srv/loop/bin/{role}-run", str(brief), "900"],
                          capture_output=True, text=True, cwd="/")
    return proc.returncode, (proc.stdout + proc.stderr)[-8000:]


class Window:
    def __init__(self, root: Path, runner: Runner, solve=solver_runner,
                 solver_in: Path = SOLVER_IN, solver_out: Path = SOLVER_OUT, tool=exec_tool,
                 run_role=role_runner, roles: Path = ROLES):
        self.root = Path(root)
        self.runner = runner
        self.tool = tool
        self.run_role_fn = run_role
        self.roles = Path(roles)
        self.solve = solve
        self.solver_in = Path(solver_in)
        self.solver_out = Path(solver_out)

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
        found = self._references(ws / allowed, d, emit, self._module(d, module))
        if "engine" in found:
            return found
        if found.get("undeclared") or found.get("forbidden"):
            # Refused before it runs: what it reaches for is the verdict, and
            # its tests would only add noise to it.
            return {"records": [], "output": "", **found}
        green = [g for g in payload.get("green", []) if g in d.by_name]
        return self._run(ws, emit, green + [module])

    def _references(self, path: Path, d: Design, emit, module: dict) -> dict:
        """The reference check (DESIGN 5): what the candidate imports and which
        globals it uses, read by the adapter's refs tool and held against the
        design. The file is parsed, not run, so runner reads it itself. A file
        that does not parse passes here: its tests say it does not build."""
        proc = subprocess.run(emit.references_command(TOOLS, path), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
        try:
            facts = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return {"engine": "the reference check printed no verdict",
                    "output": (proc.stdout + proc.stderr)[-3000:]}
        if "error" in facts:
            return {}
        return emit.check_references(d, module, facts)

    def attempt(self, ws_name: str, module: str, payload: dict) -> dict:
        """One attempt by the solver role: stage, solve, verify.

        The solver never sees the workspace. Its working directory is its own
        out/, where the window puts the one file it may change (the stub, or
        the last candidate) inside a directory app/ the window creates --
        without the sticky bit: in a sticky directory a file owned by someone
        else cannot be opened with O_CREAT even when it is writable
        (fs.protected_regular), which is how solver-local writes. Whatever
        comes back at that one path is handed to verify, which accepts that
        path and nothing else.
        """
        ws = self._ws(ws_name)
        d, emit = self._build(ws)
        self._module(d, module)
        allowed = f"app/{module}{emit.EXTENSION}"

        stage = self.solver_out / "app"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        os.chmod(stage, 0o2770)
        current = self.solver_out / allowed
        shutil.copyfile(ws / allowed, current)
        os.chmod(current, 0o664)

        brief = self.solver_in / f"{ws_name}-{module}.md"
        brief.write_text(payload["brief"], encoding="utf-8")
        code, output = self.solve(brief)
        brief.unlink(missing_ok=True)
        if code not in (0, 124):
            # Not the model being bad at its job (that exits 0 and costs an
            # attempt): the machine is wrong, and retrying will not help.
            return {"engine": f"the solver backend exited {code}", "output": output}
        candidate = current.read_text(encoding="utf-8") if current.exists() else ""
        result = self.verify(ws_name, module, {"files": {allowed: candidate},
                                               "green": payload.get("green", [])})
        result["solver"] = output
        # The candidate goes back too: the host keeps it beside the ledger, so
        # a person can read what the solver wrote, green or not.
        result["files"] = {allowed: candidate}
        return result

    def build_app(self, ws_name: str, module: str) -> dict:
        """The output (DESIGN 1): the assembly and its platform's generic
        shell bundled into one script, put into the platform's page, and the
        page opened once in happy-dom to see that it boots, draws, and survives
        its own buttons. Bundling and the boot check run as exec -- the boot
        check runs the generated code."""
        ws = self._ws(ws_name)
        d, emit = self._build(ws)
        if self._module(d, module) is not d.assembly:
            raise ValueError(f"{module} is not the assembly")
        name = d.data["target"]["platform"]
        plat = ADAPTERS / "platforms" / name
        if not (plat / "platform.json").exists():
            raise ValueError(f"no platform {name!r}")
        shutil.copyfile(plat / "shell.ts", ws / "shell.ts")
        title = d.definition.get("title", "app")
        key = "loop:" + title
        # The shell's handle goes on window.__loop: the boot check drives frames
        # through it (browser-3d). For browser-dom mount returns nothing.
        (ws / "entry.ts").write_text(
            f'import * as app from "./app/{module}";\n'
            'import { mount } from "./shell";\n'
            f'(window as any).__loop = mount(app as any, {json.dumps(key, ensure_ascii=False)}, '
            'document.getElementById("app")!);\n',
            encoding="utf-8")
        # A shell may import a library from the frozen toolchain (browser-3d:
        # three). The bundler resolves bare imports from the workspace upward,
        # so the workspace gets a link to the toolchain's node_modules --
        # read-only for everyone, like the toolchain itself.
        _link_modules(ws)

        out = tool_out(self.tool) or ws / ".loop"
        bundle = out / "app.js"
        bundle.unlink(missing_ok=True)
        code, output, _ = self.tool(ws, [TOOLS["rolldown"], "entry.ts", "--format", "iife", "--minify",
                                         "--file", str(bundle)])
        if code != 0 or not bundle.exists():
            return {"error": "the bundler failed", "output": output}
        js = bundle.read_text(encoding="utf-8").replace("</script", "<\\/script")
        page = (plat / "page.html").read_text(encoding="utf-8")
        html = _seal(page.replace("__TITLE__", _escape(title)).replace("__BUNDLE__", js))
        app = ws / ".loop" / "app.html"
        app.write_text(html, encoding="utf-8")

        code, output, _ = self.tool(ws, [TOOLS["node"], str(plat / "boot.mjs"), str(app), TOOLS["happy-dom"]])
        try:
            boot = json.loads(output.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            boot = {"ok": False, "errors": [f"the boot check printed no verdict: {output[-2000:]}"]}
        return {"html": html, "boot": boot}

    def run_role(self, ws_name: str, role: str, payload: dict) -> dict:
        """An upstream role on one brief (SYSTEM 4, run-role): the brief into
        the role's in/, the role started through its launcher, and the files it
        left at the top of its out/ handed back. The role never sees a
        workspace; ws_name only names the brief.

        out/ is emptied first: runner owns it, so it may remove what the role
        left there (the sticky bit stops the role, not the directory's owner).
        Only top-level regular files come back -- the brief asks for exactly
        the file it wants."""
        self._ws(ws_name)                       # the name check
        if role not in UPSTREAM:
            raise ValueError(f"run-role starts {sorted(UPSTREAM)}, not {role!r}")
        out = self.roles / role / "out"
        for p in out.iterdir():
            if p.is_file() or p.is_symlink():
                p.unlink(missing_ok=True)
            else:
                shutil.rmtree(p, ignore_errors=True)
        brief = self.roles / role / "in" / f"{ws_name}.md"
        brief.write_text(payload["brief"], encoding="utf-8")
        code, output = self.run_role_fn(role, brief)
        brief.unlink(missing_ok=True)
        files = {}
        for p in sorted(out.iterdir()):
            if p.is_file() and not p.is_symlink() and p.stat().st_size <= 1_000_000:
                files[p.name] = p.read_text(encoding="utf-8", errors="replace")
        return {"code": code, "files": files, "output": output}

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
        if op == "attempt":
            return self.attempt(ws, module, payload)
        if op == "accept":
            return self.accept(ws, module)
        if op == "build-app":
            return self.build_app(ws, module)
        if op == "run-role":
            return self.run_role(ws, module, payload)
        raise ValueError(f"unknown operation {op!r}")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _seal(html: str) -> str:
    """The page's CSP lets exactly its one script run: the hash of that
    script, put where the platform's page says __SCRIPT_HASH__ (DESIGN 1).
    A hash, not 'unsafe-inline' -- a script that got into the page any other
    way does not run. The browser hashes the script's text after its parser
    has turned every CR LF into LF, so the hash is taken of that."""
    import base64
    import hashlib
    start = html.index("<script>") + len("<script>")
    end = html.index("</script>", start)
    text = html[start:end].replace("\r\n", "\n").replace("\r", "\n")
    digest = base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")
    return html.replace("__SCRIPT_HASH__", f"sha256-{digest}", 1)


def main(argv: list[str]) -> int:
    """loop-window hands over: <op> <ws> <module>, the payload on stdin."""
    if len(argv) != 3 or not all(NAME.match(a) for a in argv[1:]):
        print(json.dumps({"error": "usage: <op> <workspace> <module>"}))
        return 2
    op, ws, module = argv
    payload = json.loads(sys.stdin.read() or "{}") if op in ("prepare-tests", "verify", "attempt", "run-role") else None
    try:
        out = Window(Path("/srv/loop/work"), exec_runner).call(op, ws, module, payload)
    except (ValueError, KeyError) as e:
        out = {"error": str(e)}
    print(json.dumps(out, ensure_ascii=False))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
