#!/usr/bin/env bash
# SSH access control and update freeze. Run LAST -- it is what grants `runner`
# a login, so 15-authkeys.sh must have succeeded first, and it removes password
# auth, so getting the order wrong locks you out.
set -euo pipefail

ADMIN_USER="${ADMIN_USER:-maint}"

# Refuse to touch sshd if the runner key never landed. Without this guard a
# failed 15-authkeys.sh turns into an account that is allowed to log in but has
# no way to authenticate.
if [ ! -s /home/runner/.ssh/authorized_keys ]; then
  echo "FATAL: /home/runner/.ssh/authorized_keys is missing or empty." >&2
  echo "       Refusing to change the SSH configuration." >&2
  exit 1
fi

# The filename sorts BEFORE the base drop-in (10-loop-dev.conf) because sshd
# takes the FIRST value it sees for a single-valued keyword; a 99- drop-in would
# be read later and silently lose.
#
# AllowUsers is the exception: it is list-valued and ACCUMULATES across
# drop-ins, so `AllowUsers maint` in 10-loop-dev.conf and `AllowUsers maint
# runner` here add up to {maint, runner} regardless of order. The consequence
# worth remembering is the other direction: a later drop-in can only ever WIDEN
# the allow list, never narrow it. Removing a user means editing the file that
# names them.
rm -f /etc/ssh/sshd_config.d/99-loop.conf
cat > /etc/ssh/sshd_config.d/00-loop.conf <<EOF
# Only these two may log in. solver is absent on purpose and denied twice over.
AllowUsers $ADMIN_USER runner
DenyUsers solver
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
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
# AllowUsers/DenyUsers are list-valued: they ACCUMULATE across drop-ins instead
# of the first one winning, and `sshd -T` prints one line per name. Taking the
# last line (or the first) gives a wrong answer -- collect every name.
eff_list() { printf '%s\n' "$sshd_out" | awk -v k="$1" '$1==k{for(i=2;i<=NF;i++) printf "%s ", $i}'; }
fail=0
for kv in passwordauthentication=no kbdinteractiveauthentication=no permitrootlogin=no; do
  k="${kv%%=*}"; want="${kv#*=}"; got="$(eff "$k")"
  if [ "$got" != "$want" ]; then echo "FAIL: sshd $k=$got (want $want)" >&2; fail=1; fi
done

# Check both halves of the access list: runner must be in, solver must not.
allow=" $(eff_list allowusers) "
case "${allow//,/ }" in
  *" runner "*) ;;
  *) echo "FAIL: sshd allowusers=[${allow# }] does not include runner" >&2; fail=1 ;;
esac
case "${allow//,/ }" in
  *" solver "*) echo "FAIL: sshd allowusers=[${allow# }] includes solver" >&2; fail=1 ;;
esac
deny=" $(eff_list denyusers) "
case "${deny//,/ }" in
  *" solver "*) ;;
  *) echo "FAIL: sshd does not deny user solver" >&2; fail=1 ;;
esac

# sshd must stay on 2222: the Windows side reaches it as 127.0.0.1:2222 through
# localhostForwarding, and ~/.ssh/config's `loop-dev` host hardcodes that port.
port="$(eff port)"
if [ "$port" != "2222" ]; then
  echo "FAIL: sshd port=$port (want 2222)" >&2; fail=1
fi

[ "$fail" -eq 0 ] || { echo "50-lockdown: SSH CONFIG DID NOT TAKE EFFECT" >&2; exit 1; }

# Automatic updates would move the environment out from under a frozen
# pip-freeze hash and make a green step non-reproducible weeks later.
# Updating is a deliberate act: re-run this distro's provisioning, don't drift.
systemctl disable --now unattended-upgrades.service 2>/dev/null || true
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true

echo "50-lockdown: ok"
