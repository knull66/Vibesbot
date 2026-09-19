#!/usr/bin/env python3
"""
🚀 VIBESBOT - Build Installer para macOS
========================================
Genera Vibesbot.dmg con la app lista para distribuir.

Uso:
    python3 build_installer.py

El usuario final solo:
1. Descarga Vibesbot.dmg
2. Doble clic para abrir
3. Arrastra Vibesbot a Applications
4. Listo - doble clic para usar
"""
import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

# Configuración
APP_NAME = "Vibesbot"
VERSION = "1.0.0"
IDENTIFIER = "com.vibesbot.trading"

# Directorios
PROJECT_DIR = Path(__file__).parent
BUILD_DIR = PROJECT_DIR / "dist"
APP_PATH = BUILD_DIR / f"{APP_NAME}.app"
DMG_PATH = BUILD_DIR / f"{APP_NAME}-{VERSION}.dmg"


def run(cmd, **kwargs):
    """Ejecuta comando y muestra output"""
    print(f"  → {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    result = subprocess.run(cmd, shell=isinstance(cmd, str), **kwargs)
    if result.returncode != 0:
        print(f"  ✗ Error: código {result.returncode}")
        sys.exit(1)
    return result


def check_dependencies():
    """Verifica que las dependencias estén instaladas"""
    print("\n📋 Verificando dependencias...")
    
    # Verificar PyInstaller
    try:
        import PyInstaller
        print("  ✓ PyInstaller instalado")
    except ImportError:
        print("  ⚠ Instalando PyInstaller...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Instalar dependencias del proyecto
    print("  → Instalando dependencias del proyecto...")
    run([sys.executable, "-m", "pip", "install", "-r", str(PROJECT_DIR / "requirements.txt"), "-q"])
    
    # Dependencias adicionales para empaquetado
    print("  → Instalando dependencias de empaquetado...")
    run([sys.executable, "-m", "pip", "install", "appdirs", "packaging", "-q"])
    
    # Instalar pyobjc para la ventana nativa
    print("  → Instalando PyObjC para ventana nativa...")
    run([sys.executable, "-m", "pip", "install", "pyobjc-framework-WebKit", "pyobjc-framework-Cocoa", "-q"])


def create_entry_script():
    """Crea el script de entrada para PyInstaller"""
    entry_script = PROJECT_DIR / "vibesbot_main.py"
    
    entry_code = '''#!/usr/bin/env python3
"""Vibesbot - Entry point for packaged app"""
import os
import sys
import threading
import time
import urllib.request

# Configurar paths para la app empaquetada
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
    # En .app bundle, los recursos están en Resources
    if APP_DIR.endswith("MacOS"):
        RESOURCES_DIR = os.path.join(os.path.dirname(APP_DIR), "Resources")
        if os.path.exists(RESOURCES_DIR):
            os.chdir(RESOURCES_DIR)
            sys.path.insert(0, RESOURCES_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    os.chdir(APP_DIR)
    sys.path.insert(0, APP_DIR)

def start_server():
    """Inicia el servidor FastAPI"""
    try:
        from src.web_server import run_dashboard
        run_dashboard(port=8080)
    except Exception as e:
        print(f"Server error: {e}")
        import traceback
        traceback.print_exc()

def create_window():
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
        attempts = objc.ivar()
        
        def applicationDidFinishLaunching_(self, notification):
            self.attempts = 0
            
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
            
            # Pantalla de carga
            loading = """
            <html><head><style>
                body { background: #0a0a0f; color: #00ff88; font-family: -apple-system; 
                       display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
                .c { text-align: center; }
                .t { font-size: 48px; margin-bottom: 20px; }
                .s { width: 50px; height: 50px; border: 3px solid #1a1a2e; border-top: 3px solid #00ff88;
                     border-radius: 50%; animation: spin 1s linear infinite; margin: 20px auto; }
                @keyframes spin { to { transform: rotate(360deg); } }
            </style></head>
            <body><div class="c"><div class="t">⚡ VIBESBOT</div><div class="s"></div></div></body></html>
            """
            self.webView.loadHTMLString_baseURL_(loading, None)
            
            NSApp.activateIgnoringOtherApps_(True)
            
            self.loadTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0, self, "checkServer:", None, True
            )
        
        def checkServer_(self, timer):
            self.attempts += 1
            try:
                urllib.request.urlopen("http://127.0.0.1:8080", timeout=1)
                timer.invalidate()
                self.window.setTitle_("VIBESBOT")
                url = NSURL.URLWithString_("http://127.0.0.1:8080")
                self.webView.loadRequest_(NSURLRequest.requestWithURL_(url))
            except:
                if self.attempts > 30:
                    timer.invalidate()
                    self.webView.loadHTMLString_baseURL_(
                        "<html><body style=\\"background:#0a0a0f;color:#f44;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh\\"><h1>Error iniciando servidor</h1></body></html>",
                        None
                    )
        
        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
            return True
        
        def applicationWillTerminate_(self, notification):
            os.system("pkill -f 'uvicorn.*8080' 2>/dev/null")
    
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()

if __name__ == "__main__":
    # Matar servidor anterior
    os.system("pkill -f 'uvicorn.*8080' 2>/dev/null")
    time.sleep(0.3)
    
    # Servidor en thread
    server = threading.Thread(target=start_server, daemon=True)
    server.start()
    
    time.sleep(0.5)
    
    # Ventana nativa
    create_window()
'''
    
    with open(entry_script, "w") as f:
        f.write(entry_code)
    
    print(f"  ✓ Script de entrada creado")
    return entry_script


def create_spec_file():
    """Crea el archivo .spec para PyInstaller"""
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None
project_dir = Path("{PROJECT_DIR}").resolve()

# Archivos de datos a incluir
datas = [
    (str(project_dir / "web"), "web"),
    (str(project_dir / "src"), "src"),
    (str(project_dir / "config.example.json"), "."),
]

# Incluir modelos si existen
models_dir = project_dir / "models"
if models_dir.exists():
    datas.append((str(models_dir), "models"))

a = Analysis(
    [str(project_dir / "vibesbot_main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "appdirs",
        "packaging",
        "packaging.version",
        "packaging.specifiers",
        "packaging.requirements",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "starlette",
        "starlette.routing",
        "starlette.middleware",
        "jinja2",
        "websockets",
        "lightgbm",
        "sklearn",
        "sklearn.utils._cython_blas",
        "sklearn.neighbors._typedefs",
        "sklearn.neighbors._quad_tree",
        "sklearn.tree._utils",
        "pandas",
        "numpy",
        "ta",
        "aiohttp",
        "pkg_resources.py2_warn",
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="{APP_NAME}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="{APP_NAME}",
)

app = BUNDLE(
    coll,
    name="{APP_NAME}.app",
    icon=None,
    bundle_identifier="{IDENTIFIER}",
    info_plist={{
        "CFBundleName": "{APP_NAME}",
        "CFBundleDisplayName": "Vibesbot Trading",
        "CFBundleVersion": "{VERSION}",
        "CFBundleShortVersionString": "{VERSION}",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "10.15",
    }},
)
'''
    
    spec_path = PROJECT_DIR / f"{APP_NAME}.spec"
    with open(spec_path, "w") as f:
        f.write(spec_content)
    
    print(f"  ✓ Spec file creado")
    return spec_path


def build_app():
    """Construye la app con PyInstaller"""
    print("\n🔨 Construyendo app...")
    
    spec_file = create_spec_file()
    
    run([
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file)
    ])
    
    if APP_PATH.exists():
        print(f"  ✓ App creada: {APP_PATH}")
        return True
    else:
        print("  ✗ Error: App no fue creada")
        return False


def create_dmg():
    """Crea el archivo DMG"""
    print("\n📦 Creando DMG...")
    
    if DMG_PATH.exists():
        DMG_PATH.unlink()
    
    # Crear DMG con hdiutil
    with tempfile.TemporaryDirectory() as tmpdir:
        dmg_contents = Path(tmpdir) / "dmg"
        dmg_contents.mkdir()
        
        # Copiar app
        shutil.copytree(APP_PATH, dmg_contents / f"{APP_NAME}.app")
        
        # Crear symlink a Applications
        (dmg_contents / "Applications").symlink_to("/Applications")
        
        # Crear README
        readme = dmg_contents / "LÉEME.txt"
        readme.write_text(f"""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ⚡ VIBESBOT v{VERSION}                                     ║
║   Bot de Trading para Binance Prediction                  ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝

INSTALACIÓN:
1. Arrastra "Vibesbot" a la carpeta "Applications"
2. Abre Vibesbot desde Applications o Launchpad
3. Si macOS bloquea la app: 
   Sistema → Privacidad y Seguridad → "Abrir de todos modos"

¡Listo! Disfruta el trading.
""")
        
        # Crear DMG
        run([
            "hdiutil", "create",
            "-volname", APP_NAME,
            "-srcfolder", str(dmg_contents),
            "-ov",
            "-format", "UDZO",
            str(DMG_PATH)
        ])
    
    if DMG_PATH.exists():
        size_mb = DMG_PATH.stat().st_size / (1024 * 1024)
        print(f"  ✓ DMG creado: {DMG_PATH} ({size_mb:.1f} MB)")
        return True
    
    return False


def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ⚡ VIBESBOT - Build Installer                           ║
║   Creando app distribuible para macOS                     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
""")
    
    # Limpiar builds anteriores
    if BUILD_DIR.exists():
        print("🧹 Limpiando builds anteriores...")
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    
    check_dependencies()
    create_entry_script()
    
    if not build_app():
        print("\n❌ Error construyendo la app")
        sys.exit(1)
    
    if not create_dmg():
        print("\n❌ Error creando DMG")
        sys.exit(1)
    
    print(f"""
════════════════════════════════════════════════════════════

   ✅ ¡BUILD COMPLETADO!
   
   📦 DMG listo: {DMG_PATH}
   
   Para distribuir:
   1. Sube {DMG_PATH.name} a tu sitio web
   2. Los usuarios descargan, abren el DMG
   3. Arrastran Vibesbot a Applications
   4. ¡Listo!

════════════════════════════════════════════════════════════
""")


if __name__ == "__main__":
    main()
