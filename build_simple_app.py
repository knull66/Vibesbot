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
BUNDLE_ID = "com.vibesbot.trading"

PROJECT_DIR = Path(__file__).parent.resolve()

# Leer versión del archivo VERSION
VERSION_FILE = PROJECT_DIR / "VERSION"
if VERSION_FILE.exists():
    VERSION = VERSION_FILE.read_text().strip()
else:
    VERSION = "1.0.0"

print(f"📦 Building version: {VERSION}")
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


def create_python_launcher(version: str):
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
            
            self.window.setTitle_("VIBESBOT - Loading...")
            self.window.setContentView_(self.webView)
            self.window.center()
            self.window.makeKeyAndOrderFront_(None)
            
            # Loading screen - Bunny with cyan horizontal line eyes
            loading = """<!DOCTYPE html>
<html>
<head>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600&family=Press+Start+2P&display=swap" rel="stylesheet">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background:
        radial-gradient(ellipse 80% 50% at 50% -10%, rgba(92, 242, 255, 0.14) 0%, transparent 55%),
        #070809;
    color: #5CF2FF;
    font-family: Outfit, -apple-system, sans-serif;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    overflow: hidden;
}
.container { text-align: center; z-index: 10; }
.logo {
    width: 88px;
    height: 88px;
    margin: 0 auto 28px;
    position: relative;
}
.bunny {
    width: 100%;
    height: 100%;
    background: rgba(14, 16, 20, 0.72);
    border: 1px solid rgba(92, 242, 255, 0.32);
    border-radius: 24px;
    position: relative;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.12), 0 18px 40px rgba(0,0,0,0.35);
}
.ear {
    position: absolute;
    width: 20px;
    height: 40px;
    background: #070809;
    border: 1px solid rgba(92, 242, 255, 0.28);
    top: -34px;
    border-radius: 12px;
}
.ear.left { left: 16px; transform: rotate(-8deg); }
.ear.right { right: 16px; transform: rotate(8deg); }
.eye {
    position: absolute;
    width: 22px;
    height: 4px;
    background: #5CF2FF;
    top: 50%;
    transform: translateY(-50%);
    border-radius: 99px;
    box-shadow: 0 0 12px rgba(92, 242, 255, 0.7);
    animation: blink 3s infinite;
}
.eye.left { left: 16px; }
.eye.right { right: 16px; }
@keyframes blink {
    0%, 90%, 100% { opacity: 1; }
    95% { opacity: 0.25; }
}
.title {
    font-family: 'Press Start 2P', monospace;
    font-size: 18px;
    letter-spacing: 3px;
    margin-bottom: 10px;
}
.subtitle {
    color: rgba(244,247,250,0.5);
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-bottom: 28px;
}
.version {
    color: rgba(244,247,250,0.32);
    font-size: 12px;
    margin-bottom: 22px;
}
.loader {
    width: 180px;
    height: 4px;
    background: rgba(255,255,255,0.08);
    margin: 0 auto;
    overflow: hidden;
    border-radius: 99px;
}
.loader-bar {
    width: 32%;
    height: 100%;
    background: #5CF2FF;
    border-radius: 99px;
    animation: load 1.2s ease-in-out infinite;
}
@keyframes load {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(360%); }
}
.status {
    color: rgba(244,247,250,0.45);
    font-size: 12px;
    margin-top: 18px;
    letter-spacing: 0.08em;
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
    <div class="subtitle">Trading radar</div>
    <div class="version">v__VERSION__</div>
    <div class="loader"><div class="loader-bar"></div></div>
    <div class="status">Connecting</div>
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
                self.window.setTitle_("VIBESBOT")
                url = NSURL.URLWithString_("http://127.0.0.1:8080")
                self.webView.loadRequest_(NSURLRequest.requestWithURL_(url))
            except:
                if self.attempts > 60:
                    timer.invalidate()
                    self.window.setTitle_("VIBESBOT - Error")
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
    # Insertar la versión
    python_launcher = python_launcher.replace('__VERSION__', version)
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
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True, exist_ok=True)
    
    # Tamaños requeridos para macOS
    icon_sizes = [
        (16, "16x16"),
        (32, "16x16@2x"),
        (32, "32x32"),
        (64, "32x32@2x"),
        (128, "128x128"),
        (256, "128x128@2x"),
        (256, "256x256"),
        (512, "256x256@2x"),
        (512, "512x512"),
        (1024, "512x512@2x"),
    ]
    
    print("  → Generando tamaños de icono...")
    for size, name in icon_sizes:
        out_file = iconset_dir / f"icon_{name}.png"
        result = subprocess.run([
            "sips", "-z", str(size), str(size),
            str(icon_png), "--out", str(out_file)
        ], capture_output=True)
        if result.returncode != 0:
            print(f"    ⚠ Error creando {name}")
    
    # Convertir a icns
    icns_path = RESOURCES_DIR / "AppIcon.icns"
    result = subprocess.run([
        "iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)
    ], capture_output=True, text=True)
    
    # Limpiar
    shutil.rmtree(iconset_dir, ignore_errors=True)
    
    if icns_path.exists():
        print("  ✓ Icono .icns creado")
        return icns_path
    else:
        print(f"  ⚠ Error creando icns: {result.stderr}")
        # Copiar PNG como fallback
        fallback = RESOURCES_DIR / "AppIcon.png"
        shutil.copy(icon_png, fallback)
        print("  → Usando PNG como fallback")
        return fallback


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
    files_to_copy = ['config.example.json', 'VERSION']
    
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
        f.write(create_python_launcher(VERSION))
    os.chmod(launcher_py, 0o755)
    
    print("  ✓ Proyecto copiado")
    
    # Icono
    create_icns()
    
    print(f"  ✓ App creada: {APP_DIR}")
    return True


def create_dmg():
    """Crea el DMG de forma simple y confiable"""
    print("\n📦 Creando DMG...")
    
    dmg_path = DIST_DIR / f"{APP_NAME}-{VERSION}.dmg"
    
    # Eliminar DMG anterior si existe
    if dmg_path.exists():
        dmg_path.unlink()
    
    # Crear carpeta temporal para DMG
    dmg_staging = DIST_DIR / "dmg_staging"
    if dmg_staging.exists():
        shutil.rmtree(dmg_staging)
    dmg_staging.mkdir()
    
    print(f"  Preparando contenido...")
    
    # Copiar app
    shutil.copytree(APP_DIR, dmg_staging / f"{APP_NAME}.app")
    
    # Symlink a Applications
    (dmg_staging / "Applications").symlink_to("/Applications")
    
    print(f"  Creando imagen DMG...")
    
    # Crear DMG directamente (sin AppleScript problemático)
    result = subprocess.run([
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", str(dmg_staging),
        "-ov",
        "-format", "UDZO",
        str(dmg_path)
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"  ⚠️ Error creando DMG: {result.stderr}")
        # Intentar método alternativo
        print(f"  Intentando método alternativo...")
        result = subprocess.run([
            "hdiutil", "create",
            "-volname", APP_NAME,
            "-srcfolder", str(dmg_staging),
            "-ov",
            "-format", "UDBZ",
            str(dmg_path)
        ], capture_output=True, text=True)
    
    # Limpiar staging
    shutil.rmtree(dmg_staging)
    
    if dmg_path.exists():
        size_mb = dmg_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ DMG creado: {dmg_path} ({size_mb:.1f} MB)")
        return dmg_path
    else:
        print(f"  ❌ Error: No se pudo crear el DMG")
        return None
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
    
    if dmg_path:
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
    else:
        print(f"""
════════════════════════════════════════════════════════════

   ⚠️  BUILD PARCIAL
   
   📱 App: {APP_DIR}
   ❌ DMG: No se pudo crear (hdiutil no disponible en Linux)
   
   Para probar ahora:
     open "{APP_DIR}"

════════════════════════════════════════════════════════════
""")


if __name__ == "__main__":
    main()
