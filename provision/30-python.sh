#!/usr/bin/env bash
# Python toolchain. The venv is created and owned by runner; solver may read
# and execute it but never write to it, so a stuck solver cannot pip-install
# its way out of a problem (RUNNER_SPEC 1-3: environment freeze).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git

V=/srv/loop/project/.venv
if [ ! -x "$V/bin/python" ]; then
  sudo -u runner python3 -m venv "$V"
fi
sudo -u runner "$V/bin/pip" install -q --upgrade pip
sudo -u runner "$V/bin/pip" install -q pytest

"$V/bin/python" --version
"$V/bin/pytest" --version

echo "30-python: ok"
