#!/usr/bin/env bash
# WSL-specific isolation checks.
#
# A VirtualBox guest is isolated from the host by default. A WSL2 distro is NOT:
# out of the box it mounts every Windows drive under /mnt, can execute Windows
# binaries, and bridges a display/audio/clipboard channel to the Windows side.
# The isolation comes entirely from /etc/wsl.conf and .wslconfig, and a config
# that was written but never applied looks exactly like a config that works.
#
# `wsl --terminate` does not reload those files; only `wsl --shutdown` does (and
# that kills the keepalive task -- README 3-2). So "I edited wsl.conf" is not
# evidence. These assertions are.
#
# Escape hatch: ALLOW_WSLG=1 accepts the WSLg channel as a known, deliberate
# exception. Nothing else can be waived.
set -euo pipefail

fail=0
bad()  { echo "FAIL: $*" >&2; fail=1; }
info() { echo "  note: $*"; }

# Only meaningful under WSL. On another hypervisor the file layout differs and
# these checks would be misleading rather than wrong.
if ! grep -qi microsoft /proc/sys/kernel/osrelease; then
  echo "05-isolation: not running under WSL, skipping"
  exit 0
fi

# 1. No Windows filesystem reachable. This is the load-bearing check: with no
#    Windows path mounted there is no file for the solver to read and no .exe
#    for it to run. Checked against the live mount table, not against wsl.conf.
#
#    /usr/lib/wsl/* is excluded: WSL always mounts the GPU driver store there
#    read-only (fmask/dmask 222), and it cannot be turned off.
mounts="$(awk '$3=="drvfs" || ($3=="9p" && $2 !~ /^\/usr\/lib\/wsl\//) {print "  "$2" ("$3")"}' \
          /proc/self/mounts || true)"
if [ -n "$mounts" ]; then
  bad "a Windows filesystem is mounted:"
  printf '%s\n' "$mounts" >&2
fi

# /mnt/c usually survives as an empty leftover directory after automount is
# turned off. Empty is fine; populated means something is mounted there now.
if [ -d /mnt/c ] && [ -n "$(ls -A /mnt/c 2>/dev/null || true)" ]; then
  bad "/mnt/c is populated -- automount is on, or someone mounted it by hand"
fi

case ":${PATH}:" in
  *:/mnt/c/*) bad "Windows paths are still on PATH (appendWindowsPath)" ;;
esac

# 2. Interop. Note what this does NOT check: the WSLInterop binfmt handler stays
#    registered even with `[interop] enabled=false`, so its presence proves
#    nothing. What actually happens with interop off is that /init cannot reach
#    the Windows side and exec fails with
#        WSL ERROR: UtilAcceptVsock:273: accept4 failed 110
#    Verified by hand on 2026-08-17 by mounting C: as root and running cmd.exe.
#    Since a running exec test needs a Windows path -- which check 1 already
#    forbids -- interop is reported, not asserted.
if [ -e /proc/sys/fs/binfmt_misc/WSLInterop ] || [ -e /proc/sys/fs/binfmt_misc/WSLInterop-late ]; then
  info "WSLInterop binfmt handler is registered (normal even when interop=false;"
  info "      not evidence either way -- check 1 is what keeps .exe unreachable)"
fi

# 3. WSLg. This one is easy to miss: when it is on, /mnt/wslg carries
#    world-accessible sockets to a compositor and a PulseAudio server running on
#    the WINDOWS side -- a live host channel (display, audio, clipboard) open to
#    every user in the distro, solver included. Nothing in wsl.conf turns it off;
#    it takes `guiApplications=false` in .wslconfig on the Windows side.
#
#    Checked by looking for the channel, not the directory: /mnt/wslg survives as
#    an empty scaffold (just run/user/<uid>) after WSLg is disabled, so its mere
#    existence would be a false positive.
wslg_sockets="$(find /mnt/wslg /tmp/.X11-unix -type s 2>/dev/null | head -5 || true)"
wslg_mounts="$(awk '$2 ~ /^\/mnt\/wslg/ {print "  "$2" ("$3")"}' /proc/self/mounts || true)"
if [ -n "$wslg_sockets$wslg_mounts" ]; then
  if [ "${ALLOW_WSLG:-0}" = "1" ]; then
    info "WSLg is active and waived by ALLOW_WSLG=1"
  else
    bad "WSLg is active: a display/audio/clipboard channel to Windows is open to"
    echo "      every user here, solver included. Found:" >&2
    if [ -n "$wslg_sockets" ]; then printf '  socket: %s\n' $wslg_sockets >&2; fi
    if [ -n "$wslg_mounts" ]; then printf '%s\n' "$wslg_mounts" >&2; fi
    echo "      Close it in C:\\Users\\<you>\\.wslconfig:" >&2
    echo "        [wsl2]" >&2
    echo "        guiApplications=false" >&2
    echo "      then wsl --shutdown and restart the keepalive task (README 3-2)." >&2
    echo "      Or re-run with ALLOW_WSLG=1 to accept it deliberately." >&2
  fi
fi

# 4. systemd is up. Without it sshd is unmanaged and 50-lockdown.sh's
#    verification via `systemctl restart ssh` / `sshd -T` is meaningless.
state="$(systemctl is-system-running 2>/dev/null || true)"
case "$state" in
  running|degraded) ;;
  *) bad "systemd is not running (state: ${state:-none}); set [boot] systemd=true" ;;
esac

# 5. NAT, not mirrored networking. Under mirrored mode the distro reaches
#    services listening on the Windows host's localhost, which quietly widens
#    the sandbox. loopback0 is the tell-tale interface of mirrored mode.
# (captured into a variable rather than piped into `grep -q`: under pipefail
#  grep -q exits at the first hit, ip dies of SIGPIPE, and the check "fails"
#  while being correct -- README 3-10)
links="$(ip -o link show 2>/dev/null || true)"
case "$links" in
  *" loopback0:"*) bad "mirrored networking detected (loopback0 present); use networkingMode=NAT" ;;
esac

if [ "$fail" -eq 0 ]; then
  echo "05-isolation: ok (all assertions passed)"
else
  echo "05-isolation: WSL ISOLATION IS NOT IN EFFECT" >&2
fi
exit "$fail"
