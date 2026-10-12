#!/bin/bash
# macOS / Linux: double-click (or run) to start Porometry Analyzer.
# First run creates a private Python environment in ~/.venvs/porometry-analyzer and installs the dependencies.
cd "$(dirname "$0")" || exit 1
VENV="$HOME/.venvs/porometry-analyzer"   # outside the repo, so SyncThing never copies it
if [ ! -x "$VENV/bin/python" ]; then
  echo "Setting up Porometry Analyzer for the first time - this takes about a minute..."
  mkdir -p "$(dirname "$VENV")"; python3 -m venv "$VENV" || { echo "Install Python 3.10+ (python.org or 'brew install python') and try again."; read -r; exit 1; }
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -e ".[notebook]" || { echo "Installing dependencies failed."; read -r; exit 1; }
fi
exec "$VENV/bin/python" -m porometry "$@"
