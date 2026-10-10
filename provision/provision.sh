#!/usr/bin/env bash
# Provision the loop sandbox inside the WSL2 Ubuntu-24.04 distro.
# Idempotent: safe to re-run.
#
#   sudo ./provision.sh
#
# Machine only (SYSTEM 8-1): users, toolchains, permissions, network, SSH.
# Workspaces are built by the window, not here.
#
# The maintenance user is the distro's default user (uid 1000) unless
# ADMIN_USER names someone else.
#
# Order matters:
#   05  isolation first -- with no isolation there is nothing to provision into
#   10  the role table: users, groups, channels, launchers, sudoers
#   15  the runner key, pinned to loop-window (needs loop-window from 10)
#   25  egress, before anything below runs code as a restricted role
#   30/35/36  toolchains; 36 runs its smoke tests as exec, under egress
#   40  every role against every path, after the toolchains exist
#   50  last: it is what grants runner a login
set -euo pipefail
cd "$(dirname "$0")"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

ADMIN_USER="${ADMIN_USER:-$(getent passwd 1000 | cut -d: -f1)}"
[ -n "$ADMIN_USER" ] || { echo "no maintenance user (uid 1000); set ADMIN_USER" >&2; exit 1; }
export ADMIN_USER

for s in 05-isolation.sh 10-roles.sh 15-authkeys.sh 25-egress.sh 30-python.sh 35-node.sh \
         36-languages.sh 45-engine.sh 40-check.sh 50-lockdown.sh; do
  echo
  echo "=== $s ==="
  bash "$s"
done

echo
echo "=== provisioning complete ==="
echo "Still by hand:"
echo "  - credentials for each Claude role:   sudo -u <role> -H claude setup-token"
echo "    then paste into /etc/loop/<role>.env"
echo "  - the local model:                    sudo ./70-local-solver.sh  (LOCAL_SOLVER.md)"
echo
echo "Reminder: this sandbox only stays up while a wsl.exe session holds it."
echo "The keepalive scheduled task on Windows is what does that (README 3-1)."
