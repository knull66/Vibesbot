#!/bin/bash
# Repara "Server failed" (ImportError run_dashboard / marked_equity):
# descarga desde GitHub main el launcher, ship_inflate y TODAS las partes
# .ship, reconstruye los archivos grandes, verifica el import y relanza.
set -e
LOG="$HOME/Library/Logs/Vibesbot-reparar.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════"
echo "  Vibesbot — Reparar instalación"
echo "════════════════════════════════════════"

APP_SRC=""
for d in \
  "$HOME/Applications/Vibesbot.app/Contents/Resources/vibesbot" \
  "/Applications/Vibesbot.app/Contents/Resources/vibesbot" \
  "$HOME/Downloads/Vibesbot" \
  "$HOME/Downloads/Vibesbot-1.51.1/Vibesbot-1.51.1" \
  "$(cd "$(dirname "$0")" && pwd)"
do
  if [ -f "$d/app_launcher.py" ] || [ -d "$d/.ship" ]; then
    APP_SRC="$d"
    break
  fi
done

if [ -z "$APP_SRC" ]; then
  echo "No encontré la instalación de Vibesbot."
  exit 1
fi

echo "Carpeta: $APP_SRC"
cd "$APP_SRC"

if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then kill -9 $PIDS 2>/dev/null || true; fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true
sleep 1

BASE="https://raw.githubusercontent.com/knull66/Vibesbot/main"
echo "→ Descargando launcher, ship_inflate y manifest..."
mkdir -p .ship src
curl -fsSL -o app_launcher.py "$BASE/app_launcher.py"
curl -fsSL -o src/ship_inflate.py "$BASE/src/ship_inflate.py"
curl -fsSL -o .ship/manifest.json "$BASE/.ship/manifest.json"
curl -fsSL -o VERSION "$BASE/VERSION" || true

echo "→ Reconstruyendo archivos grandes desde .ship (GitHub)..."
PYTHONPATH=. python3 - <<'PY'
from pathlib import Path
from src.ship_inflate import inflate_ship, verify_ship

root = Path(".")
restored = inflate_ship(root, fetch=True)
print("restaurados:", restored)
problems = verify_ship(root)
if problems:
    raise SystemExit(f"Quedan problemas: {problems}")
print("verify: OK")
PY

echo "→ Comprobando import del servidor..."
PYTHONPATH=. python3 - <<'PY'
from src.web_server import run_dashboard
from src.wallet_prediction import marked_equity
print("import OK:", run_dashboard.__name__, marked_equity(10, 2))
PY

echo ""
echo "Listo (v$(cat VERSION)). Abriendo Vibesbot..."
echo "Log: $LOG"
open -a Vibesbot 2>/dev/null || open "$HOME/Applications/Vibesbot.app" 2>/dev/null || true
