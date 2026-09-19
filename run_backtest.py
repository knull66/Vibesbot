#!/usr/bin/env python3
"""
Script de entrada para ejecutar el backtest.
Uso: python run_backtest.py [--days N] [--config PATH]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backtest import main

if __name__ == "__main__":
    main()
