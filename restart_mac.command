#!/bin/bash
# Double-click to stop the leftover engine and start the latest Vibesbot.
cd "$(dirname "$0")"

echo "Stopping leftover Vibesbot on port 8080..."
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    kill -9 $PIDS 2>/dev/null || true
  fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true
pkill -f "run_dashboard.py" 2>/dev/null || true
sleep 0.6

if [ -d .git ]; then
  echo "Pulling latest from GitHub..."
  git fetch origin main
  git pull origin main
fi

echo "Starting Vibesbot..."
if [ -f app_launcher.py ]; then
  python3 app_launcher.py
  exit $?
fi

if [ -d "/Applications/Vibesbot.app" ]; then
  open -n "/Applications/Vibesbot.app"
elif [ -d "$HOME/Downloads/Vibesbot.app" ]; then
  open -n "$HOME/Downloads/Vibesbot.app"
elif [ -d "dist/Vibesbot.app" ]; then
  open -n "dist/Vibesbot.app"
else
  echo "Could not find Vibesbot.app"
  read -n 1 -s -r -p "Press any key to close"
  exit 1
fi
