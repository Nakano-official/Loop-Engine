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
chmod 755 "$P"

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
chmod 750 /srv/loop/brief

# ---- assertions (from solver's perspective) ----------------------------
fail=0
chk_can()    { if sudo -u solver "$@" >/dev/null 2>&1; then :;       else echo "FAIL: solver should be able to: $*"; fail=1; fi; }
chk_cannot() { if sudo -u solver "$@" >/dev/null 2>&1; then echo "FAIL: solver should NOT be able to: $*"; fail=1; fi; }

chk_can    test -w "$P/src"
chk_can    test -w "$P/tests"
chk_can    test -x "$P/.venv/bin/python"
chk_can    test -r /srv/loop/brief

chk_cannot test -w "$P/.venv/bin/python"
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
