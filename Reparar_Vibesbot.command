#!/bin/bash
# Repara "Server failed" reconstruyendo los archivos grandes desde .ship.
# Nunca sustituye un archivo bueno por un stub de 0 bytes descargado de main.
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
  "$HOME/Downloads/Vibesbot-1.52.0" \
  "$HOME/Downloads/Vibesbot-1.49.0" \
  "$(cd "$(dirname "$0")" && pwd)"
do
  if [ -f "$d/app_launcher.py" ] || [ -d "$d/.ship" ]; then
    APP_SRC="$d"
    break
  fi
done

if [ -z "$APP_SRC" ]; then
  echo "No encontré la instalación de Vibesbot."
  echo "Instala primero desde la carpeta del proyecto (Instalar_Vibesbot.command)."
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

mkdir -p .ship src

# Prefer local ship_inflate + manifest. Only refresh them from GitHub if missing.
BASE="https://raw.githubusercontent.com/knull66/Vibesbot/main"
if [ ! -f src/ship_inflate.py ]; then
  curl -fsSL -o src/ship_inflate.py "$BASE/src/ship_inflate.py" || true
fi
if [ ! -f .ship/manifest.json ]; then
  curl -fsSL -o .ship/manifest.json "$BASE/.ship/manifest.json" || true
fi

if [ ! -f src/ship_inflate.py ] || [ ! -f .ship/manifest.json ]; then
  echo "ERROR: faltan src/ship_inflate.py o .ship/manifest.json"
  exit 1
fi

echo "→ Reconstruyendo archivos grandes desde .ship..."
PYTHONPATH=. python3 - <<'PY'
from pathlib import Path
from src.ship_inflate import inflate_ship, verify_ship

root = Path(".")
# Local parts first — do not fetch yet (main may still have incomplete pieces).
restored = inflate_ship(root, fetch=False)
print("locales:", restored)
problems = verify_ship(root)
if problems:
    print("faltan piezas locales, intentando GitHub raw...", problems)
    restored = inflate_ship(root, fetch=True)
    print("remotos:", restored)
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
echo "Listo (v$(tr -d '[:space:]' < VERSION 2>/dev/null || echo '?')). Abriendo Vibesbot..."
echo "Log: $LOG"
open -a Vibesbot 2>/dev/null || open "$HOME/Applications/Vibesbot.app" 2>/dev/null || true
