#!/usr/bin/env python3
"""
Script de entrada para ejecutar el bot de trading.
Uso: python run_bot.py [--config PATH] [--headless] [--testnet]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import run_bot

if __name__ == "__main__":
    run_bot()
python3 run_backtest.py --days 7