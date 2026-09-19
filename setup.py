#!/usr/bin/env python3
"""
Script de configuración inicial del proyecto.
Instala dependencias y configura Playwright.
"""
import subprocess
import sys
import os


def main():
    print("=" * 60)
    print("VIBESBOT - Setup")
    print("=" * 60)
    
    print("\n[1/3] Instalando dependencias de Python...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
    
    print("\n[2/3] Instalando navegador Chromium para Playwright...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    
    print("\n[3/3] Creando directorios necesarios...")
    os.makedirs("logs", exist_ok=True)
    os.makedirs("models", exist_ok=True)
    os.makedirs("user_data", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    os.makedirs("backtest_results", exist_ok=True)
    
    print("\n" + "=" * 60)
    print("Setup completado!")
    print("=" * 60)
    print("\nPróximos pasos:")
    print("  1. Ejecutar backtest:  python run_backtest.py --days 30")
    print("  2. Ejecutar bot:       python run_bot.py")
    print("\nPara más opciones: python run_backtest.py --help")
    print("                   python run_bot.py --help")


if __name__ == "__main__":
    main()
