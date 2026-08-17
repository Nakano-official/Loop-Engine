#!/usr/bin/env bash
# Install the host's public key for `runner`. Must run BEFORE 50-lockdown.sh,
# which is what actually lets `runner` log in at all (the base sshd drop-in
# only allows the maintenance user) -- and which turns password auth off for
# good measure.
#
# The key is a separate one from the maintenance user's: this key exists only
# so the planner's working clone on Windows can push to /srv/loop/repo.git.
#
# Expects the public key at /tmp/loop-provision/loop-runner_ed25519.pub
# (copied in with scp -- there is no /mnt/c in this distro, see README 2-5)
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
