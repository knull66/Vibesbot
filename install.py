#!/usr/bin/env python3
"""
Instalador de Vibesbot.

Crea accesos directos y configura la aplicación para uso fácil.
"""
import os
import sys
import subprocess
import platform
from pathlib import Path


VIBESBOT_DIR = Path(__file__).parent.absolute()
ICON_PATH = VIBESBOT_DIR / "assets" / "icon.png"


def create_icon():
    """Crea un icono simple para la aplicación."""
    assets_dir = VIBESBOT_DIR / "assets"
    assets_dir.mkdir(exist_ok=True)
    
    icon_svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#0a0a0f"/>
  <circle cx="32" cy="32" r="20" fill="none" stroke="#00ff88" stroke-width="2" opacity="0.3"/>
  <circle cx="32" cy="32" r="12" fill="none" stroke="#00ff88" stroke-width="2" opacity="0.5"/>
  <circle cx="32" cy="32" r="4" fill="#00ff88"/>
  <text x="32" y="58" text-anchor="middle" fill="#00ff88" font-family="monospace" font-size="8" font-weight="bold">VIBES</text>
</svg>'''
    
    svg_path = assets_dir / "icon.svg"
    with open(svg_path, "w") as f:
        f.write(icon_svg)
    
    try:
        subprocess.run([
            "convert", str(svg_path), "-resize", "256x256", str(assets_dir / "icon.png")
        ], capture_output=True)
    except:
        pass
    
    return svg_path


def install_dependencies():
    """Instala las dependencias necesarias."""
    print("📦 Instalando dependencias...")
    
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-q",
        "-r", str(VIBESBOT_DIR / "requirements.txt")
    ])
    
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-q", "pywebview"
    ])
    
    print("✅ Dependencias instaladas")


def create_linux_desktop_entry():
    """Crea un archivo .desktop para Linux."""
    desktop_dir = Path.home() / ".local" / "share" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    
    desktop_content = f'''[Desktop Entry]
Version=1.0
Type=Application
Name=Vibesbot
Comment=Binance Prediction Trading Radar
Exec={sys.executable} {VIBESBOT_DIR}/vibesbot.py
Icon={VIBESBOT_DIR}/assets/icon.svg
Terminal=false
Categories=Finance;Office;
StartupWMClass=vibesbot
'''
    
    desktop_file = desktop_dir / "vibesbot.desktop"
    with open(desktop_file, "w") as f:
        f.write(desktop_content)
    
    os.chmod(desktop_file, 0o755)
    
    local_desktop = Path.home() / "Desktop" / "Vibesbot.desktop"
    try:
        with open(local_desktop, "w") as f:
            f.write(desktop_content)
        os.chmod(local_desktop, 0o755)
    except:
        pass
    
    print(f"✅ Acceso directo creado: {desktop_file}")
    return desktop_file


def create_macos_app():
    """Crea un bundle .app para macOS."""
    app_dir = Path.home() / "Applications" / "Vibesbot.app"
    contents_dir = app_dir / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"
    
    for d in [macos_dir, resources_dir]:
        d.mkdir(parents=True, exist_ok=True)
    
    info_plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Vibesbot</string>
    <key>CFBundleDisplayName</key>
    <string>Vibesbot</string>
    <key>CFBundleIdentifier</key>
    <string>com.vibesbot.app</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>vibesbot</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>'''
    
    with open(contents_dir / "Info.plist", "w") as f:
        f.write(info_plist)
    
    try:
        import shutil
        icon_src = VIBESBOT_DIR / "assets" / "icon.svg"
        if icon_src.exists():
            shutil.copy(icon_src, resources_dir / "icon.svg")
    except:
        pass
    
    launcher = f'''#!/bin/bash
cd "{VIBESBOT_DIR}"
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

if command -v python3 &> /dev/null; then
    PYTHON=python3
elif [ -f "/usr/local/bin/python3" ]; then
    PYTHON=/usr/local/bin/python3
elif [ -f "/opt/homebrew/bin/python3" ]; then
    PYTHON=/opt/homebrew/bin/python3
else
    osascript -e 'display dialog "Python3 no encontrado. Instala Python desde python.org" buttons {{"OK"}} default button "OK"'
    exit 1
fi

$PYTHON "{VIBESBOT_DIR}/vibesbot.py" 2>&1 | tee "{VIBESBOT_DIR}/logs/app.log"
'''
    
    launcher_path = macos_dir / "vibesbot"
    with open(launcher_path, "w") as f:
        f.write(launcher)
    os.chmod(launcher_path, 0o755)
    
    (VIBESBOT_DIR / "logs").mkdir(exist_ok=True)
    
    print(f"✅ App creada: {app_dir}")
    print(f"   Puedes arrastrarla al Dock o abrirla desde Finder")
    return app_dir


def create_windows_shortcut():
    """Crea un acceso directo para Windows."""
    try:
        import winshell
        from win32com.client import Dispatch
        
        desktop = winshell.desktop()
        shortcut_path = os.path.join(desktop, "Vibesbot.lnk")
        
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = sys.executable
        shortcut.Arguments = str(VIBESBOT_DIR / "vibesbot.py")
        shortcut.WorkingDirectory = str(VIBESBOT_DIR)
        shortcut.Description = "Vibesbot Trading Radar"
        shortcut.save()
        
        print(f"✅ Acceso directo creado: {shortcut_path}")
        return shortcut_path
    except:
        print("⚠️ No se pudo crear acceso directo en Windows")
        return None


def create_launcher_script():
    """Crea el script principal de lanzamiento."""
    launcher = f'''#!/usr/bin/env python3
"""
VIBESBOT - Click para iniciar
"""
import sys
import os

os.chdir("{VIBESBOT_DIR}")
sys.path.insert(0, "{VIBESBOT_DIR}")

from src.desktop_app import main
main()
'''
    
    launcher_path = VIBESBOT_DIR / "vibesbot.py"
    with open(launcher_path, "w") as f:
        f.write(launcher)
    os.chmod(launcher_path, 0o755)
    
    return launcher_path


def main():
    """Ejecuta la instalación."""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   ⚡ VIBESBOT INSTALLER                                   ║
    ║   Configurando aplicación de escritorio...                ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    install_dependencies()
    
    print("\n🎨 Creando recursos...")
    create_icon()
    
    print("\n🚀 Creando lanzador...")
    create_launcher_script()
    
    system = platform.system()
    
    print(f"\n💻 Detectado: {system}")
    
    if system == "Linux":
        create_linux_desktop_entry()
    elif system == "Darwin":
        create_macos_app()
    elif system == "Windows":
        create_windows_shortcut()
    
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║   ✅ INSTALACIÓN COMPLETADA                               ║
    ╠═══════════════════════════════════════════════════════════╣
    ║                                                           ║
    ║   Para iniciar Vibesbot:                                  ║
    ║                                                           ║
    ║   • Busca "Vibesbot" en tu menú de aplicaciones           ║
    ║   • O ejecuta: python3 vibesbot.py                        ║
    ║                                                           ║
    ║   Primera vez? Ejecuta el backtest para entrenar:         ║
    ║   python3 run_backtest.py --days 30                       ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()
