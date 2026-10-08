#!/bin/bash
# Fix "Server failed" splash on Mac, then launch.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
LOG="${HOME}/Library/Logs/Vibesbot.log"
mkdir -p "$(dirname "$LOG")"

echo "Stopping old Vibesbot on :8080..."
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then kill -9 $PIDS 2>/dev/null || true; fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true
sleep 0.3

echo "Updating launcher + patch script from GitHub..."
curl -fsSL -o app_launcher.py "https://raw.githubusercontent.com/knull66/Vibesbot/main/app_launcher.py"
curl -fsSL -o VERSION "https://raw.githubusercontent.com/knull66/Vibesbot/main/VERSION" || echo "1.51.3" > VERSION
mkdir -p scripts
curl -fsSL -o scripts/patch_server_boot.py \
  "https://raw.githubusercontent.com/knull66/Vibesbot/main/scripts/patch_server_boot.py" \
  || true

if [ -f scripts/patch_server_boot.py ]; then
  python3 scripts/patch_server_boot.py
else
  echo "patch script missing; inflate .ship if present"
  PYTHONPATH=. python3 -c "from src.ship_inflate import inflate_ship; print(inflate_ship())" || true
fi

echo "$(date) fix_server_mac v$(cat VERSION 2>/dev/null)" >> "$LOG"
echo "Starting Vibesbot..."
python3 app_launcher.py
