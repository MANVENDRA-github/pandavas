#!/usr/bin/env bash
# Install the pandavas skill into Claude Code (run from the repo root).
set -euo pipefail
DEST="${HOME}/.claude"
mkdir -p "$DEST/commands" "$DEST/skills" "$DEST/agents"
cp -r commands/* "$DEST/commands/"
cp -r skills/*   "$DEST/skills/"
cp -r agents/*   "$DEST/agents/"
echo "Installed the pandavas skill into Claude Code."
echo "  commands -> $DEST/commands   skills -> $DEST/skills   agents -> $DEST/agents"
echo
echo "Also install the engine so 'python -m pandavas' works:"
echo "  pip install -e .        # from this repo,  or:  pip install pandavas"
echo
echo "Then open Claude Code in any repo and type:  /pandavas . <task>"
