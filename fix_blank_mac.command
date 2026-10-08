#!/bin/bash
# Double-click if the Mac app opens blank after an update.
# Downloads v1.51.1, restores files from .ship, and launches.
set -e
DEST="${HOME}/Downloads/Vibesbot-1.51.1"
ZIP="${HOME}/Downloads/vibesbot-1.51.1.zip"
TAG="v1.51.1"

echo "Stopping old Vibesbot..."
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then kill -9 $PIDS 2>/dev/null || true; fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true
pkill -f "run_dashboard.py" 2>/dev/null || true
sleep 0.4

echo "Downloading ${TAG} from GitHub..."
curl -fsSL -o "$ZIP" "https://github.com/knull66/Vibesbot/zipball/${TAG}"

rm -rf "$DEST"
mkdir -p "$DEST"
unzip -q "$ZIP" -d "$DEST"
APP_DIR=$(find "$DEST" -maxdepth 1 -type d -name 'knull66-Vibesbot-*' | head -1)
if [ -z "$APP_DIR" ]; then
  echo "Could not find extracted folder."
  read -n 1 -s -r -p "Press any key to close"
  exit 1
fi

cd "$APP_DIR"
echo "Restoring full dashboard files..."
PYTHONPATH="." python3 -c "from src.ship_inflate import inflate_ship; print('restored', inflate_ship())"
echo "Version:"
cat VERSION
echo ""
echo "Starting Vibesbot..."
python3 app_launcher.py
