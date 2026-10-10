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
