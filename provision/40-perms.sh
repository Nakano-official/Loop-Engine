#!/usr/bin/env bash
# The permission model. This is the primary enforcement mechanism for
# RUNNER_SPEC 1-3 (test freeze) and the files_write allowlist -- everything
# else in the runner is a tripwire on top of this.
#
# The script ends by asserting the model from solver's point of view. A
# permission model nobody tested is a permission model that does not exist.
set -euo pipefail
P=/srv/loop/project
ADMIN_USER="${ADMIN_USER:-maint}"

chown -R runner:runner "$P"

# The working tree root is group-writable, which is not the obvious choice.
# Codex's apply_patch writes through the workspace root, so a read-only root
# makes every edit fail -- with an error naming the target file, a long way from
# the actual cause.
#
# Writable alone would be a hole: unlink and rename are governed by the
# DIRECTORY's write bit, not the file's, so a solver that cannot modify
# conftest.py could still delete it and put its own there. Test collection is
# exactly what FREEZE exists to protect, so that would quietly undo it.
#
# The sticky bit closes that: with it, only a file's owner may remove or rename
# it. The solver can create new files at the root (which codex needs) and cannot
# touch anything runner owns. Asserted at the bottom of this script.
chgrp solverw "$P"
chmod 3775 "$P"      # setgid + sticky + rwxrwxr-x

# The setgid bit has a second effect that is easy to miss and expensive to
# leave: a file the RUNNER creates at the root inherits group solverw too, and
# runner's umask is 002, so it lands 664 -- writable by the solver.
#
# The files that live there are not work, they are the fence. conftest.py
# decides what pytest can import; vitest.config.mjs decides what the DOM tests
# run against; .gitignore decides what `git status` reports as a stray file,
# which is the whole of assert_touched(). A solver that can rewrite any of them
# can undo FREEZE without touching a single file FREEZE hashes.
#
# conftest.py is group runner today only because 20-layout.sh happens to run
# BEFORE the root becomes setgid. Re-running that script afterwards would flip
# it -- the same accident that once left plan/ readable through ten whole
# steps. So the rule is stated here rather than relied on.
find "$P" -maxdepth 1 -type f -user runner -exec chgrp runner {} + -exec chmod 644 {} +

# Private to runner: git history, the plan, and the freeze manifests.
# solver must not be able to read tasks.json (RUNNER_SPEC 5) or learn which
# files are being hashed.
chmod 700 "$P/.git" "$P/plan" "$P/.runner"

# solver-writable. setgid so files created by solver keep group solverw and
# stay manageable by runner.
chown -R runner:solverw "$P/src" "$P/tests"
chmod 2775 "$P/src" "$P/tests"

# Interpreter and libraries: readable and executable, never writable.
chmod -R go-w "$P/.venv"

chown runner:solverw /srv/loop/brief
chmod 2750 /srv/loop/brief   # setgid: briefs must land in group solverw

# ---- assertions (from solver's perspective) ----------------------------
fail=0
chk_can()    { if sudo -u solver "$@" >/dev/null 2>&1; then :;       else echo "FAIL: solver should be able to: $*"; fail=1; fi; }
chk_cannot() { if sudo -u solver "$@" >/dev/null 2>&1; then echo "FAIL: solver should NOT be able to: $*"; fail=1; fi; }

# The workspace root: solver may add, but may not remove what runner owns.
# A disposable runner-owned file stands in for conftest.py / pytest.ini.
sudo -u runner touch "$P/.perm-probe-runner"
chmod 644 "$P/.perm-probe-runner"

chk_can    touch "$P/.perm-probe-solver"                       # codex apply_patch
chk_cannot rm -f "$P/.perm-probe-runner"                       # sticky bit
chk_cannot mv "$P/.perm-probe-runner" "$P/.perm-probe-moved"   # sticky bit
rm -f "$P/.perm-probe-runner" "$P/.perm-probe-solver" "$P/.perm-probe-moved"

chk_can    test -w "$P/src"
chk_can    test -w "$P/tests"
chk_can    test -x "$P/.venv/bin/python"
chk_can    test -r /srv/loop/brief

chk_cannot test -w "$P/.venv/bin/python"
# The fence files at the root. Rewriting any of these defeats the freeze from
# outside the set of files the freeze watches.
chk_cannot test -w "$P/conftest.py"
chk_cannot test -w "$P/.gitignore"
[ -e "$P/vitest.config.mjs" ] && chk_cannot test -w "$P/vitest.config.mjs"
chk_cannot ls "$P/.git"
chk_cannot ls "$P/plan"
chk_cannot ls "$P/.runner"
chk_cannot test -w /srv/loop/brief
chk_cannot ls /home/runner
# The maintenance user's home holds the human's ssh keys and the agent CLI
# credentials. solver reaching it would hand it the git channel and a login.
chk_cannot ls "/home/$ADMIN_USER"

if [ "$fail" -eq 0 ]; then
  echo "40-perms: ok (all assertions passed)"
else
  echo "40-perms: PERMISSION MODEL BROKEN" >&2
fi
exit "$fail"
