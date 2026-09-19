#!/bin/bash
# ═══════════════════════════════════════════════════════════
#   ⚡ VIBESBOT - Lanzador para macOS
#   Doble clic para iniciar
# ═══════════════════════════════════════════════════════════

cd "$(dirname "$0")"

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║   ⚡ VIBESBOT TRADING RADAR                               ║"
echo "║   Iniciando...                                            ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python3 no está instalado"
    echo "   Instálalo desde https://python.org"
    read -p "Presiona Enter para salir..."
    exit 1
fi

# Instalar dependencias básicas (sin pywebview)
echo "📦 Verificando dependencias..."
pip3 install --quiet fastapi uvicorn jinja2 aiohttp pandas numpy ta lightgbm xgboost scikit-learn 2>/dev/null

# Matar procesos anteriores
pkill -f "uvicorn.*web_server" 2>/dev/null
sleep 1

# Iniciar servidor
echo "🚀 Iniciando servidor en http://localhost:8080"
echo ""

# Abrir navegador después de 2 segundos
(sleep 2 && open "http://localhost:8080") &

# Ejecutar dashboard
python3 -c "
import sys
sys.path.insert(0, '.')
from src.web_server import run_dashboard
run_dashboard(port=8080)
"
