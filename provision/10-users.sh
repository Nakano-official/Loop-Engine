#!/usr/bin/env bash
# Users and groups. Idempotent.
#
# maint : the distro's default user (uid 1000). Has sudo. Maintenance and
#           provisioning only -- it is NOT part of the loop.
# runner  : owns everything, drives the loop, no sudo
# solver  : writes src/ (and tests/ before freeze) only, no sudo, no ssh
# planner : writes plan/tasks.json only, no sudo, no ssh. Separate from solver so
#           that the account setting the acceptance criteria and the account
#           satisfying them are different uids, not just different prompts
#           (BOOTSTRAP 1-1). Its credentials are separate for the same reason.
#
# The loop accounts must not be able to read each other's home, nor the
# maintenance account's home, so the repository lives in /srv/loop rather than
# under any home directory.
set -euo pipefail

ADMIN_USER="${ADMIN_USER:-maint}"

id -u "$ADMIN_USER" >/dev/null 2>&1 || {
  echo "FATAL: maintenance user '$ADMIN_USER' does not exist." >&2
  echo "       This is the distro's default user; set ADMIN_USER if it differs." >&2
  exit 1
}

id -u runner >/dev/null 2>&1 || useradd -m -u 1001 -s /bin/bash runner
id -u solver >/dev/null 2>&1 || useradd -m -u 1002 -s /bin/bash solver
id -u planner >/dev/null 2>&1 || useradd -m -u 1003 -s /bin/bash planner

# Group used to grant solver write access to specific directories.
getent group solverw >/dev/null || groupadd solverw
usermod -aG solverw solver
usermod -aG solverw runner   # so runner can write into brief/ with group perms

# The planner gets its own group rather than sharing solverw. Sharing one would
# put the planner in reach of tests/ and src/, which is the exact separation
# BOOTSTRAP 1-1 is about: whoever sets the acceptance criteria must not be able
# to touch the code that satisfies them.
getent group plannerw >/dev/null || groupadd plannerw
usermod -aG plannerw planner
usermod -aG plannerw runner

# The human's own group. `maint` is in it so that a person can drop a file
# into /srv/loop/human/in without sudo, and runner is in it so it can read what
# was dropped. Neither solver nor planner is in it, and that is the point: the
# requirements that start a project, and later the answers to escalations, are
# the two things only a person may say.
#
# This is not a privilege increase for maint, which already has sudo. It is
# there so that the same directory works unchanged when a web front end, running
# as its own uid, takes over the writing.
getent group humanw >/dev/null || groupadd humanw
usermod -aG humanw runner
usermod -aG humanw "$ADMIN_USER"

# Neither loop account may sudo. Assert rather than assume: a stray sudoers
# drop-in would silently defeat the whole environment-freeze argument.
for u in runner solver planner; do
  if id -nG "$u" | tr ' ' '\n' | grep -qxE 'sudo|admin'; then
    echo "FATAL: $u is in a sudo-capable group" >&2
    exit 1
  fi
done

# Homes are private to their owner. The maintenance user's home is where the
# human keeps ssh keys and agent CLI credentials, so solver must not read it.
chmod 700 /home/runner /home/solver /home/planner
if [ -d "/home/$ADMIN_USER" ]; then chmod 700 "/home/$ADMIN_USER"; fi

echo "10-users: ok"
