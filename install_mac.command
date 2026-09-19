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
import urllib.request
import traceback

# Log file para debug
LOG_FILE = os.path.expanduser("~/Library/Logs/Vibesbot.log")

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
    print(msg)

# Leer ruta del proyecto
try:
    resources_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Resources")
    with open(os.path.join(resources_path, "project_path.txt")) as f:
        PROJECT_PATH = f.read().strip()
    log(f"Project path: {PROJECT_PATH}")
except Exception as e:
    PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if PROJECT_PATH.endswith(".app"):
        PROJECT_PATH = PROJECT_PATH[:-4]
    log(f"Fallback project path: {PROJECT_PATH}")

sys.path.insert(0, PROJECT_PATH)
os.chdir(PROJECT_PATH)

SERVER_PROCESS = None
SERVER_ERROR = None

def start_server():
    """Inicia el servidor FastAPI usando uvicorn directamente"""
    global SERVER_PROCESS, SERVER_ERROR
    
    log("Starting server...")
    
    # Usar uvicorn directamente es más confiable
    server_script = f'''
import sys
import os
sys.path.insert(0, "{PROJECT_PATH}")
os.chdir("{PROJECT_PATH}")

try:
    import uvicorn
    from src.web_server import create_app
    from src.config import load_config
    
    config = load_config()
    app = create_app(config)
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
except Exception as e:
    import traceback
    with open("{LOG_FILE}", "a") as f:
        f.write("SERVER ERROR: " + str(e) + "\\n")
        f.write(traceback.format_exc() + "\\n")
    raise
'''
    
    try:
        SERVER_PROCESS = subprocess.Popen(
            [sys.executable, "-c", server_script],
            cwd=PROJECT_PATH,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": PROJECT_PATH}
        )
        
        # Leer output del servidor
        for line in iter(SERVER_PROCESS.stdout.readline, b''):
            line_str = line.decode('utf-8', errors='ignore').strip()
            if line_str:
                log(f"Server: {line_str}")
        
        SERVER_PROCESS.wait()
        log(f"Server exited with code: {SERVER_PROCESS.returncode}")
        
    except Exception as e:
        SERVER_ERROR = str(e)
        log(f"Server error: {e}")
        log(traceback.format_exc())

def create_native_window():
    """Crea ventana nativa con WebKit"""
    import objc
    from Foundation import NSObject, NSURL, NSURLRequest, NSMakeRect, NSTimer
    from AppKit import (
        NSApplication, NSWindow, NSApp,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
        NSBackingStoreBuffered, NSApplicationActivationPolicyRegular
    )
    from WebKit import WKWebView, WKWebViewConfiguration
    
    class AppDelegate(NSObject):
        window = objc.ivar()
        webView = objc.ivar()
        loadTimer = objc.ivar()
        loadAttempts = objc.ivar()
        
        def applicationDidFinishLaunching_(self, notification):
            self.loadAttempts = 0
            
            config = WKWebViewConfiguration.alloc().init()
            self.webView = WKWebView.alloc().initWithFrame_configuration_(
                NSMakeRect(0, 0, 1400, 900), config
            )
            
            style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                    NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
            
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 1400, 900), style, NSBackingStoreBuffered, False
            )
            
            self.window.setTitle_("⚡ Vibesbot - Iniciando...")
            self.window.setContentView_(self.webView)
            self.window.center()
            self.window.makeKeyAndOrderFront_(None)
            
            loading_html = """
            <html>
            <head><style>
                body { background: #0a0a0f; color: #00ff88; font-family: -apple-system, sans-serif;
                       display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
                .container { text-align: center; }
                .title { font-size: 48px; margin-bottom: 20px; }
                .spinner { width: 50px; height: 50px; border: 3px solid #1a1a2e; border-top: 3px solid #00ff88;
                           border-radius: 50%; animation: spin 1s linear infinite; margin: 20px auto; }
                @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                .status { color: #888; font-size: 14px; }
            </style></head>
            <body><div class="container">
                <div class="title">⚡ VIBESBOT</div>
                <div class="spinner"></div>
                <div class="status">Iniciando servidor...</div>
            </div></body></html>
            """
            self.webView.loadHTMLString_baseURL_(loading_html, None)
            
            NSApp.activateIgnoringOtherApps_(True)
            
            self.loadTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0, self, "tryLoadURL:", None, True
            )
        
        def tryLoadURL_(self, timer):
            self.loadAttempts += 1
            log(f"Load attempt {self.loadAttempts}")
            
            try:
                response = urllib.request.urlopen("http://127.0.0.1:8080", timeout=2)
                log("Server responded!")
                timer.invalidate()
                self.window.setTitle_("⚡ Vibesbot Trading Radar")
                url = NSURL.URLWithString_("http://127.0.0.1:8080")
                request = NSURLRequest.requestWithURL_(url)
                self.webView.loadRequest_(request)
            except Exception as e:
                if self.loadAttempts > 45:
                    timer.invalidate()
                    log(f"Failed to connect after {self.loadAttempts} attempts")
                    
                    # Leer log de errores
                    error_detail = ""
                    try:
                        with open(LOG_FILE, "r") as f:
                            lines = f.readlines()[-20:]
                            error_detail = "<br>".join(lines)
                    except:
                        error_detail = str(e)
                    
                    error_html = f"""
                    <html><body style="background:#0a0a0f;color:#ff4444;font-family:sans-serif;padding:40px;">
                    <h1>Error de Conexión</h1>
                    <p>No se pudo iniciar el servidor</p>
                    <p style="color:#888">Ejecuta en Terminal para ver el error:</p>
                    <pre style="background:#1a1a2e;padding:15px;border-radius:8px;color:#00ff88;overflow:auto;">
cd {PROJECT_PATH}
python3 run_dashboard.py</pre>
                    <p style="color:#666;font-size:12px;margin-top:20px;">Log: ~/Library/Logs/Vibesbot.log</p>
                    </body></html>
                    """
                    self.webView.loadHTMLString_baseURL_(error_html, None)
        
        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
            return True
        
        def applicationWillTerminate_(self, notification):
            log("App terminating, killing server...")
            if SERVER_PROCESS:
                SERVER_PROCESS.terminate()
            os.system("pkill -f 'uvicorn.*8080' 2>/dev/null")
    
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()

if __name__ == "__main__":
    log("="*50)
    log("Vibesbot starting...")
    log(f"Python: {sys.executable}")
    log(f"Working dir: {os.getcwd()}")
    
    # Matar servidor anterior
    os.system("pkill -f 'uvicorn.*8080' 2>/dev/null")
    time.sleep(0.5)
    
    # Servidor en thread separado
    server = threading.Thread(target=start_server, daemon=True)
    server.start()
    
    # Esperar un momento para que el servidor inicie
    time.sleep(1)
    
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
