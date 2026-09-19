#!/usr/bin/env python3
"""
🚀 VIBESBOT - Build Simple App para macOS
==========================================
Crea una app nativa que usa el Python del sistema.
Más confiable que PyInstaller para apps con muchas dependencias.

Uso:
    python3 build_simple_app.py

Resultado:
    dist/Vibesbot.app - App lista para usar
    dist/Vibesbot.dmg - DMG para distribuir
"""
import os
import sys
import shutil
import subprocess
import plistlib
from pathlib import Path

APP_NAME = "Vibesbot"
VERSION = "1.0.0"
BUNDLE_ID = "com.vibesbot.trading"

PROJECT_DIR = Path(__file__).parent.resolve()
DIST_DIR = PROJECT_DIR / "dist"
APP_DIR = DIST_DIR / f"{APP_NAME}.app"
CONTENTS_DIR = APP_DIR / "Contents"
MACOS_DIR = CONTENTS_DIR / "MacOS"
RESOURCES_DIR = CONTENTS_DIR / "Resources"


def create_launcher_script():
    """Crea el script lanzador principal"""
    
    launcher = '''#!/bin/bash
# Vibesbot Launcher

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="$APP_DIR/Resources"
VIBESBOT_DIR="$RESOURCES/vibesbot"
LOG_FILE="$HOME/Library/Logs/Vibesbot.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

log "Starting Vibesbot..."
log "App dir: $APP_DIR"
log "Resources: $RESOURCES"

cd "$VIBESBOT_DIR"

# Verificar Python
if ! command -v python3 &> /dev/null; then
    osascript -e 'display alert "Python3 no encontrado" message "Instala Python desde python.org" as critical'
    exit 1
fi

log "Python: $(which python3)"

# Instalar dependencias si es necesario
check_deps() {
    python3 -c "import fastapi, uvicorn, pandas, lightgbm" 2>/dev/null
    return $?
}

if ! check_deps; then
    log "Installing dependencies..."
    
    # Mostrar ventana de progreso
    osascript <<'APPLESCRIPT' &
        display dialog "Instalando dependencias de Vibesbot...

Esto solo ocurre la primera vez." buttons {"OK"} default button 1 giving up after 120 with title "Vibesbot Setup"
APPLESCRIPT
    
    python3 -m pip install --user -q fastapi uvicorn jinja2 aiohttp pandas numpy ta lightgbm scikit-learn websockets python-dotenv pyobjc-framework-WebKit pyobjc-framework-Cocoa 2>> "$LOG_FILE"
    
    log "Dependencies installed"
fi

# Matar servidor anterior
pkill -f "uvicorn.*8080" 2>/dev/null
sleep 0.5

# Ejecutar la app
log "Launching app..."
exec python3 "$VIBESBOT_DIR/app_launcher.py" 2>> "$LOG_FILE"
'''
    
    return launcher


def create_python_launcher():
    """Crea el script Python que lanza la ventana"""
    
    python_launcher = '''#!/usr/bin/env python3
"""Vibesbot - Native macOS Window Launcher"""
import os
import sys
import threading
import time
import urllib.request

# Setup paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

def start_server():
    """Start the FastAPI server"""
    try:
        from src.web_server import run_dashboard
        run_dashboard(port=8080)
    except Exception as e:
        print(f"Server error: {e}")
        import traceback
        traceback.print_exc()

def main():
    import objc
    from Foundation import NSObject, NSURL, NSURLRequest, NSMakeRect, NSTimer, NSBundle
    from AppKit import (
        NSApplication, NSWindow, NSApp,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
        NSBackingStoreBuffered, NSApplicationActivationPolicyRegular,
        NSImage
    )
    from WebKit import WKWebView, WKWebViewConfiguration
    
    class AppDelegate(NSObject):
        window = objc.ivar()
        webView = objc.ivar()
        timer = objc.ivar()
        attempts = objc.ivar()
        
        def applicationDidFinishLaunching_(self, notification):
            self.attempts = 0
            self.createWindow()
            
            # Start checking for server
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.5, self, "checkServer:", None, True
            )
        
        def createWindow(self):
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
            
            # Loading screen with bunny logo
            loading = """<!DOCTYPE html>
<html>
<head>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 100%);
    color: #00ff88;
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', sans-serif;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    overflow: hidden;
}
.container { text-align: center; }
.logo {
    width: 120px;
    height: 120px;
    margin: 0 auto 30px;
    position: relative;
}
.bunny {
    width: 100%;
    height: 100%;
    background: #000;
    border-radius: 20px;
    position: relative;
    box-shadow: 0 0 40px rgba(0, 255, 136, 0.3);
}
.ear {
    position: absolute;
    width: 25px;
    height: 50px;
    background: #000;
    top: -40px;
    border-radius: 10px;
}
.ear.left { left: 20px; transform: rotate(-10deg); }
.ear.right { right: 20px; transform: rotate(10deg); }
.eye {
    position: absolute;
    width: 30px;
    height: 6px;
    background: #00ff88;
    top: 50%;
    border-radius: 3px;
    box-shadow: 0 0 20px #00ff88, 0 0 40px #00ff88;
    animation: blink 3s infinite;
}
.eye.left { left: 20px; }
.eye.right { right: 20px; }
@keyframes blink {
    0%, 90%, 100% { opacity: 1; }
    95% { opacity: 0.3; }
}
.title {
    font-size: 42px;
    font-weight: 700;
    margin-bottom: 10px;
    text-shadow: 0 0 30px rgba(0, 255, 136, 0.5);
}
.subtitle {
    color: #666;
    font-size: 14px;
    margin-bottom: 30px;
}
.loader {
    width: 200px;
    height: 4px;
    background: #1a1a2e;
    border-radius: 2px;
    margin: 0 auto;
    overflow: hidden;
}
.loader-bar {
    width: 40%;
    height: 100%;
    background: linear-gradient(90deg, #00ff88, #00d4ff);
    border-radius: 2px;
    animation: load 1.5s ease-in-out infinite;
}
@keyframes load {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(350%); }
}
.status {
    color: #444;
    font-size: 12px;
    margin-top: 20px;
}
</style>
</head>
<body>
<div class="container">
    <div class="logo">
        <div class="bunny">
            <div class="ear left"></div>
            <div class="ear right"></div>
            <div class="eye left"></div>
            <div class="eye right"></div>
        </div>
    </div>
    <div class="title">VIBESBOT</div>
    <div class="subtitle">Trading Radar</div>
    <div class="loader"><div class="loader-bar"></div></div>
    <div class="status">Conectando al servidor...</div>
</div>
</body>
</html>"""
            self.webView.loadHTMLString_baseURL_(loading, None)
            NSApp.activateIgnoringOtherApps_(True)
        
        def checkServer_(self, timer):
            self.attempts += 1
            try:
                urllib.request.urlopen("http://127.0.0.1:8080", timeout=1)
                timer.invalidate()
                self.window.setTitle_("⚡ Vibesbot Trading Radar")
                url = NSURL.URLWithString_("http://127.0.0.1:8080")
                self.webView.loadRequest_(NSURLRequest.requestWithURL_(url))
            except:
                if self.attempts > 60:
                    timer.invalidate()
                    self.window.setTitle_("⚡ Vibesbot - Error")
                    error_html = """<!DOCTYPE html>
<html><body style="background:#0a0a0f;color:#ff4444;font-family:-apple-system;display:flex;justify-content:center;align-items:center;height:100vh;text-align:center">
<div>
<h1 style="font-size:48px;margin-bottom:20px">:(</h1>
<p style="font-size:18px">Error conectando al servidor</p>
<p style="color:#666;margin-top:20px">Revisa ~/Library/Logs/Vibesbot.log</p>
</div>
</body></html>"""
                    self.webView.loadHTMLString_baseURL_(error_html, None)
        
        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
            return True
        
        def applicationWillTerminate_(self, notification):
            os.system("pkill -f 'uvicorn.*8080' 2>/dev/null")
    
    # Start server in background
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Create and run app
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()

if __name__ == "__main__":
    os.system("pkill -f 'uvicorn.*8080' 2>/dev/null")
    time.sleep(0.3)
    main()
'''
    return python_launcher


def create_info_plist():
    """Crea el Info.plist"""
    return {
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': 'Vibesbot Trading',
        'CFBundleIdentifier': BUNDLE_ID,
        'CFBundleVersion': VERSION,
        'CFBundleShortVersionString': VERSION,
        'CFBundleExecutable': 'launcher',
        'CFBundlePackageType': 'APPL',
        'CFBundleIconFile': 'AppIcon',
        'LSMinimumSystemVersion': '10.15',
        'NSHighResolutionCapable': True,
        'NSSupportsAutomaticGraphicsSwitching': True,
    }


def create_icns():
    """Crea el archivo .icns desde el PNG"""
    icon_png = PROJECT_DIR / "assets" / "icon.png"
    if not icon_png.exists():
        print("  ⚠ No se encontró icon.png, usando icono por defecto")
        return None
    
    iconset_dir = DIST_DIR / "AppIcon.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)
    
    # Crear diferentes tamaños
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    
    for size in sizes:
        # Normal
        out_file = iconset_dir / f"icon_{size}x{size}.png"
        subprocess.run([
            "sips", "-z", str(size), str(size),
            str(icon_png), "--out", str(out_file)
        ], capture_output=True)
        
        # @2x (retina)
        if size <= 512:
            out_file_2x = iconset_dir / f"icon_{size}x{size}@2x.png"
            subprocess.run([
                "sips", "-z", str(size*2), str(size*2),
                str(icon_png), "--out", str(out_file_2x)
            ], capture_output=True)
    
    # Convertir a icns
    icns_path = RESOURCES_DIR / "AppIcon.icns"
    subprocess.run([
        "iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)
    ], capture_output=True)
    
    # Limpiar
    shutil.rmtree(iconset_dir)
    
    if icns_path.exists():
        print("  ✓ Icono creado")
        return icns_path
    return None


def build_app():
    """Construye la app"""
    print("\n🔨 Construyendo Vibesbot.app...")
    
    # Limpiar
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    
    # Crear estructura
    MACOS_DIR.mkdir(parents=True)
    RESOURCES_DIR.mkdir(parents=True)
    
    # Info.plist
    plist_path = CONTENTS_DIR / "Info.plist"
    with open(plist_path, 'wb') as f:
        plistlib.dump(create_info_plist(), f)
    print("  ✓ Info.plist")
    
    # Launcher script
    launcher_path = MACOS_DIR / "launcher"
    with open(launcher_path, 'w') as f:
        f.write(create_launcher_script())
    os.chmod(launcher_path, 0o755)
    print("  ✓ Launcher")
    
    # Copiar proyecto
    vibesbot_dir = RESOURCES_DIR / "vibesbot"
    
    # Copiar archivos necesarios
    dirs_to_copy = ['src', 'web', 'models', 'assets']
    files_to_copy = ['config.example.json']
    
    vibesbot_dir.mkdir()
    
    for d in dirs_to_copy:
        src = PROJECT_DIR / d
        if src.exists():
            shutil.copytree(src, vibesbot_dir / d)
    
    for f in files_to_copy:
        src = PROJECT_DIR / f
        if src.exists():
            shutil.copy2(src, vibesbot_dir / f)
    
    # Python launcher
    launcher_py = vibesbot_dir / "app_launcher.py"
    with open(launcher_py, 'w') as f:
        f.write(create_python_launcher())
    os.chmod(launcher_py, 0o755)
    
    print("  ✓ Proyecto copiado")
    
    # Icono
    create_icns()
    
    print(f"  ✓ App creada: {APP_DIR}")
    return True


def create_dmg():
    """Crea el DMG"""
    print("\n📦 Creando DMG...")
    
    dmg_path = DIST_DIR / f"{APP_NAME}-{VERSION}.dmg"
    
    if dmg_path.exists():
        dmg_path.unlink()
    
    # Crear carpeta temporal para DMG
    dmg_staging = DIST_DIR / "dmg_staging"
    if dmg_staging.exists():
        shutil.rmtree(dmg_staging)
    dmg_staging.mkdir()
    
    # Copiar app
    shutil.copytree(APP_DIR, dmg_staging / f"{APP_NAME}.app")
    
    # Symlink a Applications
    (dmg_staging / "Applications").symlink_to("/Applications")
    
    # README
    readme = dmg_staging / "INSTRUCCIONES.txt"
    readme.write_text(f"""
═══════════════════════════════════════════════════════════
   ⚡ VIBESBOT v{VERSION}
   Bot de Trading para Binance Prediction
═══════════════════════════════════════════════════════════

INSTALACIÓN:
  1. Arrastra "Vibesbot" a "Applications"
  2. Abre desde Applications o Launchpad
  
PRIMERA VEZ:
  La app instalará dependencias automáticamente.
  Esto toma ~1 minuto solo la primera vez.

SI MACOS BLOQUEA LA APP:
  Sistema → Privacidad y Seguridad → "Abrir de todos modos"

═══════════════════════════════════════════════════════════
""")
    
    # Crear DMG
    subprocess.run([
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", str(dmg_staging),
        "-ov",
        "-format", "UDZO",
        str(dmg_path)
    ], capture_output=True)
    
    # Limpiar
    shutil.rmtree(dmg_staging)
    
    if dmg_path.exists():
        size_mb = dmg_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ DMG creado: {dmg_path} ({size_mb:.1f} MB)")
        return dmg_path
    
    return None


def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ⚡ VIBESBOT - Build Simple App                          ║
║   Creando app nativa para macOS                           ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
""")
    
    if not build_app():
        print("\n❌ Error construyendo app")
        sys.exit(1)
    
    dmg_path = create_dmg()
    
    print(f"""
════════════════════════════════════════════════════════════

   ✅ ¡BUILD COMPLETADO!
   
   📱 App: {APP_DIR}
   📦 DMG: {dmg_path}
   
   Para probar ahora:
     open "{APP_DIR}"
   
   Para distribuir:
     Sube {dmg_path.name} a tu sitio web

════════════════════════════════════════════════════════════
""")


if __name__ == "__main__":
    main()
