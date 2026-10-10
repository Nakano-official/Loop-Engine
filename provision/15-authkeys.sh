#!/usr/bin/env bash
# The host's key for `runner`, pinned to the window. Must run BEFORE
# 50-lockdown.sh, which is what lets `runner` log in at all.
#
# Every line of authorized_keys carries
#
#     restrict,command="/srv/loop/bin/loop-window"
#
# so the key starts loop-window and nothing else: no shell, no pty, no port or
# agent forwarding (SYSTEM 8-4). What the client asked for reaches the window
# as SSH_ORIGINAL_COMMAND and is matched against a fixed list there.
#
# The key comes from /tmp/loop-provision/loop-runner_ed25519.pub when that file
# is present (a fresh box, README 2-5). On a box that already has a key it is
# taken from the existing authorized_keys, options stripped, so re-running this
# never needs the public key copied in again.
set -euo pipefail

PUB=/tmp/loop-provision/loop-runner_ed25519.pub
AK=/home/runner/.ssh/authorized_keys
FORCED='restrict,command="/srv/loop/bin/loop-window"'

[ -x /srv/loop/bin/loop-window ] || { echo "FATAL: loop-window is not installed (run 10-roles.sh)" >&2; exit 1; }

if [ -f "$PUB" ]; then
  keys="$(grep -E '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9]+) ' "$PUB" || true)"
elif [ -s "$AK" ]; then
  # The key fields start at the key type; anything before it is options.
  keys="$(grep -oE '(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9]+) [A-Za-z0-9+/=]+( .*)?$' "$AK" || true)"
else
  keys=""
fi
[ -n "$keys" ] || { echo "FATAL: no public key in $PUB or $AK" >&2; exit 1; }

install -d -o runner -g runner -m 700 /home/runner/.ssh
tmp="$(mktemp)"
while IFS= read -r k; do
  printf '%s %s\n' "$FORCED" "$k"
done <<<"$keys" > "$tmp"
install -o runner -g runner -m 600 "$tmp" "$AK"
rm -f "$tmp"

# Assert: no line in the file escapes the window.
while IFS= read -r line; do
  [[ "$line" == "$FORCED "* ]] || { echo "FATAL: a line in $AK is not pinned to loop-window" >&2; exit 1; }
done < "$AK"

# No other role gets a key or a .ssh directory at all.
python3 - <<'EOF'
import json, shutil
roles = json.load(open("/etc/loop/roles.json"))["roles"]
for name, r in roles.items():
    if not r.get("login"):
        shutil.rmtree(f"/home/{name}/.ssh", ignore_errors=True)
EOF

echo "15-authkeys: ok ($(wc -l < "$AK") key(s), all pinned to loop-window)"
