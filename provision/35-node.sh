#!/usr/bin/env bash
# The Node toolchain, and the reason it exists: a user interface a machine can
# check.
#
# tkinter cannot be driven without a display, and there is no display here.
# Run 7 shipped because of that gap -- ten green steps, 42 passing tests, and a
# window in which every button was disabled from the first frame. A DOM does not
# need a screen: happy-dom builds one in memory, so a test can click a button
# and assert what changed.
#
# Machine only (REDESIGN 7-1). This used to also write the project's side --
# the node_modules symlink, vitest.config.mjs, index.html, the .gitignore
# anchoring -- and that now belongs to the TypeScript adapter, which builds it
# into each workspace. What stays here is the frozen tree itself, outside every
# workspace, owned by root: every role may read and execute it, none may change
# it, so nothing can npm-install its way out of a problem.
set -euo pipefail

TOOLS=/srv/loop/node

# Pinned. A range would let a `npm install` months from now change what the
# gates mean without anyone choosing that.
VITEST_VERSION="4.1.11"
HAPPY_DOM_VERSION="20.13.1"

command -v node >/dev/null || { echo "35-node: node is not installed (README 2-4)" >&2; exit 1; }

install -d -o root -g root -m 755 "$TOOLS"
cat > "$TOOLS/package.json" <<EOF
{
  "name": "loop-toolchain",
  "private": true,
  "type": "module",
  "devDependencies": {
    "vitest": "$VITEST_VERSION",
    "happy-dom": "$HAPPY_DOM_VERSION"
  }
}
EOF
npm install --prefix "$TOOLS" --no-audit --no-fund --silent

# ---- freeze --------------------------------------------------------------
chown -R root:root "$TOOLS"
chmod -R go-w "$TOOLS"

"$TOOLS/node_modules/.bin/vitest" --version
echo "35-node: ok (40-check.sh confirms every role can run it and none can change it)"
