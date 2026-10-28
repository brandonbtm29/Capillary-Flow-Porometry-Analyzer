#!/bin/bash
# macOS / Linux: double-click (or run) to start Capillary Flow Porometry Analyzer.
# First run creates a private Python environment in ~/.venvs/porometry-analyzer and installs the dependencies.
# Then it starts the app in the background and closes this Terminal window. Errors after start-up go to
# ~/Library/Logs/PorometryAnalyzer/porometry.log.
cd "$(dirname "$0")" || exit 1
VENV="$HOME/.venvs/porometry-analyzer"   # outside the repo, so SyncThing never copies it
if [ ! -x "$VENV/bin/python" ]; then
  echo "Setting up Capillary Flow Porometry Analyzer for the first time - this takes about a minute..."
  mkdir -p "$(dirname "$VENV")"; python3 -m venv "$VENV" || { echo "Install Python 3.10+ (python.org or 'brew install python') and try again."; read -r; exit 1; }
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -e ".[notebook]" || { echo "Installing dependencies failed."; read -r; exit 1; }
fi
PY="$VENV/bin/python"

# Quick check here, so a broken install shows an error instead of nothing happening.
if ! "$PY" -c "import PyQt6.QtWidgets, matplotlib, porometry"; then
  echo
  echo "The app can't start: its Python packages are missing or broken. Copy the messages above when asking for help."
  echo "To reinstall them, run this in Terminal, then double-click this file again:"
  echo "  rm -rf ~/.venvs/porometry-analyzer"
  read -r -p "Press Enter to close"
  exit 1
fi

# App icon in ~/Applications, made once (Settings > Create app icon remakes it)
[ -f "$VENV/.shortcut-made" ] || "$PY" -m porometry.shortcuts

# Start the app in its own session (so closing this window doesn't stop it), passing on any files or
# folders given to this script, then ask Terminal to close this window once the script has finished.
"$PY" - "$PY" "$(tty)" "$@" <<'PYEOF'
import subprocess, sys
python, tty, args = sys.argv[1], sys.argv[2], sys.argv[3:]
quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
subprocess.Popen([python, "-m", "porometry", *args], **quiet)
script = (
    "delay 1\n"
    'tell application "Terminal"\n'
    "  repeat with w in (every window)\n"
    f'    if tty of selected tab of w is "{tty}" then close w\n'
    "  end repeat\n"
    "end tell"
)
try:
    subprocess.Popen(["osascript", "-e", script], **quiet)
except OSError:
    pass
PYEOF
exit 0
