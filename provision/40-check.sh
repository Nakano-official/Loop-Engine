#!/usr/bin/env bash
# The role model, checked from every role's point of view (SYSTEM 8-2).
#
# Every role is tried against every path the table knows about -- read, write,
# traverse -- and each answer has to be the one the table implies. Then the
# sudo grants (exactly the table's, nothing else), the sticky out/ channels,
# and the egress rules, by actually connecting.
#
# A permission model nobody tested is a permission model that does not exist:
# the hand-written checks this replaces were how tests/ stayed readable by every
# account until a check written for one new role happened to look.
set -euo pipefail
cd "$(dirname "$0")"
python3 roles.py check roles.json

# What the table cannot say, tried as the roles themselves (2026-10-13). Each of
# these was a hole until then.
fail=0
bad() { echo "40-check: $*" >&2; fail=1; }

# The Claude roles get their tools from --tools; --allowedTools alone left Bash,
# WebFetch and the rest available.
grep -q -- '--tools "$TOOLS"' bin/claude-run || bad "claude-run does not restrict the tools with --tools"

# No role may schedule a job for later.
for r in $(python3 -c 'import json; print(" ".join(n for n, v in json.load(open("roles.json"))["roles"].items() if v.get("invoked")))'); do
  if sudo -n -u "$r" crontab -l >/dev/null 2>&1 || sudo -n -u "$r" crontab -l 2>&1 | grep -q "no crontab"; then
    bad "$r may use crontab"
  fi
done

# exec: nothing it starts outlives exec-run, and its TMPDIR and umask are its own.
WS="$(mktemp -d /srv/loop/work/check-XXXXXX)"
chmod 755 "$WS"
sudo -n -u exec /srv/loop/bin/exec-run "$WS" 20 \
  bash -c 'setsid sleep 300 </dev/null >/dev/null 2>&1 & echo "TMPDIR=$TMPDIR UMASK=$(umask)"' > /tmp/.40-check.$$ 2>&1 || true
sleep 1
pgrep -u exec >/dev/null && bad "a process exec started outlived exec-run: $(pgrep -a -u exec | head -3)"
grep -q "TMPDIR=/home/exec/" /tmp/.40-check.$$ || bad "exec-run gives no private TMPDIR: $(cat /tmp/.40-check.$$)"
grep -q "UMASK=0027" /tmp/.40-check.$$ || bad "exec-run umask is not 0027: $(cat /tmp/.40-check.$$)"
rm -rf "$WS" /tmp/.40-check.$$
pkill -KILL -u exec 2>/dev/null || true

[ "$fail" -eq 0 ] && echo "40-check: ok (tools restricted, no cron for roles, exec leaves nothing behind)"
exit "$fail"
