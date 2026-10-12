#!/bin/bash
# macOS / Linux: opens your working copy of the comparison notebook in JupyterLab
# (sets up ~/.venvs/porometry-analyzer the first time).
# The working copy (with your plots and numbers) lives in SyncThing, not in this public repo:
#   ~/SyncThing/UAkron Playground/Capillary Flow Porometer/Notebooks/compare_conditions.ipynb
# It is copied from examples/compare_conditions.ipynb the first time. Set UAKRON_DATA_DIR to use another root.
REPO="$(cd "$(dirname "$0")" && pwd)" || exit 1
VENV="$HOME/.venvs/porometry-analyzer"   # outside the repo and SyncThing
ROOT="${UAKRON_DATA_DIR:-$HOME/SyncThing/UAkron Playground}"
NBDIR="$ROOT/Capillary Flow Porometer/Notebooks"
if [ ! -x "$VENV/bin/jupyter-lab" ]; then
  mkdir -p "$(dirname "$VENV")"
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV" || { echo "Install Python 3.10+ (python.org or 'brew install python') and try again."; read -r; exit 1; }
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -e "$REPO[notebook]" || { echo "Installing dependencies failed."; read -r; exit 1; }
fi
mkdir -p "$NBDIR"
[ -f "$NBDIR/compare_conditions.ipynb" ] || cp "$REPO/examples/compare_conditions.ipynb" "$NBDIR/"
cd "$NBDIR" || exit 1
exec "$VENV/bin/jupyter-lab" compare_conditions.ipynb
