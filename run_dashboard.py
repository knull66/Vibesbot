#!/usr/bin/env python3
"""
Script de entrada para el dashboard visual de Vibesbot.
Uso: python3 run_dashboard.py [--port PORT] [--host HOST]
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.web_server import run_dashboard


def main():
    parser = argparse.ArgumentParser(
        description="Vibesbot Dashboard - Visual Trading Interface"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8080,
        help="Port to run the dashboard (default: 8080)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind (default: 0.0.0.0)"
    )
    parser.add_argument(
        "-c", "--config",
        type=str,
        help="Path to configuration file"
    )
    
    args = parser.parse_args()
    
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   ⚡ VIBESBOT DASHBOARD                                   ║
    ║   Binance Prediction Trading Radar                        ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    print(f"    🌐 Starting dashboard at http://localhost:{args.port}")
    print(f"    📊 Open your browser to view the trading interface")
    print()
    
    run_dashboard(host=args.host, port=args.port, config_path=args.config)


if __name__ == "__main__":
    main()
