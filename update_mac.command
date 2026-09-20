#!/bin/bash
# Double-click this file on your Mac to pull v1.13.0+ and rebuild Vibesbot.app
set -e
cd "$(dirname "$0")"

echo "Updating Vibesbot from GitHub..."
if [ ! -d .git ]; then
  echo "This folder is not a git clone."
  echo "Run this instead:"
  echo "  cd ~/Downloads"
  echo "  git clone https://github.com/knull66/Vibesbot.git"
  echo "  cd Vibesbot"
  echo "  python3 build_simple_app.py"
  read -n 1 -s -r -p "Press any key to close"
  exit 1
fi

git fetch origin main
git pull origin main

echo "Building native app..."
python3 build_simple_app.py

echo ""
echo "Done. Open dist/Vibesbot.app (or copy it to /Applications)."
echo "Current version:"
cat VERSION
echo ""
read -n 1 -s -r -p "Press any key to close"
