#!/bin/bash
# One-click launcher. On macOS, double-click this file in Finder; it opens a
# Terminal window, sets everything up on first run, starts the server, and
# opens the browser. Also works from a shell on Linux: ./start.command
set -euo pipefail

# Run from the project directory no matter where this was launched from,
# which is what makes double-clicking in Finder work.
cd "$(dirname "$0")"

pause_and_exit() {
  echo ""
  echo "$1"
  # Keep the Terminal window open on failure so the message is readable
  # before macOS closes it.
  read -n 1 -s -r -p "Press any key to close..." || true
  echo ""
  exit 1
}

command -v exiftool >/dev/null 2>&1 || pause_and_exit \
  "ExifTool is required but was not found.
Install it first:
  macOS:         brew install exiftool
  Debian/Ubuntu: sudo apt install libimage-exiftool-perl"

command -v python3 >/dev/null 2>&1 || pause_and_exit \
  "python3 was not found. Install Python 3.11 or newer from https://www.python.org"

if [ ! -d .venv ]; then
  echo "First run: creating a virtual environment (one-time, takes a minute)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -r requirements.txt

PORT="${PORT:-8000}"
URL="http://127.0.0.1:$PORT"

# Open the browser once the server has had a moment to bind. Backgrounded so
# uvicorn stays in the foreground and Ctrl+C stops everything.
(
  sleep 1.5
  if command -v open >/dev/null 2>&1; then open "$URL"; \
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
) &

echo ""
echo "Metadata Inspector is starting at $URL"
echo "Leave this window open while you use it. Press Ctrl+C to stop."
echo ""
python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
