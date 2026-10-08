#!/bin/bash
# Arregla Server failed en ~/Downloads/Vibesbot-1.51.1/Vibesbot-1.51.1
set -e

CANDIDATES=(
  "$HOME/Downloads/Vibesbot-1.51.1/Vibesbot-1.51.1"
  "$HOME/Downloads/Vibesbot-1.51.1"
  "$HOME/Downloads/Vibesbot"
  "$(cd "$(dirname "$0")" && pwd)"
)

ROOT=""
for d in "${CANDIDATES[@]}"; do
  if [ -f "$d/app_launcher.py" ] && [ -f "$d/src/web_server.py" ]; then
    ROOT="$d"
    break
  fi
done

if [ -z "$ROOT" ]; then
  echo "No encuentro Vibesbot. Abre este .command DENTRO de la carpeta del proyecto."
  read -n 1 -s -r -p "Pulsa una tecla..."
  exit 1
fi

cd "$ROOT"
LOG="$HOME/Library/Logs/Vibesbot.log"
mkdir -p "$(dirname "$LOG")"
echo "Usando: $ROOT"
echo "$(date) fix_1511 start cwd=$ROOT" >> "$LOG"

echo "Parando procesos viejos..."
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then kill -9 $PIDS 2>/dev/null || true; fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true
pkill -f "run_dashboard.py" 2>/dev/null || true
sleep 0.4

echo "Descargando launcher + patch 1.51.3..."
curl -fsSL -o app_launcher.py "https://raw.githubusercontent.com/knull66/Vibesbot/main/app_launcher.py"
curl -fsSL -o VERSION "https://raw.githubusercontent.com/knull66/Vibesbot/main/VERSION"
mkdir -p scripts
curl -fsSL -o scripts/patch_server_boot.py \
  "https://raw.githubusercontent.com/knull66/Vibesbot/main/scripts/patch_server_boot.py"

echo "Aplicando parche anti-timeout..."
python3 scripts/patch_server_boot.py | tee -a "$LOG"

echo "Inflate .ship (por si faltan archivos)..."
PYTHONPATH=. python3 -c "from src.ship_inflate import inflate_ship; print('inflate', inflate_ship())" | tee -a "$LOG" || true

echo "Probando import del servidor..."
PYTHONPATH=. python3 - <<'PY' 2>&1 | tee -a "$HOME/Library/Logs/Vibesbot.log"
import traceback
try:
    from src.web_server import run_dashboard
    print("import OK")
    import pathlib
    t = pathlib.Path("src/web_server.py").read_text()
    print("has_healthz", "/healthz" in t)
    print("has_boot", "asyncio.create_task(_boot())" in t)
except Exception:
    traceback.print_exc()
    raise
PY

echo ""
echo "Arrancando Vibesbot..."
echo "$(date) launching app_launcher" >> "$LOG"
exec python3 app_launcher.py
