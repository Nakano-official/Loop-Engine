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
# critic  : reads a brief and writes findings, no sudo, no ssh. A fourth uid
#           rather than a second prompt for the planner, because its value comes
#           entirely from what it CANNOT see. A critic that can read the plan it
#           is judging answers "every criterion is met" -- true, and useless. A
#           critic that can read tests/ answers "the tests pass". Both were
#           measured. So the separation is a filesystem fact, not an instruction.
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
id -u critic  >/dev/null 2>&1 || useradd -m -u 1004 -s /bin/bash critic

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
# The critic's group, and it is deliberately NOT plannerw or solverw. Being in
# either would put the critic within reach of planner/out or brief/ -- the two
# places where the work it is judging is written. It gets a brief handed to it
# and it writes findings; there is no third thing it needs to touch.
getent group criticw >/dev/null || groupadd criticw
usermod -aG criticw critic
usermod -aG criticw runner

getent group humanw >/dev/null || groupadd humanw
usermod -aG humanw runner
usermod -aG humanw "$ADMIN_USER"

# Neither loop account may sudo. Assert rather than assume: a stray sudoers
# drop-in would silently defeat the whole environment-freeze argument.
for u in runner solver planner critic; do
  if id -nG "$u" | tr ' ' '\n' | grep -qxE 'sudo|admin'; then
    echo "FATAL: $u is in a sudo-capable group" >&2
    exit 1
  fi
done

# Homes are private to their owner. The maintenance user's home is where the
# human keeps ssh keys and agent CLI credentials, so solver must not read it.
chmod 700 /home/runner /home/solver /home/planner /home/critic
if [ -d "/home/$ADMIN_USER" ]; then chmod 700 "/home/$ADMIN_USER"; fi

echo "10-users: ok"
