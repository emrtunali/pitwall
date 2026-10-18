#!/bin/bash
# Double-click to open Pitwall on macOS. First run sets everything up (about a minute);
# after that it just checks for new races and opens the browser.
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Enter to close…"; exit 1
fi
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import httpx, numpy" 2>/dev/null; then
  echo "First run: setting up Pitwall…"
  "$PY" -m venv .venv && .venv/bin/pip install --quiet --upgrade pip && .venv/bin/pip install --quiet -e . || {
    read -r -p "Setup failed. Press Enter to close…"; exit 1; }
fi
# Run as a module from this folder: Python 3.13 ignores "hidden" .pth files, and macOS marks files in some
# folders (e.g. Desktop) hidden, which would break the installed `pitwall` command.
.venv/bin/python -m pitwall serve
