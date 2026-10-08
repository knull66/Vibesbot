# Vibesbot 1.51.1 — instalar ahora

Los enlaces del chat de Cursor dicen **File not found**. Usa GitHub.

## Opción rápida (Terminal en Mac)

Copia y pega **todo** esto:

```bash
curl -fsSL -o ~/Downloads/vb1511.zip https://github.com/knull66/Vibesbot/archive/refs/tags/v1.51.1.zip && rm -rf ~/Downloads/Vibesbot-1.51.1 && mkdir -p ~/Downloads/Vibesbot-1.51.1 && unzip -q ~/Downloads/vb1511.zip -d ~/Downloads/Vibesbot-1.51.1 && cd ~/Downloads/Vibesbot-1.51.1/Vibesbot-1.51.1 && PYTHONPATH=. python3 -c "from src.ship_inflate import inflate_ship; print('OK', inflate_ship())" && python3 app_launcher.py
```

## Opción manual

1. Borra carpetas viejas: `~/Downloads/Vibesbot-1.51.0` y apps rotas.
2. Abre: https://github.com/knull66/Vibesbot/releases/tag/v1.51.1
3. Descarga **Source code (zip)** (abajo en Assets).
4. Descomprime → entra a la carpeta → en Terminal:

```bash
cd ~/Downloads/Vibesbot-1.51.1
PYTHONPATH=. python3 -c "from src.ship_inflate import inflate_ship; print(inflate_ship())"
python3 app_launcher.py
```

## Qué debes ver

- Login / lobby (no pantalla negra)
- Versión **v1.51.1**
- Apuesta mínima **$1**
- Chips **$1 / $5 / $10 / $50**

Si falla: `~/Library/Logs/Vibesbot.log`
