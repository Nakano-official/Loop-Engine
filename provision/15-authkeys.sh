#!/usr/bin/env bash
# Install the host's public key for `runner`. Must run BEFORE 50-lockdown.sh,
# which turns off password authentication -- get the order wrong and you lock
# yourself out of the runner account.
#
# Expects the public key at /tmp/loop-provision/loop-runner_ed25519.pub
set -euo pipefail

PUB=/tmp/loop-provision/loop-runner_ed25519.pub
[ -f "$PUB" ] || { echo "FATAL: $PUB not found" >&2; exit 1; }

install -d -o runner -g runner -m 700 /home/runner/.ssh
install -o runner -g runner -m 600 /dev/null /home/runner/.ssh/authorized_keys
cat "$PUB" > /home/runner/.ssh/authorized_keys
chown runner:runner /home/runner/.ssh/authorized_keys

# solver gets no key and no .ssh directory at all.
rm -rf /home/solver/.ssh

echo "15-authkeys: ok"
