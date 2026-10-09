#!/usr/bin/env python3
"""Everything the role table says, applied and then checked.

    sudo python3 roles.py apply  [roles.json]   users, groups, channels, credentials,
                                                launchers, sudoers. Idempotent.
    sudo python3 roles.py egress [roles.json]   per-role outbound rules (iptables
                                                and ip6tables). Run at every boot
                                                by loop-egress.service.
    sudo python3 roles.py check  [roles.json]   every role against every path, the
                                                sudo grants, the egress rules.
    python3 roles.py sshd        [roles.json]   prints "AllowUsers ..." and
                                                "DenyUsers ..." for 50-lockdown.sh

REDESIGN 7-2. The three roles before this were each written out by hand, in four
scripts, and the checks were written by hand too -- which is how tests/ stayed
readable by every account until a check written for one new role happened to
look. Here a role is one line of roles.json, and the checks are generated from
the same line: every role is tried against every path the table knows about,
for read, write and traverse, and each answer has to be the one the table
implies. A role added to the table is checked the moment it exists.

Without an argument the table is roles.json next to this file. Once installed,
/etc/loop/roles.json is the copy the boot-time egress service and the
launchers read.
"""
from __future__ import annotations

import grp
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path("/srv/loop")
BIN = ROOT / "bin"
LIB = ROOT / "lib"
ROLES_DIR = ROOT / "roles"
WORK = ROOT / "work"
GIT = ROOT / "git"
ETC = Path("/etc/loop")
INSTALLED_TABLE = ETC / "roles.json"
SUDOERS = Path("/etc/sudoers.d/91-loop-roles")
WORK_GROUP = "workr"
ADMIN_USER = os.environ.get("ADMIN_USER") or pwd.getpwuid(1000).pw_name

# The sudoers drop-ins this file replaces. They are ours, from the three-role
# layout; leaving one behind would be a grant the table does not know about,
# and the check below would (rightly) refuse it.
LEGACY_SUDOERS = ["91-runner-to-solver", "92-runner-to-planner", "93-runner-to-critic"]

ENV_TEMPLATE = """\
# Non-interactive credentials for the `{role}` account. Fill in by hand.
#
# Preferred -- a subscription token:
#     sudo -u {role} -H claude setup-token
# and paste what it prints after the '=' below.
CLAUDE_CODE_OAUTH_TOKEN=

# Fallback -- metered Console credit, used only when the token above is empty.
ANTHROPIC_API_KEY_CONSOLE=
"""


# ---- the table -----------------------------------------------------------

def load(path: Path) -> dict[str, dict]:
    roles = json.loads(path.read_text(encoding="utf-8"))["roles"]
    if "runner" not in roles:
        sys.exit("roles.json: there is no runner")
    for name, r in roles.items():
        egress = r.get("egress")
        if not (egress in ("open", "none") or
                (isinstance(egress, dict) and set(egress) == {"loopback_tcp"})):
            sys.exit(f"roles.json: {name}: egress must be open, none or {{loopback_tcp: [...]}}")
        if r.get("model") == "claude" and not r.get("tools"):
            sys.exit(f"roles.json: {name}: a claude role needs tools")
        if r.get("work") not in (None, "read"):
            sys.exit(f"roles.json: {name}: work may only be read")
    return roles


def invoked(roles):
    return [n for n, r in roles.items() if r.get("invoked")]


def io_group(role: str) -> str:
    return f"{role}w"


def channel(role: str, side: str) -> Path:
    return ROLES_DIR / role / side


def launcher(role: str) -> Path:
    return BIN / f"{role}-run"


def launcher_source(role: str, r: dict) -> Path:
    """bin/<role>-run if the role has its own, else bin/<model>-run."""
    own = HERE / "bin" / f"{role}-run"
    return own if own.exists() else HERE / "bin" / f"{r['model']}-run"


def expected_groups(roles, name: str) -> set[str]:
    """Every group a role may be in -- and nothing else is allowed."""
    r = roles[name]
    if name == "runner":
        return {"runner"} | {io_group(n) for n in invoked(roles)}
    groups = {name}
    if r.get("invoked"):
        groups.add(io_group(name))
    if r.get("work") == "read":
        groups.add(WORK_GROUP)
    return groups


# ---- small helpers -------------------------------------------------------

def run(*argv: str, check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, check=check, text=True, capture_output=True, **kw)


def user_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def group_exists(name: str) -> bool:
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def place(path: Path, owner: str, group: str, mode: int, directory: bool = True) -> None:
    """Make it exist and make it exactly so, whatever it was before."""
    if directory:
        path.mkdir(parents=True, exist_ok=True)
    shutil.chown(path, owner, group)
    os.chmod(path, mode)


# ---- apply ---------------------------------------------------------------

def apply(roles) -> None:
    if os.geteuid() != 0:
        sys.exit("apply: run with sudo")

    for name, r in roles.items():
        if user_exists(name):
            have = pwd.getpwnam(name).pw_uid
            if r.get("uid") is not None and have != r["uid"]:
                sys.exit(f"apply: {name} exists with uid {have}, the table says {r['uid']}")
        elif r.get("system"):
            run("useradd", "--system", "--create-home", "--home-dir", f"/home/{name}",
                "--shell", "/usr/sbin/nologin", name)
        else:
            run("useradd", "--create-home", "--uid", str(r["uid"]), "--shell", "/bin/bash", name)
        # Only runner logs in (into loop-window, through sshd, which runs the
        # forced command with the account's shell). Every other role is only
        # ever started by sudo with an explicit command, so it needs no shell.
        shell = "/bin/bash" if r.get("login") else "/usr/sbin/nologin"
        if pwd.getpwnam(name).pw_shell != shell:
            run("usermod", "--shell", shell, name)
        home = Path(pwd.getpwnam(name).pw_dir)
        home.mkdir(exist_ok=True)
        shutil.chown(home, name, pwd.getpwnam(name).pw_gid)
        os.chmod(home, 0o700)

    # Groups: one channel group per invoked role (the role and runner), and the
    # workspace readers. Membership is set exactly -- extra memberships left by
    # an earlier layout are removed, because each one is a door.
    for name in invoked(roles):
        if not group_exists(io_group(name)):
            run("groupadd", io_group(name))
    if not group_exists(WORK_GROUP):
        run("groupadd", WORK_GROUP)
    for name in roles:
        primary = grp.getgrgid(pwd.getpwnam(name).pw_gid).gr_name
        wanted = expected_groups(roles, name) - {primary}
        run("usermod", "--groups", ",".join(sorted(wanted)), name)

    for name in roles:
        out = run("id", "-nG", name).stdout.split()
        if {"sudo", "admin"} & set(out):
            sys.exit(f"apply: {name} is in a sudo-capable group")

    # The tree. Root owns the parts nobody in the loop may change; runner owns
    # the channels and the workspaces, because runner is the window.
    place(ROOT, "root", "root", 0o755)
    place(BIN, "root", "root", 0o755)
    place(LIB, "root", "root", 0o755)
    place(ROLES_DIR, "root", "root", 0o755)
    place(ETC, "root", "root", 0o755)
    # Workspaces. Only runner writes here; the roles with work=read may list and
    # read. setgid so every workspace the window creates lands in workr.
    place(WORK, "runner", WORK_GROUP, 0o2750)
    # Bare repositories the host pulls from, over loop-window.
    place(GIT, "runner", "runner", 0o700)

    for name in invoked(roles):
        place(ROLES_DIR / name, "root", "root", 0o755)
        # in/  runner writes the brief, the role reads it. setgid, so a brief
        #      runner writes lands in the role's group and is readable by it.
        place(channel(name, "in"), "runner", io_group(name), 0o2750)
        # out/ the role writes, runner reads. Sticky: group write would
        #      otherwise let the role delete what runner put there.
        place(channel(name, "out"), "runner", io_group(name), 0o3770)

    # What runner creates LATER under work/ and in/ must stay read-only to the
    # group, whatever runner's umask says. Its umask is 002, so a workspace the
    # window made with a plain mkdir came out group-writable -- and exec, which
    # is in that group, could write into the code it was testing. Found on the
    # first run of this layout (2026-10-09), by trying it: the checks then
    # looked at work/ itself and not at what gets made inside it.
    #
    # A default ACL makes it a property of the directory instead of a habit of
    # the window: with one present, new entries take their group bits from it
    # and the umask does not apply.
    for path in [WORK] + [channel(n, "in") for n in invoked(roles)]:
        run("setfacl", "-m", "d:u::rwx,d:g::r-x,d:o::---", str(path))

    # Credentials, one file per Claude role, readable by that uid alone. Not by
    # runner: the window starts a role, it never acts as one.
    for name, r in roles.items():
        if r.get("model") != "claude":
            continue
        env = ETC / f"{name}.env"
        if not env.exists():
            env.write_text(ENV_TEMPLATE.format(role=name), encoding="utf-8")
        shutil.chown(env, "root", name)
        os.chmod(env, 0o640)

    # Launchers: one root-owned script per invoked role, and the window.
    for name, r in roles.items():
        if r.get("invoked"):
            src = launcher_source(name, r)
            if not src.exists():
                sys.exit(f"apply: no launcher for {name} (looked for {src})")
            shutil.copyfile(src, launcher(name))
            place(launcher(name), "root", "root", 0o755, directory=False)
    shutil.copyfile(HERE / "bin" / "loop-window", BIN / "loop-window")
    place(BIN / "loop-window", "root", "root", 0o755, directory=False)
    if Path(__file__).resolve() != (LIB / "roles.py").resolve():
        shutil.copyfile(Path(__file__).resolve(), LIB / "roles.py")
    place(LIB / "roles.py", "root", "root", 0o644, directory=False)

    # sudoers: runner may start each invoked role through its launcher, as that
    # role, and nothing else. Sideways, never up -- no role has a privilege of
    # its own to inherit.
    lines = [f"runner ALL=({n}) NOPASSWD: {launcher(n)}" for n in invoked(roles)]
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write("# Generated by provision/roles.py from roles.json. Do not edit.\n")
        tmp.write("\n".join(lines) + "\n")
    proc = run("visudo", "-c", "-f", tmp.name, check=False)
    if proc.returncode != 0:
        os.unlink(tmp.name)
        sys.exit(f"apply: generated sudoers does not parse:\n{proc.stdout}{proc.stderr}")
    shutil.move(tmp.name, SUDOERS)
    place(SUDOERS, "root", "root", 0o440, directory=False)
    for old in LEGACY_SUDOERS:
        Path("/etc/sudoers.d", old).unlink(missing_ok=True)

    # The table itself, where the egress service and the launchers read it.
    if TABLE.resolve() != INSTALLED_TABLE.resolve():
        shutil.copyfile(TABLE, INSTALLED_TABLE)
    place(INSTALLED_TABLE, "root", "root", 0o644, directory=False)

    print(f"roles apply: ok ({len(roles)} roles, {len(invoked(roles))} invoked)")


# ---- egress --------------------------------------------------------------

FAMILIES = [("iptables", "icmp-admin-prohibited"), ("ip6tables", "icmp6-adm-prohibited")]


def chain(name: str) -> str:
    return f"LOOP_{name.upper()}"


def egress(roles) -> None:
    """One chain per restricted role, reached from OUTPUT by the role's uid.

    Replies to connections someone else opened (ESTABLISHED) are let through --
    sshd's answers to the host on runner's behalf are such replies. Anything a
    role starts itself is refused unless the table allows it, and refused with
    an ICMP error rather than dropped, so the attempt fails at once and the
    errno says why (EHOSTUNREACH, not a timeout).
    """
    if os.geteuid() != 0:
        sys.exit("egress: run with sudo")
    for tool, reject in FAMILIES:
        for name, r in roles.items():
            uid = str(pwd.getpwnam(name).pw_uid)
            c = chain(name)
            jump = ["-m", "owner", "--uid-owner", uid, "-j", c]
            restricted = r["egress"] != "open"
            exists = run(tool, "-w", "-n", "-L", c, check=False).returncode == 0
            if not restricted:
                if exists:
                    while run(tool, "-w", "-C", "OUTPUT", *jump, check=False).returncode == 0:
                        run(tool, "-w", "-D", "OUTPUT", *jump)
                    run(tool, "-w", "-F", c)
                    run(tool, "-w", "-X", c)
                continue
            if exists:
                run(tool, "-w", "-F", c)
            else:
                run(tool, "-w", "-N", c)
            if run(tool, "-w", "-C", "OUTPUT", *jump, check=False).returncode != 0:
                run(tool, "-w", "-A", "OUTPUT", *jump)
            run(tool, "-w", "-A", c, "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT")
            if isinstance(r["egress"], dict):
                for port in r["egress"]["loopback_tcp"]:
                    run(tool, "-w", "-A", c, "-o", "lo", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT")
            run(tool, "-w", "-A", c, "-j", "REJECT", "--reject-with", reject)
    print("roles egress: ok")


# ---- sshd ----------------------------------------------------------------

def sshd(roles) -> None:
    allow = [ADMIN_USER] + [n for n, r in roles.items() if r.get("login")]
    deny = [n for n, r in roles.items() if not r.get("login")]
    print("AllowUsers " + " ".join(allow))
    print("DenyUsers " + " ".join(deny))


# ---- check ---------------------------------------------------------------

PROBE = r"""
import json, os, sys
out = {}
for path, kinds in json.load(sys.stdin):
    out[path] = {k: os.access(path, {"r": os.R_OK, "w": os.W_OK, "x": os.X_OK}[k]) for k in kinds}
print(json.dumps(out))
"""

CONNECT = r"""
import errno, json, socket, sys
res = {}
for host, port in json.load(sys.stdin):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((host, port)); res[f"{host}:{port}"] = "connected"
    except socket.timeout:
        res[f"{host}:{port}"] = "timeout"
    except OSError as e:
        res[f"{host}:{port}"] = errno.errorcode.get(e.errno, str(e.errno))
    finally:
        s.close()
print(json.dumps(res))
"""

BLOCKED = {"EHOSTUNREACH", "EPERM", "EACCES", "ENETUNREACH"}


def as_role(name: str, script: str, payload) -> dict:
    proc = run("sudo", "-u", name, "-H", "python3", "-c", script,
               input=json.dumps(payload), check=False, cwd="/")
    if proc.returncode != 0:
        raise RuntimeError(f"probe as {name} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def matrix(roles) -> list[tuple[str, str, dict[str, set[str]]]]:
    """(path, kinds to probe, {role: rights it must have}). Every role not named
    must have none of the probed rights."""
    m = []
    names = list(roles)
    everyone_rx = {n: {"r", "x"} for n in names}
    for name in invoked(roles):
        m.append((str(channel(name, "in")), "rwx", {name: {"r", "x"}, "runner": {"r", "w", "x"}}))
        m.append((str(channel(name, "out")), "rwx", {name: {"r", "w", "x"}, "runner": {"r", "w", "x"}}))
    for name, r in roles.items():
        if r.get("model") == "claude":
            m.append((str(ETC / f"{name}.env"), "rw", {name: {"r"}}))
        m.append((pwd.getpwnam(name).pw_dir, "rwx", {name: {"r", "w", "x"}}))
    readers = {n: {"r", "x"} for n, r in roles.items() if r.get("work") == "read"}
    m.append((str(WORK), "rwx", {**readers, "runner": {"r", "w", "x"}}))
    m.append((str(GIT), "rwx", {"runner": {"r", "w", "x"}}))
    for shared in (BIN, LIB, ROLES_DIR):
        m.append((str(shared), "rwx", everyone_rx))
    m.append((str(INSTALLED_TABLE), "rw", {n: {"r"} for n in names}))
    for n in invoked(roles):
        m.append((str(launcher(n)), "rwx", everyone_rx))
    m.append((str(BIN / "loop-window"), "rwx", everyone_rx))
    # Toolchains: every role may use them, none may change them. Only the ones
    # that exist yet -- 30/35 run after the first apply.
    for tool in ("/srv/loop/python/venv/bin/python", "/srv/loop/node/node_modules/.bin/vitest"):
        if Path(tool).exists():
            m.append((tool, "rwx", everyone_rx))
    if Path("/srv/loop/models").exists() and "llm" in roles:
        m.append(("/srv/loop/models", "rwx", {"llm": {"r", "x"}}))
    return m


def check(roles) -> int:
    if os.geteuid() != 0:
        sys.exit("check: run with sudo")
    fails: list[str] = []

    # Users and groups.
    for name, r in roles.items():
        if not user_exists(name):
            fails.append(f"{name}: does not exist"); continue
        pw = pwd.getpwnam(name)
        if r.get("uid") is not None and pw.pw_uid != r["uid"]:
            fails.append(f"{name}: uid {pw.pw_uid}, table says {r['uid']}")
        have = set(run("id", "-nG", name).stdout.split())
        want = expected_groups(roles, name)
        if have != want:
            fails.append(f"{name}: groups {sorted(have)}, table implies {sorted(want)}")

    # sudo: exactly the table's grants for runner, nothing for anyone else.
    granted = run("sudo", "-l", "-U", "runner", check=False).stdout
    for n in invoked(roles):
        if f"({n}) NOPASSWD: {launcher(n)}" not in granted:
            fails.append(f"runner: no grant to start {n}")
    grant_lines = [l.strip() for l in granted.splitlines() if l.strip().startswith("(")]
    expected_lines = {f"({n}) NOPASSWD: {launcher(n)}" for n in invoked(roles)}
    for line in grant_lines:
        if line not in expected_lines:
            fails.append(f"runner: a grant the table does not know: {line}")
    for n in roles:
        if n == "runner":
            continue
        out = run("sudo", "-l", "-U", n, check=False).stdout
        if "not allowed" not in out:
            fails.append(f"{n}: has sudo rights")

    # Every role against every path.
    m = matrix(roles)
    for name in roles:
        payload = [(path, list(kinds)) for path, kinds, _ in m]
        got = as_role(name, PROBE, payload)
        for path, kinds, rights in m:
            want = rights.get(name, set())
            for k in kinds:
                if got[path][k] != (k in want):
                    verb = {"r": "read", "w": "write", "x": "traverse/execute"}[k]
                    should = "should" if k in want else "should NOT"
                    fails.append(f"{name} {should} be able to {verb} {path}")

    # What runner creates later -- a workspace and a file in it, a brief -- with
    # runner's own umask, exactly as the window will. The group may read it and
    # nothing more.
    later = []
    ws = WORK / ".probe-workspace"
    run("sudo", "-u", "runner", "sh", "-c",
        f"umask 002 && mkdir -p {ws}/src && echo x > {ws}/src/f", cwd="/")
    readers = {n for n, r in roles.items() if r.get("work") == "read"}
    later += [(str(ws / "src"), "rwx", {n: {"r", "x"} for n in readers} | {"runner": {"r", "w", "x"}}),
              (str(ws / "src" / "f"), "rw", {n: {"r"} for n in readers} | {"runner": {"r", "w"}})]
    for name in invoked(roles):
        brief = channel(name, "in") / ".probe-brief"
        run("sudo", "-u", "runner", "sh", "-c", f"umask 002 && echo x > {brief}", cwd="/")
        later.append((str(brief), "rw", {name: {"r"}, "runner": {"r", "w"}}))
    try:
        for name in roles:
            got = as_role(name, PROBE, [(p, list(k)) for p, k, _ in later])
            for path, kinds, rights in later:
                want = rights.get(name, set())
                for k in kinds:
                    if got[path][k] != (k in want):
                        verb = {"r": "read", "w": "write", "x": "traverse"}[k]
                        should = "should" if k in want else "should NOT"
                        fails.append(f"{name} {should} be able to {verb} {path} (made later by runner)")
    finally:
        shutil.rmtree(ws, ignore_errors=True)
        for name in invoked(roles):
            (channel(name, "in") / ".probe-brief").unlink(missing_ok=True)

    # Sticky out/: the role cannot remove what runner put there.
    for name in invoked(roles):
        out = channel(name, "out")
        probe = out / ".sticky-probe"
        run("sudo", "-u", "runner", "touch", str(probe))
        if run("sudo", "-u", name, "rm", "-f", str(probe), check=False, cwd="/").returncode == 0 \
                and not probe.exists():
            fails.append(f"{name} can delete runner's files in {out} (sticky bit missing)")
        probe.unlink(missing_ok=True)

    # Egress, by trying. Refused by a rule shows as EHOSTUNREACH at once.
    outside = ("1.1.1.1", 443)
    for name, r in roles.items():
        targets = [outside, ("127.0.0.1", 2222)]
        ports = r["egress"].get("loopback_tcp", []) if isinstance(r["egress"], dict) else []
        targets += [("127.0.0.1", p) for p in ports]
        got = as_role(name, CONNECT, targets)
        for host, port in targets:
            res = got[f"{host}:{port}"]
            if r["egress"] == "open":
                allowed = True
            elif (host, port) == outside:
                allowed = False
            else:
                allowed = port in ports
            if allowed and res in BLOCKED:
                fails.append(f"{name}: {host}:{port} refused ({res}), the table allows it")
            if not allowed and res not in BLOCKED:
                fails.append(f"{name}: {host}:{port} not refused ({res}), the table forbids it")
    active = run("systemctl", "is-active", "loop-egress", check=False).stdout.strip()
    if active != "active":
        fails.append(f"loop-egress.service is {active or 'missing'}: the rules will not survive a restart")

    if fails:
        print("\n".join(f"FAIL: {f}" for f in fails), file=sys.stderr)
        print(f"roles check: ROLE MODEL BROKEN ({len(fails)} findings)", file=sys.stderr)
        return 1
    probes = sum(len(k) for _, k, _ in m) * len(roles)
    print(f"roles check: ok ({len(roles)} roles x {len(m)} paths, {probes} access probes)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("apply", "egress", "check", "sshd"):
        sys.exit(__doc__)
    TABLE = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        HERE / "roles.json" if (HERE / "roles.json").exists() else INSTALLED_TABLE)
    table = load(TABLE)
    if sys.argv[1] == "apply":
        apply(table)
    elif sys.argv[1] == "egress":
        egress(table)
    elif sys.argv[1] == "sshd":
        sshd(table)
    else:
        sys.exit(check(table))
