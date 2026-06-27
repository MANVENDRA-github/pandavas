#!/usr/bin/env bash
# Install the pandavas skill into Cursor (run from the repo root).
set -euo pipefail
DEST="${HOME}/.cursor"
mkdir -p "$DEST/commands" "$DEST/skills"
cp -r commands/* "$DEST/commands/"
cp -r skills/*   "$DEST/skills/"
echo "Installed the pandavas skill into Cursor."
echo "  commands -> $DEST/commands   skills -> $DEST/skills"
echo
echo "Note: Cursor has no subagent primitive, so the judge (Sahadeva) runs as a"
echo "fresh-pass self-review in shared context - weaker independence than Claude"
echo "Code's subagent. The deterministic gates (run-tests, judge-gate, decide) are"
echo "identical on both harnesses. For strict judge isolation use Claude Code, or"
echo "run the standalone engine:  python -m pandavas run --repo . --task \"...\""
echo
echo "Also install the engine:  pip install -e .   (so 'python -m pandavas' works)"
echo "Then in Cursor, in any repo, type:  /pandavas . <task>"
