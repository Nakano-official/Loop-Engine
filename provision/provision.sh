#!/usr/bin/env bash
# Provision the loop-runner VM. Idempotent: safe to re-run.
#
#   sudo ./provision.sh
#
# Order matters. 15-authkeys must precede 50-lockdown, and 40-perms must
# follow everything that creates files under /srv/loop.
set -euo pipefail
cd "$(dirname "$0")"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

for s in 10-users.sh 15-authkeys.sh 20-layout.sh 30-python.sh 40-perms.sh 50-lockdown.sh; do
  echo
  echo "=== $s ==="
  bash "$s"
done

echo
echo "=== provisioning complete ==="
echo "60-egress.sh was NOT run: the solver CLI and its API endpoint are still"
echo "undecided (RUNNER_SPEC section 11, item 1). Until it runs, the solver"
echo "account has unrestricted outbound network access."
