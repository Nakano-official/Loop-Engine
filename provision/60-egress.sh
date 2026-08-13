#!/usr/bin/env bash
# Egress restriction for the solver account (RUNNER_SPEC 1-3).
#
# NOT run by provision.sh. Run it once the solver CLI is chosen and its API
# endpoint is known -- see RUNNER_SPEC section 11 item 1.
#
#   usage: sudo ./60-egress.sh api.anthropic.com [host ...]
#
# Effect: uid `solver` may reach loopback, DNS, and the listed hosts. Every
# other outbound connection is rejected, so `pip install` and `apt` fail
# loudly instead of silently changing the environment.
#
# LIMITATION: this pins the hosts' current IP addresses. CDN-backed API
# endpoints rotate, and the rules go stale without warning. When that starts
# hurting, replace this with a filtering forward proxy (tinyproxy with an
# allowlist) running as `runner`, and reduce these rules to
# "solver may only reach the proxy port on localhost".
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
[ "$#" -ge 1 ] || { echo "usage: $0 <host> [host ...]" >&2; exit 1; }

UID_SOLVER="$(id -u solver)"
CHAIN=LOOP_SOLVER_OUT

iptables -N "$CHAIN" 2>/dev/null || iptables -F "$CHAIN"
# Attach the chain exactly once.
iptables -C OUTPUT -m owner --uid-owner "$UID_SOLVER" -j "$CHAIN" 2>/dev/null \
  || iptables -A OUTPUT -m owner --uid-owner "$UID_SOLVER" -j "$CHAIN"

iptables -A "$CHAIN" -o lo -j ACCEPT
iptables -A "$CHAIN" -p udp --dport 53 -j ACCEPT
iptables -A "$CHAIN" -p tcp --dport 53 -j ACCEPT

for host in "$@"; do
  ips="$(getent ahostsv4 "$host" | awk '{print $1}' | sort -u)"
  [ -n "$ips" ] || { echo "FATAL: cannot resolve $host" >&2; exit 1; }
  for ip in $ips; do
    echo "  allow $host -> $ip"
    iptables -A "$CHAIN" -d "$ip" -p tcp --dport 443 -j ACCEPT
  done
done

# REJECT rather than DROP: the solver gets an immediate error instead of
# hanging until timeout, and the failure shows up in its output.
iptables -A "$CHAIN" -j REJECT --reject-with icmp-admin-prohibited

echo
echo "Verifying (both checks must behave as stated):"
sudo -u solver curl -s -m 8 -o /dev/null -w '  pypi.org  -> %{http_code} (want 000/failure)\n' https://pypi.org/simple/ || echo "  pypi.org  -> blocked (correct)"
for host in "$@"; do
  sudo -u solver curl -s -m 8 -o /dev/null -w "  $host -> %{http_code} (want non-000)\n" "https://$host/" || echo "  $host -> UNREACHABLE (rules too tight)"
done

echo
echo "Rules are NOT persistent. To keep them across reboots:"
echo "  apt-get install -y iptables-persistent && netfilter-persistent save"
