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

# Pick the first free port at or above 8000 unless the user pinned one.
# Anything else already running on 8000 (another dev server, for example)
# would otherwise be what the browser opens.
if [ -z "${PORT:-}" ]; then
  PORT=$(python - <<'EOF'
import socket
for port in range(8000, 8100):
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        continue
    probe.close()
    print(port)
    break
EOF
)
fi
[ -n "$PORT" ] || pause_and_exit "No free port found between 8000 and 8099."
URL="http://127.0.0.1:$PORT"

# Open the browser only after THIS app answers on the port, so a slow start
# never sends the browser to something else.
(
  python - "$URL" <<'EOF'
import sys, time, urllib.request
url = sys.argv[1]
for _ in range(60):
    time.sleep(0.5)
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            if b"metadata inspector" in resp.read(4096).lower():
                break
    except Exception:
        continue
else:
    sys.exit(1)
EOF
  if command -v open >/dev/null 2>&1; then open "$URL"; \
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
) &

echo ""
echo "Metadata Inspector is starting at $URL"
echo "Leave this window open while you use it. Press Ctrl+C to stop."
echo ""
python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
