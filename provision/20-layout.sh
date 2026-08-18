#!/usr/bin/env bash
# Directory layout and git repositories. Idempotent.
#
# Everything lives on the distro's own ext4 filesystem inside the VHDX. Nothing
# lives on a Windows path: /mnt/c is not mounted (automount is off), and even if
# it were, DrvFs cannot represent the ownership and mode bits that 40-perms.sh
# depends on -- the test freeze would stop being enforceable.
#
#   /srv/loop/repo.git   bare repo. The planner (on Windows) pushes here
#                        over SSH as `runner`; the runner pulls from it.
#   /srv/loop/project    working tree the loop actually runs in
#   /srv/loop/brief      runner writes the per-step brief here, solver reads it.
#                        This is the ONLY channel from runner to solver, which
#                        is what keeps RUNNER_SPEC 5 honest: solver never reads
#                        plan/ and therefore never sees tasks.json.
set -euo pipefail

install -d -o runner -g runner -m 755 /srv/loop
# setgid: briefs written here by runner must land in group solverw, or the
# solver cannot read the one channel it has.
install -d -o runner -g solverw -m 2750 /srv/loop/brief

if [ ! -d /srv/loop/repo.git ]; then
  sudo -u runner git init --bare -b main /srv/loop/repo.git
fi

sudo -u runner git config --global user.name  "loop runner"
sudo -u runner git config --global user.email "runner@$(hostname)"
sudo -u runner git config --global init.defaultBranch main
# The working tree is owned by runner but contains group-writable dirs; keep
# git from treating that as a dubious-ownership problem.
sudo -u runner git config --global --add safe.directory /srv/loop/project

if [ ! -d /srv/loop/project/.git ]; then
  sudo -u runner git clone /srv/loop/repo.git /srv/loop/project
fi

sudo -u runner install -d -m 755 \
  /srv/loop/project/src \
  /srv/loop/project/tests \
  /srv/loop/project/plan \
  /srv/loop/project/.runner

# An empty conftest.py at the root is what puts the project root on sys.path for
# pytest, so a test can `from src.x import y`. Without it pytest inserts tests/
# instead, every import of src fails as a collection error, and RED_GATE's R5
# correctly refuses to call that red -- a confusing way to discover a missing
# empty file.
if [ ! -f /srv/loop/project/conftest.py ]; then
  sudo -u runner touch /srv/loop/project/conftest.py
fi

# Seed an initial commit so the host has something to clone.
cd /srv/loop/project
if ! sudo -u runner git rev-parse HEAD >/dev/null 2>&1; then
  sudo -u runner touch src/.gitkeep tests/.gitkeep plan/.gitkeep
  sudo -u runner tee .gitignore >/dev/null <<'EOF'
.venv/
.runner/
__pycache__/
*.pyc
EOF
  sudo -u runner git add -A
  sudo -u runner git commit -q -m "chore: initial skeleton"
  sudo -u runner git push -q origin main
fi

echo "20-layout: ok"
