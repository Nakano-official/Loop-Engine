#!/usr/bin/env bash
# The window's operations and the adapters they use, installed into the box.
# Idempotent.
#
#     /srv/loop/lib/engine/window.py     prepare-tests / verify / accept
#     /srv/loop/lib/adapters/...         design.py and one directory per language
#
# Both come from the repository, beside provision/ -- send the three directories
# together (README 2-5). Root owns every file and every role may read them: the
# window runs them as runner, and nothing in the loop may change the code that
# builds its own tests.
set -euo pipefail
cd "$(dirname "$0")"
REPO=..

for d in "$REPO/adapters" "$REPO/engine"; do
  [ -d "$d" ] || { echo "FATAL: $d is missing -- send adapters/ and engine/ with provision/" >&2; exit 1; }
done

LIB=/srv/loop/lib
rm -rf "$LIB/adapters" "$LIB/engine"
install -d -o root -g root -m 755 "$LIB/adapters" "$LIB/engine"
# The adapters without their tests: the box needs what builds a workspace,
# not the conformance suite.
(cd "$REPO/adapters" && find . -type f \( -name '*.py' -o -name '*.ts' \) \
   -not -path './*/tests/*' -not -path '*/__pycache__/*' -print0) |
while IFS= read -r -d '' f; do
  install -D -o root -g root -m 644 "$REPO/adapters/$f" "$LIB/adapters/$f"
done
install -o root -g root -m 644 "$REPO/engine/window.py" "$LIB/engine/window.py"
find "$LIB/adapters" -type d -exec chmod 755 {} +

# The window is runner's to run: check it can import what it needs, as runner.
sudo -u runner python3 -c "
import sys; sys.path.insert(0, '$LIB/engine')
import window
for language in ('python', 'typescript'):
    window.adapter(language)
print('45-engine: ok (window and adapters load as runner)')
" </dev/null
