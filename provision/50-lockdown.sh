#!/usr/bin/env bash
# SSH hardening and update freeze. Run LAST -- it removes password auth, so
# 15-authkeys.sh must have succeeded first.
set -euo pipefail

# Refuse to disable password auth if the runner key never landed. Without this
# guard a failed 15-authkeys.sh turns into a locked VM.
if [ ! -s /home/runner/.ssh/authorized_keys ]; then
  echo "FATAL: /home/runner/.ssh/authorized_keys is missing or empty." >&2
  echo "       Refusing to disable password authentication." >&2
  exit 1
fi

# The filename must sort BEFORE 50-cloud-init.conf. sshd takes the FIRST
# value it sees for a keyword, and cloud-init writes
# /etc/ssh/sshd_config.d/50-cloud-init.conf containing
# "PasswordAuthentication yes" (from `allow-pw: true` in the autoinstall).
# A 99- drop-in is read later and silently loses.
rm -f /etc/ssh/sshd_config.d/99-loop.conf
cat > /etc/ssh/sshd_config.d/00-loop.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
# solver has no key and must never reach the git channel to the host.
DenyUsers solver
EOF
chmod 644 /etc/ssh/sshd_config.d/00-loop.conf

sshd -t
systemctl restart ssh

# Writing a config is not the same as the config taking effect. Ask sshd what
# it actually resolved to, and fail loudly if any of it did not stick.
# Capture once into a variable rather than piping sshd into grep/awk per check.
# Under `set -o pipefail`, `sshd -T | grep -q ...` reports failure even on a
# match: grep -q exits at the first hit, sshd dies of SIGPIPE, and pipefail
# turns that into a non-zero pipeline. The check then "fails" while the
# setting is in fact correct.
sshd_out="$(sshd -T 2>/dev/null || true)"
eff() { printf '%s\n' "$sshd_out" | awk -v k="$1" '$1==k{v=$2} END{print v}'; }
fail=0
for kv in passwordauthentication=no kbdinteractiveauthentication=no permitrootlogin=no; do
  k="${kv%%=*}"; want="${kv#*=}"; got="$(eff "$k")"
  if [ "$got" != "$want" ]; then echo "FAIL: sshd $k=$got (want $want)" >&2; fail=1; fi
done
case "$sshd_out" in
  *"denyusers solver"*) ;;
  *) echo "FAIL: sshd does not deny user solver" >&2; fail=1 ;;
esac
[ "$fail" -eq 0 ] || { echo "50-lockdown: SSH HARDENING DID NOT TAKE EFFECT" >&2; exit 1; }

# Automatic updates would move the environment out from under a frozen
# pip-freeze hash and make a green step non-reproducible weeks later.
# Updating is a deliberate act: re-run this VM's provisioning, don't drift.
systemctl disable --now unattended-upgrades.service 2>/dev/null || true
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true

echo "50-lockdown: ok"
