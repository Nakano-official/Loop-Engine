#!/usr/bin/env bash
# How the runner starts the solver. Idempotent.
#
# The runner owns the repository and drives the loop, but has no sudo -- and
# 10-users.sh asserts that, because a runner that can become root can undo every
# gate it is supposed to enforce. Yet it still has to start processes as a
# DIFFERENT uid, or the solver's write fence (RUNNER_SPEC 1-2) has nobody to
# apply it to.
#
# So: one narrow exception. Runas is limited to (solver) and the command list to
# a single root-owned launcher. That is sideways movement, not escalation --
# `solver` has no privileges of its own to inherit. BOOTSTRAP 1-7 forbids handing
# the loop accounts power over the machine; it does not forbid the runner from
# dropping into the account it supervises.
set -euo pipefail
cd "$(dirname "$0")"

install -d -o root -g root -m 755 /srv/loop/bin
install -o root -g root -m 755 bin/solver-run   /srv/loop/bin/solver-run
install -o root -g root -m 755 bin/smoke-solver /srv/loop/bin/smoke-solver
install -o root -g root -m 755 bin/smoke-pytest /srv/loop/bin/smoke-pytest

install -d -o root -g root -m 755 /etc/loop

# There is deliberately NO credential file for the solver. It authenticates with
# its own ChatGPT subscription login, which lands in /home/solver/.codex at mode
# 700 -- so the credential is reachable by exactly one uid and by nothing else:
#
#     sudo -u solver -H codex login --device-auth
#
# Logging in as the maintenance account does not work, and that is the property
# worth having rather than a nuisance to route around: /home/<other> is 0700, so
# a credential can only ever be used by the account it was issued to.
# (Device auth needs no browser inside the distro -- it prints a code you enter
# in a browser on the host.)

# The planner's credentials are a SEPARATE file with a separate key, readable by
# a different uid. Two reasons, both mechanical rather than tidy-minded:
# a solver that burns through its quota must not be able to stop the planner from
# running, and a sandbox breach must not hand over the credential that drives the
# side which sets the acceptance criteria.
if [ ! -f /etc/loop/planner.env ]; then
  cat > /etc/loop/planner.env <<'EOF'
# Non-interactive credentials for the `planner` account. Fill in by hand.
ANTHROPIC_API_KEY=
EOF
fi
chown root:planner /etc/loop/planner.env
chmod 640 /etc/loop/planner.env

# A malformed drop-in makes sudo refuse to run at all, including the sudo that
# would fix it. Validate before it goes live.
tmp="$(mktemp)"
cat > "$tmp" <<'EOF'
runner ALL=(solver) NOPASSWD: /srv/loop/bin/solver-run
EOF
visudo -c -f "$tmp" >/dev/null
install -o root -g root -m 440 "$tmp" /etc/sudoers.d/91-runner-to-solver
rm -f "$tmp"

# Verify what actually took effect, not what was written.
granted="$(sudo -l -U runner 2>/dev/null || true)"
case "$granted" in
  *"(solver) NOPASSWD: /srv/loop/bin/solver-run"*)
    : ;;
  *)
    echo "FATAL: runner did not receive the (solver) Runas grant" >&2
    printf '%s\n' "$granted" >&2
    exit 1 ;;
esac

# ...and that it did not receive anything else. `sudo -l` prints a "(ALL : ALL)"
# style line if a broader rule exists anywhere.
case "$granted" in
  *"(ALL"*|*"(root"*)
    echo "FATAL: runner has a Runas grant beyond (solver)" >&2
    printf '%s\n' "$granted" >&2
    exit 1 ;;
esac

# Report what is still missing, per account, rather than a bare "ok".
pending=""
[ -r /home/solver/.codex/auth.json ] || pending="$pending solver(codex-login)"
if ! grep -q '^ANTHROPIC_API_KEY=.\+' /etc/loop/planner.env 2>/dev/null; then
  pending="$pending planner(api-key)"
fi
if [ -n "$pending" ]; then
  echo "45-agent-invoke: ok (still unauthenticated:$pending)"
else
  echo "45-agent-invoke: ok"
fi
