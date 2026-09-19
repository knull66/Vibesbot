#!/usr/bin/env python3
"""
Crea una aplicación nativa de macOS para Vibesbot
usando WebKit nativo (sin abrir navegador externo)
"""
import os
import stat
import subprocess
import sys

APP_NAME = "Vibesbot"
APP_PATH = os.path.expanduser(f"~/Applications/{APP_NAME}.app")

# Estructura del .app bundle
CONTENTS = f"{APP_PATH}/Contents"
MACOS = f"{CONTENTS}/MacOS"
RESOURCES = f"{CONTENTS}/Resources"

# Info.plist para la app
INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIdentifier</key>
    <string>com.vibesbot.app</string>
    <key>CFBundleName</key>
    <string>Vibesbot</string>
    <key>CFBundleDisplayName</key>
    <string>Vibesbot Trading</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
</dict>
</plist>
"""

# Script Swift para la ventana nativa WebKit
SWIFT_APP = """
import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var serverProcess: Process?
    
    func applicationDidFinishLaunching(_ notification: Notification) {
        startServer()
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
            self.createWindow()
        }
    }
    
    func startServer() {
        let projectPath = Bundle.main.resourcePath!.replacingOccurrences(of: "/Contents/Resources", with: "").replacingOccurrences(of: ".app", with: "")
        
        serverProcess = Process()
        serverProcess?.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        serverProcess?.arguments = ["python3", "-c", \"\"\"
import sys
sys.path.insert(0, '\\(projectPath)')
from src.web_server import run_dashboard
run_dashboard(port=8080)
\"\"\"]
        serverProcess?.currentDirectoryURL = URL(fileURLWithPath: projectPath)
        
        try? serverProcess?.run()
    }
    
    func createWindow() {
        let config = WKWebViewConfiguration()
        webView = WKWebView(frame: .zero, configuration: config)
        
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1400, height: 900),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        
        window.title = "⚡ Vibesbot Trading Radar"
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
        
        if let url = URL(string: "http://localhost:8080") {
            webView.load(URLRequest(url: url))
        }
        
        NSApp.activate(ignoringOtherApps: true)
    }
    
    func applicationWillTerminate(_ notification: Notification) {
        serverProcess?.terminate()
    }
    
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
"""

# Script launcher alternativo (sin Swift, usa Python + pyobjc)
PYTHON_LAUNCHER = '''#!/usr/bin/env python3
"""Vibesbot - Native macOS App Launcher"""
import os
import sys
import subprocess
import threading
import time

# Obtener la ruta del proyecto
app_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
project_path = app_path.replace(".app", "")

# Agregar el proyecto al path
sys.path.insert(0, project_path)

def start_server():
    """Inicia el servidor web en background"""
    os.chdir(project_path)
    subprocess.run([
        sys.executable, "-c",
        "from src.web_server import run_dashboard; run_dashboard(port=8080)"
    ], cwd=project_path)

def create_window():
    """Crea ventana nativa con WebKit"""
    try:
        import objc
        from Foundation import NSObject, NSURL, NSURLRequest
        from AppKit import (
            NSApplication, NSWindow, NSApp,
            NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
            NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
            NSBackingStoreBuffered, NSApplicationActivationPolicyRegular
        )
        from WebKit import WKWebView, WKWebViewConfiguration
        
        class AppDelegate(NSObject):
            window = None
            webView = None
            
            def applicationDidFinishLaunching_(self, notification):
                time.sleep(2)  # Esperar que el servidor inicie
                
                config = WKWebViewConfiguration.alloc().init()
                self.webView = WKWebView.alloc().initWithFrame_configuration_(
                    ((0, 0), (1400, 900)), config
                )
                
                style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                        NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
                
                self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    ((200, 200), (1400, 900)), style, NSBackingStoreBuffered, False
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
        
    except ImportError as e:
        print(f"Error: {e}")
        print("Instalando dependencias...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.run([sys.executable, "-m", "pip", "install", "pyobjc-framework-WebKit"])
        print("Reinicia la aplicación")
        sys.exit(1)

if __name__ == "__main__":
    # Iniciar servidor en thread separado
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Crear ventana nativa
    create_window()
'''

# Launcher shell simple como fallback
SHELL_LAUNCHER = '''#!/bin/bash
cd "$(dirname "$0")/../.."
PROJECT_DIR="${PWD%.app}"

# Matar procesos anteriores
pkill -f "uvicorn.*web_server" 2>/dev/null

# Verificar dependencias
python3 -c "import objc" 2>/dev/null || {
    python3 -m pip install --upgrade pip
    python3 -m pip install pyobjc-framework-WebKit pyobjc-framework-Cocoa
}

# Ejecutar la app
cd "$PROJECT_DIR"
python3 "$PROJECT_DIR/Vibesbot.app/Contents/MacOS/vibesbot_native.py"
'''


def create_app():
    """Crea la estructura de la aplicación macOS"""
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║   ⚡ Creando Vibesbot.app nativa para macOS               ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()
    
    # Crear directorios
    os.makedirs(MACOS, exist_ok=True)
    os.makedirs(RESOURCES, exist_ok=True)
    
    # Info.plist
    with open(f"{CONTENTS}/Info.plist", "w") as f:
        f.write(INFO_PLIST)
    print("✓ Info.plist creado")
    
    # Script Python nativo
    python_script = f"{MACOS}/vibesbot_native.py"
    with open(python_script, "w") as f:
        f.write(PYTHON_LAUNCHER)
    os.chmod(python_script, os.stat(python_script).st_mode | stat.S_IEXEC)
    print("✓ Script nativo creado")
    
    # Launcher shell
    launcher = f"{MACOS}/launcher"
    with open(launcher, "w") as f:
        f.write(SHELL_LAUNCHER)
    os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IEXEC)
    print("✓ Launcher creado")
    
    print()
    print(f"✅ App creada en: {APP_PATH}")
    print()
    print("Para completar la instalación:")
    print("1. Actualiza pip: python3 -m pip install --upgrade pip")
    print("2. Instala WebKit: python3 -m pip install pyobjc-framework-WebKit")
    print("3. Abre la app desde ~/Applications/Vibesbot.app")
    print()
    
    return APP_PATH


if __name__ == "__main__":
    create_app()
