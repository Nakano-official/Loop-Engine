#!/usr/bin/env bash
# Outbound network, per role, from the table (SYSTEM 8-3). Idempotent.
#
#     exec    none         -- generated code runs here
#     solver  loopback:8080 -- the local model's server, nothing else
#     runner  none         -- it answers the host; it never calls out
#     llm     none
#     Claude roles  open   -- their tools (Read/Write/Edit) are what keep them in
#
# Before this, 60-egress.sh existed and provision.sh never ran it: every account
# could reach the internet, the solver included (measured 2026-10-09).
#
# Under WSL2 "not persistent" means "until the VM next idles out", which is
# about a minute after the last wsl.exe session ends -- so the rules are applied
# by a systemd unit at every boot, from /etc/loop/roles.json, not saved once.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# The WSL Ubuntu image ships neither iptables nor nft.
if ! command -v iptables >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq iptables
fi

# The three-role layout's chain, if it was ever applied by hand.
for tool in iptables ip6tables; do
  if "$tool" -w -n -L LOOP_SOLVER_OUT >/dev/null 2>&1; then
    uid="$(id -u solver)"
    while "$tool" -w -D OUTPUT -m owner --uid-owner "$uid" -j LOOP_SOLVER_OUT 2>/dev/null; do :; done
    "$tool" -w -F LOOP_SOLVER_OUT
    "$tool" -w -X LOOP_SOLVER_OUT
  fi
done

cat > /etc/systemd/system/loop-egress.service <<'EOF'
[Unit]
Description=loop: outbound network rules per role (provision/roles.json)
After=local-fs.target
Before=network-pre.target ssh.service loop-llm.service
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /srv/loop/lib/roles.py egress /etc/loop/roles.json

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable loop-egress.service >/dev/null 2>&1
# restart, not start: a oneshot that already ran would otherwise not re-read
# a changed table.
systemctl restart loop-egress.service
systemctl is-active --quiet loop-egress.service || { echo "FATAL: loop-egress.service did not come up" >&2; exit 1; }

iptables -w -S | grep -E '^-A OUTPUT .*-j LOOP_' | sed 's/^/  /'
echo "25-egress: ok (rules applied now and at every boot; 40-check.sh tries them)"
