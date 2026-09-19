#!/usr/bin/env python3
"""
VIBESBOT - Aplicación de Trading
Doble clic para iniciar o ejecuta: python3 vibesbot.py
"""
import sys
import os
from pathlib import Path

VIBESBOT_DIR = Path(__file__).parent.absolute()
os.chdir(VIBESBOT_DIR)
sys.path.insert(0, str(VIBESBOT_DIR))

def main():
    try:
        import webview
        from src.desktop_app import main as desktop_main
        desktop_main()
    except ImportError:
        print("⚠️  pywebview no instalado. Abriendo en navegador...")
        import webbrowser
        from src.web_server import run_dashboard
        webbrowser.open("http://localhost:8080")
        run_dashboard(port=8080)

if __name__ == "__main__":
    main()
