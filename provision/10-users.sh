#!/usr/bin/env bash
# Users and groups. Idempotent.
#
# runner : owns everything, drives the loop, no sudo
# solver : writes src/ (and tests/ before freeze) only, no sudo, no ssh
#
# The two accounts must not be able to read each other's home, so the
# repository lives in /srv/loop rather than under either home directory.
set -euo pipefail

id -u runner >/dev/null 2>&1 || useradd -m -u 1001 -s /bin/bash runner
id -u solver >/dev/null 2>&1 || useradd -m -u 1002 -s /bin/bash solver

# Group used to grant solver write access to specific directories.
getent group solverw >/dev/null || groupadd solverw
usermod -aG solverw solver
usermod -aG solverw runner   # so runner can write into brief/ with group perms

# Neither account may sudo. Assert rather than assume: a stray sudoers drop-in
# would silently defeat the whole environment-freeze argument.
for u in runner solver; do
  if id -nG "$u" | tr ' ' '\n' | grep -qxE 'sudo|admin'; then
    echo "FATAL: $u is in a sudo-capable group" >&2
    exit 1
  fi
done

# Homes are private to their owner.
chmod 700 /home/runner /home/solver
[ -d /home/admin ] && chmod 700 /home/admin

echo "10-users: ok"
