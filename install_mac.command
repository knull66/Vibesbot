#!/bin/bash
# ═══════════════════════════════════════════════════════════
#   ⚡ VIBESBOT - Instalador para macOS
#   Crea una app nativa con ventana WebKit
# ═══════════════════════════════════════════════════════════

cd "$(dirname "$0")"

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║   ⚡ VIBESBOT - Instalador macOS                          ║"
echo "║   Creando aplicación nativa...                            ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# 1. Actualizar pip (IMPORTANTE - resuelve el error de pyobjc-core)
echo "📦 Paso 1/4: Actualizando pip..."
python3 -m pip install --upgrade pip --quiet

# 2. Instalar dependencias del servidor
echo "📦 Paso 2/4: Instalando dependencias del servidor..."
python3 -m pip install --quiet \
    fastapi uvicorn jinja2 aiohttp \
    pandas numpy ta lightgbm xgboost scikit-learn \
    websockets python-dotenv

# 3. Instalar WebKit para ventana nativa
echo "📦 Paso 3/4: Instalando framework WebKit nativo..."
python3 -m pip install --quiet pyobjc-framework-WebKit pyobjc-framework-Cocoa

# 4. Crear la aplicación
echo "📦 Paso 4/4: Creando Vibesbot.app..."

APP_NAME="Vibesbot"
APP_PATH="$HOME/Applications/$APP_NAME.app"
CONTENTS="$APP_PATH/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
PROJECT_DIR="$(pwd)"

# Crear estructura
mkdir -p "$MACOS" "$RESOURCES"

# Info.plist
cat > "$CONTENTS/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIdentifier</key>
    <string>com.vibesbot.trading</string>
    <key>CFBundleName</key>
    <string>Vibesbot</string>
    <key>CFBundleDisplayName</key>
    <string>Vibesbot Trading</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

# Guardar ruta del proyecto
echo "$PROJECT_DIR" > "$RESOURCES/project_path.txt"

# Script Python nativo
cat > "$MACOS/vibesbot_app.py" << 'PYTHONSCRIPT'
#!/usr/bin/env python3
"""Vibesbot - Aplicación nativa macOS con WebKit"""
import os
import sys
import subprocess
import threading
import time

# Leer ruta del proyecto
resources_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Resources")
with open(os.path.join(resources_path, "project_path.txt")) as f:
    PROJECT_PATH = f.read().strip()

sys.path.insert(0, PROJECT_PATH)
os.chdir(PROJECT_PATH)

def start_server():
    """Inicia el servidor FastAPI"""
    subprocess.run([
        sys.executable, "-c",
        "from src.web_server import run_dashboard; run_dashboard(port=8080)"
    ], cwd=PROJECT_PATH)

def create_native_window():
    """Crea ventana nativa con WebKit"""
    import objc
    from Foundation import NSObject, NSURL, NSURLRequest, NSMakeRect
    from AppKit import (
        NSApplication, NSWindow, NSApp,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
        NSBackingStoreBuffered, NSApplicationActivationPolicyRegular,
        NSScreen
    )
    from WebKit import WKWebView, WKWebViewConfiguration
    
    class AppDelegate(NSObject):
        window = objc.ivar()
        webView = objc.ivar()
        
        def applicationDidFinishLaunching_(self, notification):
            time.sleep(2)
            
            config = WKWebViewConfiguration.alloc().init()
            self.webView = WKWebView.alloc().initWithFrame_configuration_(
                NSMakeRect(0, 0, 1400, 900), config
            )
            
            style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                    NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
            
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 1400, 900), style, NSBackingStoreBuffered, False
            )
            
            self.window.setTitle_("⚡ Vibesbot Trading Radar")
            self.window.setContentView_(self.webView)
            self.window.center()
            self.window.makeKeyAndOrderFront_(None)
            
            url = NSURL.URLWithString_("http://localhost:8080")
            request = NSURLRequest.requestWithURL_(url)
            self.webView.loadRequest_(request)
            
            NSApp.activateIgnoringOtherApps_(True)
        
        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
            return True
    
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()

if __name__ == "__main__":
    # Matar servidor anterior
    os.system("pkill -f 'uvicorn.*web_server' 2>/dev/null")
    
    # Servidor en thread separado
    server = threading.Thread(target=start_server, daemon=True)
    server.start()
    
    # Ventana nativa
    create_native_window()
PYTHONSCRIPT

chmod +x "$MACOS/vibesbot_app.py"

# Launcher
cat > "$MACOS/launcher" << LAUNCHER
#!/bin/bash
cd "\$(dirname "\$0")"
exec python3 "\$(dirname "\$0")/vibesbot_app.py"
LAUNCHER

chmod +x "$MACOS/launcher"

echo ""
echo "════════════════════════════════════════════════════════════"
echo ""
echo "   ✅ ¡INSTALACIÓN COMPLETADA!"
echo ""
echo "   📍 La app está en: ~/Applications/Vibesbot.app"
echo ""
echo "   Para abrirla:"
echo "   • Abre Finder → Ve a tu carpeta personal → Applications"
echo "   • Doble clic en Vibesbot"
echo ""
echo "   O ejecuta en terminal:"
echo "   open ~/Applications/Vibesbot.app"
echo ""
echo "════════════════════════════════════════════════════════════"
echo ""

# Preguntar si abrir ahora
read -p "¿Abrir Vibesbot ahora? (s/n): " answer
if [[ "$answer" =~ ^[Ss]$ ]]; then
    open "$APP_PATH"
fi
