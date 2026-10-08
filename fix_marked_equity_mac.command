#!/bin/bash
# Repair ImportError: cannot import name 'marked_equity'
# Rebuilds src/wallet_prediction.py (+ other .ship files) from GitHub main.
set -e
LOG="$HOME/Library/Logs/Vibesbot-fix-equity.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════"
echo "  Vibesbot — fix marked_equity ImportError"
echo "════════════════════════════════════════"

APP_SRC=""
for d in \
  "$HOME/Applications/Vibesbot.app/Contents/Resources/vibesbot" \
  "/Applications/Vibesbot.app/Contents/Resources/vibesbot" \
  "$HOME/Downloads/Vibesbot" \
  "$HOME/Downloads/Vibesbot-1.51.1/Vibesbot-1.51.1" \
  "$(cd "$(dirname "$0")" && pwd)"
do
  if [ -f "$d/src/wallet_prediction.py" ] || [ -d "$d/.ship" ]; then
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

# Stop running app/server
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then kill -9 $PIDS 2>/dev/null || true; fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true
pkill -f "Vibesbot.app" 2>/dev/null || true
sleep 1

BASE="https://raw.githubusercontent.com/knull66/Vibesbot/main"
echo "→ Descargando ship_inflate + manifest + partes wallet..."
mkdir -p .ship src
curl -fsSL -o src/ship_inflate.py "$BASE/src/ship_inflate.py"
curl -fsSL -o .ship/manifest.json "$BASE/.ship/manifest.json"

python3 - <<'PY'
import base64, hashlib, json, urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/knull66/Vibesbot/main"
root = Path(".")
ship = root / ".ship"
manifest = json.loads((ship / "manifest.json").read_text(encoding="utf-8"))
want = {
    "src/wallet_prediction.py",
    "src/web_server.py",
    "src/updater.py",
    "web/static/app.js",
    "web/static/styles.css",
    "web/templates/index.html",
}
restored = []
for item in manifest:
    rel = item.get("path") or ""
    if rel not in want:
        continue
    digest = item.get("sha256") or ""
    parts = item.get("parts") or []
    buf = bytearray()
    for name in parts:
        url = f"{BASE}/.ship/{name}"
        part_path = ship / name
        try:
            data = urllib.request.urlopen(url, timeout=60).read()
            part_path.write_bytes(data if data.endswith(b"\n") else data + b"\n")
            raw = part_path.read_text(encoding="ascii").strip()
            buf.extend(base64.b64decode(raw, validate=False))
        except Exception as exc:
            print(f"FAIL part {name}: {exc}")
            buf = bytearray()
            break
    if not buf:
        continue
    data = bytes(buf)
    if hashlib.sha256(data).hexdigest() != digest:
        print(f"FAIL hash {rel}")
        continue
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    restored.append(rel)
    print(f"OK {rel} ({len(data)} bytes)")

try:
    ver = urllib.request.urlopen(f"{BASE}/VERSION", timeout=30).read().decode().strip()
    (root / "VERSION").write_text(ver + "\n", encoding="utf-8")
    print("VERSION", ver)
except Exception as exc:
    print("VERSION skip", exc)

print("restored", restored)
if "src/wallet_prediction.py" not in restored:
    raise SystemExit("No se pudo restaurar wallet_prediction.py")
text = (root / "src/wallet_prediction.py").read_text(encoding="utf-8")
if "marked_equity" not in text:
    raise SystemExit("wallet_prediction restaurado pero sin marked_equity")
print("marked_equity: OK")
PY

PYTHONPATH=. python3 -c "from src.ship_inflate import inflate_ship; print('inflate', inflate_ship())" || true

echo "→ Comprobando import..."
PYTHONPATH=. python3 - <<'PY'
from src.wallet_prediction import marked_equity
print("import marked_equity OK", marked_equity(10, 2))
PY

echo ""
echo "Listo. Abre Vibesbot.app de nuevo (Dock → Quit primero si sigue abierto)."
echo "Log: $LOG"
open -a Vibesbot 2>/dev/null || open "$HOME/Applications/Vibesbot.app" 2>/dev/null || true
