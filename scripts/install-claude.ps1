# Install the pandavas skill into Claude Code (run from the repo root).
$dest = Join-Path $HOME ".claude"
New-Item -ItemType Directory -Force -Path "$dest\commands","$dest\skills","$dest\agents" | Out-Null
Copy-Item -Recurse -Force commands\* "$dest\commands\"
Copy-Item -Recurse -Force skills\*   "$dest\skills\"
Copy-Item -Recurse -Force agents\*   "$dest\agents\"
Write-Host "Installed the pandavas skill into Claude Code -> $dest"
Write-Host ""
Write-Host "Also install the engine so 'python -m pandavas' works:"
Write-Host "  pip install -e .        # from this repo,  or:  pip install pandavas"
Write-Host ""
Write-Host "Then open Claude Code in any repo and type:  /pandavas . <task>"
