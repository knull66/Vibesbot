# Vibesbot 1.51.2 — DMG con icono

El DMG se genera **en macOS** (`hdiutil` + `sips`/`iconutil`), igual que antes.

## Generar el instalador (tu Mac)

En la carpeta del proyecto (`~/Downloads/Vibesbot`):

```bash
cd ~/Downloads/Vibesbot
curl -fsSL -o build_simple_app.py https://raw.githubusercontent.com/knull66/Vibesbot/main/build_simple_app.py
curl -fsSL -o make_dmg_mac.command https://raw.githubusercontent.com/knull66/Vibesbot/main/make_dmg_mac.command
curl -fsSL -o VERSION https://raw.githubusercontent.com/knull66/Vibesbot/main/VERSION
chmod +x make_dmg_mac.command
python3 build_simple_app.py
open dist/Vibesbot-1.51.2.dmg
```

O doble clic en **make_dmg_mac.command**.

Salida:
- `dist/Vibesbot.app` (con **AppIcon**)
- `dist/Vibesbot-1.51.2.dmg` (app + Applications + fondo)

Instalar: abre el DMG → arrastra Vibesbot a Applications → clic derecho → Abrir.

## Qué incluye el DMG

- Icono de app (bunny)
- Fondo profesional
- Enlace a Applications
- Min **$1** · chips **$1/$5/$10/$50** · v**1.51.2**
