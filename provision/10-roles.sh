#!/usr/bin/env bash
# Every role in roles.json: users, groups, channels, credentials, launchers,
# sudoers. Idempotent.
#
# The work is roles.py's; this file only puts it in the sequence. The checks
# come later (40-check.sh), once the toolchains they also cover exist.
set -euo pipefail
cd "$(dirname "$0")"

# setfacl, for the default ACLs that keep what runner creates later read-only
# to the roles that may read it (roles.py explains why).
if ! command -v setfacl >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq acl
fi

python3 roles.py apply roles.json
