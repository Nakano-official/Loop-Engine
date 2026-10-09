#!/usr/bin/env bash
# One-time, for rebuilding a box in place: move the three-role layout out of
# the way. NOT run by provision.sh.
#
#     sudo ./95-retire.sh          then   sudo ./provision.sh
#
# Nothing is deleted. Everything the new layout does not know about is MOVED to
# /var/backups/loop-retired-<timestamp> (root, 0700): the old project and its
# run copies, the bare repos, the logs, the planner account and its home, the
# old channels and launchers. Look through it, then remove it by hand.
#
# What the new layout keeps under /srv/loop: bin lib roles work git python node
# models. Under /srv/loop/bin: the launchers roles.json implies, loop-window,
# and the local solver's three scripts. Under /etc/loop: roles.json and the
# Claude roles' credential files.
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

R="/var/backups/loop-retired-$(date +%Y%m%d-%H%M%S)"
install -d -o root -g root -m 700 "$R"
moved=0
retire() {  # retire <path> <subdir under $R>
  [ -e "$1" ] || [ -L "$1" ] || return 0
  install -d -m 700 "$R/$2"
  mv -- "$1" "$R/$2/"
  echo "  moved $1"
  moved=$((moved + 1))
}

# What the table implies, read from the table rather than repeated here.
read -r -a LAUNCHERS <<<"$(python3 -c '
import json
roles = json.load(open("roles.json"))["roles"]
print(" ".join(f"{n}-run" for n, r in roles.items() if r.get("invoked")))')"
read -r -a CLAUDE_ENVS <<<"$(python3 -c '
import json
roles = json.load(open("roles.json"))["roles"]
print(" ".join(f"{n}.env" for n, r in roles.items() if r.get("model") == "claude"))')"
read -r -a TABLE_USERS <<<"$(python3 -c '
import json
print(" ".join(json.load(open("roles.json"))["roles"]))')"

in_list() { local x="$1"; shift; for y in "$@"; do [ "$x" = "$y" ] && return 0; done; return 1; }

echo "retiring into $R"

# /srv/loop
if [ -d /srv/loop ]; then
  shopt -s dotglob nullglob
  for e in /srv/loop/*; do
    in_list "$(basename "$e")" bin lib roles work git python node models || retire "$e" srv-loop
  done
  for e in /srv/loop/bin/*; do
    in_list "$(basename "$e")" "${LAUNCHERS[@]}" loop-window llm-serve solver-local smoke-local \
      || retire "$e" bin
  done
  shopt -u dotglob nullglob
fi

# /etc/loop
if [ -d /etc/loop ]; then
  for e in /etc/loop/*; do
    in_list "$(basename "$e")" roles.json "${CLAUDE_ENVS[@]}" || retire "$e" etc-loop
  done
fi

# sudoers drop-ins of the three-role layout. roles.py replaces them with one
# generated file; moving them here first means sudo never sees both at once.
for f in 91-runner-to-solver 92-runner-to-planner 93-runner-to-critic; do
  retire "/etc/sudoers.d/$f" sudoers.d
done
visudo -c >/dev/null

# Accounts the old layout had and the table does not: the home is kept, the
# account is removed.
for u in planner; do
  if id -u "$u" >/dev/null 2>&1 && ! in_list "$u" "${TABLE_USERS[@]}"; then
    pkill -u "$u" 2>/dev/null || true
    retire "/home/$u" homes
    userdel "$u"
    echo "  removed account $u"
  fi
done
for g in plannerw humanw; do
  if getent group "$g" >/dev/null; then
    groupdel "$g"
    echo "  removed group $g"
  fi
done

echo "95-retire: ok ($moved moved into $R). Next: sudo ./provision.sh"
