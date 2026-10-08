#!/bin/bash
# Crea Vibesbot.app con icono propio e instala en ~/Applications
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
for d in "$ROOT" "$ROOT/Vibesbot-1.51.1" "$HOME/Downloads/Vibesbot-1.51.1/Vibesbot-1.51.1" "$HOME/Downloads/Vibesbot"; do
  if [ -f "$d/build_simple_app.py" ] && [ -f "$d/app_launcher.py" ]; then
    ROOT="$d"
    break
  fi
done
cd "$ROOT"
echo "════════════════════════════════════════"
echo "  Vibesbot — instalador .app (macOS)"
echo "  Carpeta: $ROOT"
echo "════════════════════════════════════════"

if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then kill -9 $PIDS 2>/dev/null || true; fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true

echo "→ Actualizando archivos clave..."
curl -fsSL -o app_launcher.py "https://raw.githubusercontent.com/knull66/Vibesbot/main/app_launcher.py"
curl -fsSL -o build_simple_app.py "https://raw.githubusercontent.com/knull66/Vibesbot/main/build_simple_app.py"
curl -fsSL -o VERSION "https://raw.githubusercontent.com/knull66/Vibesbot/main/VERSION"
curl -fsSL -o src/round_signal.py "https://raw.githubusercontent.com/knull66/Vibesbot/main/src/round_signal.py"
mkdir -p scripts
curl -fsSL -o scripts/patch_server_boot.py \
  "https://raw.githubusercontent.com/knull66/Vibesbot/main/scripts/patch_server_boot.py" || true

python3 - <<'PY'
from pathlib import Path
p = Path("src/wallet_prediction.py")
t = p.read_text(encoding="utf-8")
orig = t
t = t.replace("MAX_SHARE_PRICE = 0.60", "MAX_SHARE_PRICE = 0.65")
t = t.replace("MIN_WIN_PNL_RATIO = 0.40", "MIN_WIN_PNL_RATIO = 0.35")
t = t.replace("need 20–60%", "need 20–65%")
t = t.replace("need 20-60%", "need 20-65%")
t = t.replace("Skip 61¢+", "Skip 66¢+")
if t != orig:
    p.write_text(t, encoding="utf-8")
    print("patched wallet_prediction: max share 65¢")
else:
    print("wallet_prediction filters already updated or markers missing")
r = Path("src/round_signal.py")
rt = r.read_text(encoding="utf-8")
rt2 = rt.replace("MIN_CONFIRM_MOVE = 10.0", "MIN_CONFIRM_MOVE = 5.0")
if rt2 != rt:
    r.write_text(rt2, encoding="utf-8")
    print("patched round_signal: confirm move $5")
PY

if [ -f scripts/patch_server_boot.py ]; then
  python3 scripts/patch_server_boot.py || true
fi

echo "→ Dependencias..."
python3 -m pip install --user -q \
  fastapi uvicorn jinja2 aiohttp pandas numpy ta lightgbm scikit-learn \
  websockets python-dotenv pyobjc-framework-WebKit pyobjc-framework-Cocoa || true

echo "→ Inflate .ship..."
PYTHONPATH=. python3 -c "from src.ship_inflate import inflate_ship; print(inflate_ship())" || true

echo "→ Construyendo Vibesbot.app + DMG..."
python3 build_simple_app.py

APP_SRC="$ROOT/dist/Vibesbot.app"
APP_DST="$HOME/Applications/Vibesbot.app"
mkdir -p "$HOME/Applications"
if [ -d "$APP_SRC" ]; then
  rm -rf "$APP_DST"
  cp -R "$APP_SRC" "$APP_DST"
  xattr -cr "$APP_DST" 2>/dev/null || true
  echo ""
  echo "✅ Instalado: $APP_DST"
  echo "   Abriendo (Dock debe mostrar icono Vibesbot, no Python)..."
  open "$APP_DST"
else
  echo "⚠ No se creó .app — abriendo con icono forzado vía launcher"
  python3 app_launcher.py
fi

echo ""
echo "Si macOS bloquea: clic derecho en Vibesbot.app → Abrir"
read -n 1 -s -r -p "Listo. Pulsa una tecla para cerrar esta ventana..."
