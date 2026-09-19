#!/bin/bash
# ═══════════════════════════════════════════════════════════
# VIBESBOT - Build DMG Installer for macOS
# ═══════════════════════════════════════════════════════════

set -e

APP_NAME="Vibesbot"
VERSION="1.0.0"
BUNDLE_ID="com.vibesbot.app"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
APP_DIR="$BUILD_DIR/$APP_NAME.app"
DMG_NAME="$APP_NAME-$VERSION.dmg"

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   ⚡ VIBESBOT DMG BUILDER                                 ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Limpiar build anterior
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo "📁 Creando estructura de la app..."

# Crear estructura .app
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"
mkdir -p "$APP_DIR/Contents/Resources/app"

# Copiar todo el código
echo "📦 Copiando código fuente..."
cp -r "$SCRIPT_DIR/src" "$APP_DIR/Contents/Resources/app/"
cp -r "$SCRIPT_DIR/web" "$APP_DIR/Contents/Resources/app/"
cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/Contents/Resources/app/"
cp "$SCRIPT_DIR/config.example.json" "$APP_DIR/Contents/Resources/app/"
cp "$SCRIPT_DIR/SETUP.md" "$APP_DIR/Contents/Resources/app/" 2>/dev/null || true
cp "$SCRIPT_DIR/README.md" "$APP_DIR/Contents/Resources/app/" 2>/dev/null || true

# Crear directorios necesarios
mkdir -p "$APP_DIR/Contents/Resources/app/models"
mkdir -p "$APP_DIR/Contents/Resources/app/logs"
mkdir -p "$APP_DIR/Contents/Resources/app/user_data"

# Info.plist
echo "📝 Creando Info.plist..."
cat > "$APP_DIR/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.finance</string>
</dict>
</plist>
EOF

# Crear icono
echo "🎨 Creando icono..."
cat > "$APP_DIR/Contents/Resources/icon.svg" << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="90" fill="#0a0a0f"/>
  <circle cx="256" cy="256" r="160" fill="none" stroke="#00ff88" stroke-width="8" opacity="0.3"/>
  <circle cx="256" cy="256" r="100" fill="none" stroke="#00ff88" stroke-width="8" opacity="0.5"/>
  <circle cx="256" cy="256" r="40" fill="#00ff88"/>
  <line x1="256" y1="96" x2="256" y2="140" stroke="#00ff88" stroke-width="6" opacity="0.8"/>
  <line x1="256" y1="372" x2="256" y2="416" stroke="#00ff88" stroke-width="6" opacity="0.8"/>
  <line x1="96" y1="256" x2="140" y2="256" stroke="#00ff88" stroke-width="6" opacity="0.8"/>
  <line x1="372" y1="256" x2="416" y2="256" stroke="#00ff88" stroke-width="6" opacity="0.8"/>
</svg>
EOF

# Launcher script
echo "🚀 Creando launcher..."
cat > "$APP_DIR/Contents/MacOS/launcher" << 'LAUNCHER'
#!/bin/bash

APP_DIR="$(dirname "$0")/../Resources/app"
cd "$APP_DIR"

# Buscar Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif [ -f "/opt/homebrew/bin/python3" ]; then
    PYTHON=/opt/homebrew/bin/python3
elif [ -f "/usr/local/bin/python3" ]; then
    PYTHON=/usr/local/bin/python3
else
    osascript -e 'display dialog "Python3 no encontrado.\n\nInstala Python desde:\nhttps://www.python.org/downloads/" buttons {"Descargar Python", "Cancelar"} default button "Descargar Python"' -e 'if button returned of result is "Descargar Python" then open location "https://www.python.org/downloads/"'
    exit 1
fi

# Verificar/instalar dependencias
if ! $PYTHON -c "import fastapi" 2>/dev/null; then
    osascript -e 'display dialog "Instalando dependencias...\nEsto puede tomar unos minutos." buttons {"OK"} default button "OK" giving up after 3'
    $PYTHON -m pip install -q -r requirements.txt 2>/dev/null
fi

# Abrir navegador y ejecutar servidor
sleep 1 && open "http://localhost:8080" &

# Ejecutar dashboard
export PYTHONPATH="$APP_DIR"
$PYTHON -c "
import sys
sys.path.insert(0, '$APP_DIR')
from src.web_server import run_dashboard
run_dashboard(port=8080)
"
LAUNCHER

chmod +x "$APP_DIR/Contents/MacOS/launcher"

# Crear DMG
echo "💿 Creando DMG..."
if command -v hdiutil &> /dev/null; then
    # Crear DMG temporal
    hdiutil create -volname "$APP_NAME" -srcfolder "$APP_DIR" -ov -format UDZO "$BUILD_DIR/$DMG_NAME"
    echo ""
    echo "✅ DMG creado: $BUILD_DIR/$DMG_NAME"
else
    echo "⚠️  hdiutil no disponible (no estás en macOS)"
    echo "✅ App creada: $APP_DIR"
    echo ""
    echo "Para crear el DMG, ejecuta en macOS:"
    echo "  hdiutil create -volname Vibesbot -srcfolder $APP_DIR -format UDZO Vibesbot.dmg"
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   ✅ BUILD COMPLETADO                                     ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "║                                                           ║"
echo "║   Para instalar:                                          ║"
echo "║   1. Abre el DMG                                          ║"
echo "║   2. Arrastra Vibesbot a Applications                     ║"
echo "║   3. Abre Vibesbot desde Applications                     ║"
echo "║                                                           ║"
echo "║   Primera vez que abres:                                  ║"
echo "║   - Click derecho → Abrir (bypass Gatekeeper)             ║"
echo "║   - Se instalarán dependencias automáticamente            ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
