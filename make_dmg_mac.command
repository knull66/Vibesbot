#!/bin/bash
# Doble clic en Mac: genera Vibesbot.app + Vibesbot-VERSION.dmg con icono.
set -e
cd "$(dirname "$0")"
echo "════════════════════════════════════════"
echo "  Vibesbot — build DMG (macOS)"
echo "════════════════════════════════════════"
PYTHONPATH=. python3 -c "from src.ship_inflate import inflate_ship; print('inflate', inflate_ship())" || true
python3 build_simple_app.py
VERSION=$(tr -d '[:space:]' < VERSION)
DMG="dist/Vibesbot-${VERSION}.dmg"
if [ -f "$DMG" ]; then
  echo ""
  echo "✅ Listo: $DMG"
  open "$(dirname "$DMG")"
else
  echo "❌ No se creó el DMG. ¿Estás en macOS?"
  read -n 1 -s -r -p "Pulsa una tecla..."
  exit 1
fi
