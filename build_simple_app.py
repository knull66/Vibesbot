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
        display dialog "Instalando dependencias de Vibesbot...\n\nEsto solo ocurre la primera vez." buttons {"OK"} default button 1 giving up after 120 with title "Vibesbot Setup"
APPLESCRIPT
    
    python3 -m pip install --user -q fastapi uvicorn jinja2 aiohttp pandas numpy ta lightgbm scikit-learn websockets python-dotenv pyobjc-framework-WebKit pyobjc-framework-Cocoa 2>> "$LOG_FILE"
    
    log "Dependencies installed"
fi

# Matar lo que siga escuchando en 8080 (el motor viejo es python, no uvicorn)
if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
    fi
fi
pkill -f "app_launcher.py" 2>/dev/null || true
sleep 0.4

# Ejecutar la app
log "Inflating ship parts if needed..."
PYTHONPATH="." python3 -c "from src.ship_inflate import inflate_ship; print(inflate_ship())" >> "$LOG_FILE" 2>&1 || true
log "Launching app..."
exec python3 "$VIBESBOT_DIR/app_launcher.py" 2>> "$LOG_FILE"
'''
    
    return launcher


def create_python_launcher(version: str):
    """Copia el launcher nativo; la splash se lee de web/static/loading.html."""
    src = PROJECT_DIR / "app_launcher.py"
    if src.exists():
        return src.read_text(encoding="utf-8")
    return f'''#!/usr/bin/env python3
print("missing app_launcher.py v{version}")
'''


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
    
    if not shutil.which("sips") or not shutil.which("iconutil"):
        print("  ⚠ sips/iconutil no disponibles (build en Linux); usando PNG")
        fallback = RESOURCES_DIR / "AppIcon.png"
        shutil.copy(icon_png, fallback)
        shutil.rmtree(iconset_dir, ignore_errors=True)
        return fallback

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
    dirs_to_copy = ['src', 'web', 'models', 'assets', '.ship']
    files_to_copy = ['config.example.json', 'VERSION', 'app_launcher.py', 'requirements.txt',
                     'fix_blank_mac.command', 'restart_mac.command']
    
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
    """Crea el DMG con icono, fondo y enlace a Applications (como antes)."""
    print("\n📦 Creando DMG con diseño personalizado...")

    dmg_path = DIST_DIR / f"{APP_NAME}-{VERSION}.dmg"
    temp_dmg = DIST_DIR / "temp.dmg"

    if dmg_path.exists():
        dmg_path.unlink()
    if temp_dmg.exists():
        temp_dmg.unlink()

    dmg_staging = DIST_DIR / "dmg_staging"
    if dmg_staging.exists():
        shutil.rmtree(dmg_staging)
    dmg_staging.mkdir()

    print("  Preparando contenido...")
    shutil.copytree(APP_DIR, dmg_staging / f"{APP_NAME}.app")
    (dmg_staging / "Applications").symlink_to("/Applications")

    bg_source = PROJECT_DIR / "assets" / "dmg_background.png"
    if bg_source.exists():
        bg_dir = dmg_staging / ".background"
        bg_dir.mkdir()
        shutil.copy(bg_source, bg_dir / "background.png")
        print("  ✓ Fondo DMG")

    readme = dmg_staging / "LÉEME.txt"
    readme.write_text(
        f"Vibesbot {VERSION}\n\n"
        "1. Arrastra Vibesbot.app a Applications\n"
        "2. Abre Applications → Vibesbot\n"
        "3. Primera vez: clic derecho → Abrir\n\n"
        "Min apuesta $1 · chips $1/$5/$10/$50\n",
        encoding="utf-8",
    )

    if not shutil.which("hdiutil"):
        print("  ⚠ hdiutil no disponible (hace falta macOS); se omite DMG")
        zip_fallback = DIST_DIR / f"{APP_NAME}-{VERSION}-mac.app.zip"
        if zip_fallback.exists():
            zip_fallback.unlink()
        shutil.make_archive(
            str(DIST_DIR / f"{APP_NAME}-{VERSION}-mac.app"),
            "zip",
            root_dir=dmg_staging,
            base_dir=".",
        )
        print(f"  → Fallback ZIP: {zip_fallback}")
        return None

    print("  Creando imagen DMG writable...")
    result = subprocess.run(
        [
            "hdiutil", "create",
            "-volname", APP_NAME,
            "-srcfolder", str(dmg_staging),
            "-ov",
            "-format", "UDRW",
            str(temp_dmg),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not temp_dmg.exists():
        print(f"  ⚠ UDRW falló ({result.stderr.strip()}); intento UDZO directo")
        result = subprocess.run(
            [
                "hdiutil", "create",
                "-volname", APP_NAME,
                "-srcfolder", str(dmg_staging),
                "-ov",
                "-format", "UDZO",
                str(dmg_path),
            ],
            capture_output=True,
            text=True,
        )
        shutil.rmtree(dmg_staging, ignore_errors=True)
        if dmg_path.exists():
            size_mb = dmg_path.stat().st_size / (1024 * 1024)
            print(f"  ✓ DMG creado: {dmg_path} ({size_mb:.1f} MB)")
            return dmg_path
        print(f"  ❌ Error: No se pudo crear el DMG: {result.stderr}")
        return None

    mount_result = subprocess.run(
        ["hdiutil", "attach", str(temp_dmg), "-readwrite", "-noverify"],
        capture_output=True,
        text=True,
    )
    if mount_result.returncode == 0:
        mount_point = f"/Volumes/{APP_NAME}"
        applescript = f'''
tell application "Finder"
    tell disk "{APP_NAME}"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set bounds of container window to {{100, 100, 640, 480}}
        set theViewOptions to the icon view options of container window
        set arrangement of theViewOptions to not arranged
        set icon size of theViewOptions to 100
        set position of item "{APP_NAME}.app" of container window to {{140, 180}}
        set position of item "Applications" of container window to {{400, 180}}
        try
            set background picture of theViewOptions to file ".background:background.png"
        end try
        close
        open
        update without registering applications
        delay 2
        close
    end tell
end tell
'''
        if shutil.which("osascript"):
            subprocess.run(["osascript", "-e", applescript], capture_output=True)
            print("  ✓ Layout Finder + fondo")
        subprocess.run(["hdiutil", "detach", mount_point, "-quiet"], capture_output=True)
    else:
        print(f"  ⚠ No se pudo montar temp DMG: {mount_result.stderr.strip()}")

    convert = subprocess.run(
        [
            "hdiutil", "convert", str(temp_dmg),
            "-format", "UDZO",
            "-imagekey", "zlib-level=9",
            "-o", str(dmg_path),
        ],
        capture_output=True,
        text=True,
    )
    if temp_dmg.exists():
        temp_dmg.unlink()
    shutil.rmtree(dmg_staging, ignore_errors=True)

    if dmg_path.exists():
        size_mb = dmg_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ DMG creado: {dmg_path} ({size_mb:.1f} MB)")
        return dmg_path

    print(f"  ❌ Error convirtiendo DMG: {convert.stderr}")
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
