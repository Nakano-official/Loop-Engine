#!/usr/bin/env bash
# Python toolchain: one virtualenv for the whole machine, owned by root.
# Every role may read and execute it; none may write to it, so nothing that
# runs under a loop account can pip-install its way out of a problem
# (the environment is frozen: what the loop runs on changes only when
# provisioning changes it).
#
# Machine only (SYSTEM 8-1). It used to live inside the project, at
# project/.venv, and the project is no longer provisioning's business: the
# window builds workspaces, and the Python adapter points at this venv.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
# python3-tk is not optional even though nothing here opens a window. On Debian
# tkinter is a separate package, so `import tkinter` raises ModuleNotFoundError
# -- and a test that imports a module which imports tkinter fails at import
# time, before any assertion runs. The venv picks it up for free: tkinter lives
# in the stdlib, not site-packages.
apt-get install -y -qq python3-venv python3-pip python3-tk git

V=/srv/loop/python/venv
install -d -o root -g root -m 755 /srv/loop/python
if [ ! -x "$V/bin/python" ]; then
  python3 -m venv "$V"
fi
"$V/bin/pip" install -q --upgrade pip
"$V/bin/pip" install -q pytest
chown -R root:root /srv/loop/python
chmod -R go-w /srv/loop/python

"$V/bin/python" --version
"$V/bin/pytest" --version

echo "30-python: ok"
