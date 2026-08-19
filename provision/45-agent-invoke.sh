#!/usr/bin/env bash
# How the runner starts the two agents. Idempotent.
#
# The runner owns the repository and drives the loop, but has no sudo -- and
# 10-users.sh asserts that, because a runner that can become root can undo every
# gate it is supposed to enforce. Yet it still has to start processes as
# DIFFERENT uids, or the write fences (RUNNER_SPEC 1-2) have nobody to apply to.
#
# So: two narrow exceptions, one per agent. Runas is limited to (solver) or
# (planner) and the command list to a single root-owned launcher each. That is
# sideways movement, not escalation -- neither account has privileges of its own
# to inherit. BOOTSTRAP 1-7 forbids handing the loop accounts power over the
# machine; it does not forbid the runner from dropping into the accounts it
# supervises.
set -euo pipefail
cd "$(dirname "$0")"

install -d -o root -g root -m 755 /srv/loop/bin
install -o root -g root -m 755 bin/solver-run   /srv/loop/bin/solver-run
install -o root -g root -m 755 bin/planner-run  /srv/loop/bin/planner-run
install -o root -g root -m 755 bin/smoke-solver /srv/loop/bin/smoke-solver
install -o root -g root -m 755 bin/smoke-pytest /srv/loop/bin/smoke-pytest
install -o root -g root -m 755 bin/smoke-planner /srv/loop/bin/smoke-planner
install -o root -g root -m 755 bin/smoke-plan    /srv/loop/bin/smoke-plan

# The planner's channel, deliberately separate from the solver's.
#
#   brief/  runner writes, planner reads. The planner cannot reach plan/ at all
#           (0700 runner), so everything it is allowed to know arrives here.
#   out/    planner writes a PROPOSAL, runner reads it. The planner never writes
#           tasks.json; the runner applies a proposal only after checking what
#           changed. Sticky, for the same reason the workspace root is: group
#           write would otherwise let the planner delete runner-owned files.
install -d -o root  -g root     -m 755  /srv/loop/planner
install -d -o runner -g plannerw -m 2750 /srv/loop/planner/brief
install -d -o runner -g plannerw -m 3770 /srv/loop/planner/out

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
#
# Preferred -- a subscription token, so planning costs nothing per call:
#     sudo -u planner -H claude setup-token
# It prints a token; paste it after the '=' below. Note this draws on the same
# usage window as your own interactive Claude Code work.
CLAUDE_CODE_OAUTH_TOKEN=

# Fallback -- metered Console credit. planner-run uses this only when the
# subscription token above is empty, and says so when it does.
ANTHROPIC_API_KEY_CONSOLE=
EOF
fi
chown root:planner /etc/loop/planner.env
chmod 640 /etc/loop/planner.env

# A malformed drop-in makes sudo refuse to run at all, including the sudo that
# would fix it. Validate before either goes live.
for spec in "solver:91-runner-to-solver" "planner:92-runner-to-planner"; do
  who="${spec%%:*}"; file="${spec##*:}"
  tmp="$(mktemp)"
  printf 'runner ALL=(%s) NOPASSWD: /srv/loop/bin/%s-run\n' "$who" "$who" > "$tmp"
  visudo -c -f "$tmp" >/dev/null
  install -o root -g root -m 440 "$tmp" "/etc/sudoers.d/$file"
  rm -f "$tmp"
done

# Verify what actually took effect, not what was written.
granted="$(sudo -l -U runner 2>/dev/null || true)"
for who in solver planner; do
  case "$granted" in
    *"($who) NOPASSWD: /srv/loop/bin/$who-run"*)
      : ;;
    *)
      echo "FATAL: runner did not receive the ($who) Runas grant" >&2
      printf '%s\n' "$granted" >&2
      exit 1 ;;
  esac
done

# ...and that it did not receive anything else. `sudo -l` prints a "(ALL : ALL)"
# style line if a broader rule exists anywhere.
case "$granted" in
  *"(ALL"*|*"(root"*)
    echo "FATAL: runner has a Runas grant beyond (solver) and (planner)" >&2
    printf '%s\n' "$granted" >&2
    exit 1 ;;
esac

# Report what is still missing, per account, rather than a bare "ok".
pending=""
[ -r /home/solver/.codex/auth.json ] || pending="$pending solver(codex-login)"
if ! grep -qE '^(CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY_CONSOLE)=.+' \
        /etc/loop/planner.env 2>/dev/null; then
  pending="$pending planner(token)"
fi
if [ -n "$pending" ]; then
  echo "45-agent-invoke: ok (still unauthenticated:$pending)"
else
  echo "45-agent-invoke: ok"
fi
