#!/bin/bash
# Instala Vibesbot.app desde ESTA carpeta (código local).
# No descarga src/web_server.py ni otros archivos grandes desde GitHub main:
# main ha llegado a publicar stubs de 0 bytes y eso deja la app sin abrir.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
for d in "$ROOT" "$ROOT/Vibesbot-1.52.0" "$HOME/Downloads/Vibesbot"; do
  if [ -f "$d/build_simple_app.py" ] && [ -f "$d/app_launcher.py" ]; then
    ROOT="$d"
    break
  fi
done
cd "$ROOT"
echo "════════════════════════════════════════"
echo "  Vibesbot — instalador .app (macOS)"
echo "  Carpeta: $ROOT"
echo "  Versión: $(tr -d '[:space:]' < VERSION 2>/dev/null || echo '?')"
echo "════════════════════════════════════════"

if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then kill -9 $PIDS 2>/dev/null || true; fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true

# Rebuild large files from local .ship if any are empty/missing.
if [ -f src/ship_inflate.py ] && [ -f .ship/manifest.json ]; then
  echo "→ Comprobando archivos grandes (.ship local)..."
  PYTHONPATH=. python3 - <<'PY'
from pathlib import Path
from src.ship_inflate import inflate_ship, verify_ship
restored = inflate_ship(Path("."), fetch=False)
if restored:
    print("restaurados:", ", ".join(restored))
problems = verify_ship(Path("."))
if problems:
    raise SystemExit("Archivos incompletos: " + ", ".join(f"{k}={v}" for k, v in problems.items()))
print("verify: OK")
PY
fi

BYTES=$(wc -c < src/web_server.py | tr -d ' ')
if [ "$BYTES" -lt 10000 ] || ! grep -q "def run_dashboard" src/web_server.py; then
  echo "ERROR: src/web_server.py está vacío o incompleto ($BYTES bytes)."
  echo "Usa la carpeta completa de la versión, no un zip a medias."
  exit 1
fi
echo "→ web_server.py = $BYTES bytes"

echo "→ Dependencias..."
python3 -m pip install --user -q \
  fastapi uvicorn jinja2 aiohttp pandas numpy ta lightgbm scikit-learn \
  websockets python-dotenv pyobjc-framework-WebKit pyobjc-framework-Cocoa || true

echo "→ Construyendo Vibesbot.app..."
python3 build_simple_app.py

APP_SRC="$ROOT/dist/Vibesbot.app"
APP_DST="$HOME/Applications/Vibesbot.app"
mkdir -p "$HOME/Applications"
if [ -d "$APP_SRC" ]; then
  rm -rf "$APP_DST"
  cp -R "$APP_SRC" "$APP_DST"
  xattr -cr "$APP_DST" 2>/dev/null || true
  echo ""
  echo "Instalado: $APP_DST"
  open "$APP_DST"
else
  echo "No se creó .app — lanzando launcher"
  python3 app_launcher.py
fi

echo ""
echo "Si macOS bloquea: clic derecho en Vibesbot.app → Abrir"
echo "No uses Check update / Install hasta que main en GitHub tenga el servidor completo."
read -n 1 -s -r -p "Listo. Pulsa una tecla para cerrar..."
