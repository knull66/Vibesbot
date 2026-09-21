# Vibesbot - Bot de Trading Automatizado para Binance Prediction

Bot de trading automatizado para operar en Binance Prediction (BTC/USDT 5m "Up or Down"). El sistema utiliza machine learning para predecir la dirección del precio y gestión de riesgo avanzada para maximizar el Win Rate mientras minimiza el Maximum Drawdown.

## Características Principales

### 🤖 Predicción con IA
- Modelo LightGBM/XGBoost para clasificación binaria (UP/DOWN)
- Features financieras de alta frecuencia:
  - Indicadores técnicos (RSI, MACD, Bollinger Bands, VWAP)
  - Order Flow y Liquidity Imbalance
  - Métricas de microestructura de mercado
- Umbral de confianza configurable para filtrar señales débiles

### 📊 Streaming de Datos en Tiempo Real
- Conexión WebSocket con Binance Futures
- Velas OHLCV de 1m y 5m
- Libro de órdenes (Order Book Depth)
- Flujo de transacciones (Trade Tape)

### 🛡️ Gestión de Riesgo Avanzada
- **Kelly Criterion**: Sizing óptimo de posición
- **Circuit Breaker**: Frena la operativa tras N pérdidas consecutivas
- **Filtros de Volatilidad**: Evita operar en condiciones extremas
- **Límites Diarios**: Stop-loss y máximo de operaciones

### 🔑 Wallet Prediction API (app Mac / dashboard REAL)
- Apuestas reales por la SAPI oficial de Binance Wallet Prediction
- Requiere API key con **Enable Prediction Trading** y filtro de IP

## Estructura del Proyecto

```
vibesbot/
├── src/
│   ├── __init__.py
│   ├── config.py           # Configuración centralizada
│   ├── data_stream.py      # WebSocket y datos en tiempo real
│   ├── predictor.py        # Modelo de IA y generación de features
│   ├── risk_manager.py     # Gestión de riesgo y Kelly Criterion
│   ├── wallet_prediction.py # Cliente SAPI Wallet Prediction (REAL)
│   ├── web_server.py       # Dashboard y motor REAL/SIM
│   ├── backtest.py         # Sistema de backtesting
│   └── utils/
│       ├── __init__.py
│       ├── logger.py       # Sistema de logging
│       └── helpers.py      # Funciones auxiliares
├── models/                  # Modelos entrenados
├── logs/                    # Archivos de log
├── data/                    # Datos históricos
├── config.example.json     # Ejemplo de configuración
├── requirements.txt        # Dependencias
└── README.md
```

## Instalación

### Requisitos
- Python 3.10+
- Cuenta de Binance con API key (Enable Prediction Trading)

### Pasos

1. **Clonar el repositorio**
```bash
git clone https://github.com/knullproject/Vibesbot.git
cd Vibesbot
```

2. **Crear entorno virtual** (opcional pero recomendado)
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows
```

3. **Instalar dependencias** (opción rápida)
```bash
python3 setup.py
```

O manualmente:
```bash
pip install -r requirements.txt
```

4. **Configurar**
```bash
cp config.example.json config.json
# Editar config.json según tus preferencias
```

## Uso

### 0. Dashboard Visual (Recomendado)

Ejecuta el dashboard web para una experiencia visual completa:

```bash
python3 run_dashboard.py
```

Abre tu navegador en `http://localhost:8080` para ver:
- Panel de señales en tiempo real
- Gráficos de P&L
- Control del bot (Start/Pause/Stop)
- Historial de operaciones
- Métricas de riesgo

### 1. Entrenamiento y Backtest

Antes de operar en vivo, entrena el modelo con datos históricos:

```bash
python3 run_backtest.py --days 30
```

Opciones disponibles:
- `--days N`: Número de días de datos históricos (default: 30)
- `--config PATH`: Ruta al archivo de configuración
- `--no-save-model`: No guardar el modelo entrenado
- `-o, --output DIR`: Directorio de salida para resultados

### 2. Operar en REAL (app Mac)

Para apuestas reales usa la app Mac en modo REAL con una API key de Binance que tenga **Enable Prediction Trading**. El motor llama a `WalletPredictionClient` (SAPI).

### Variables de Entorno

Puedes configurar el bot mediante variables de entorno:

```bash
export VIBESBOT_CAPITAL=100
export VIBESBOT_CONFIDENCE=0.62
export VIBESBOT_MAX_DAILY_LOSS=20
export VIBESBOT_TESTNET=true
```

## Configuración

### Parámetros de Trading

| Parámetro | Descripción | Default |
|-----------|-------------|---------|
| `initial_capital` | Capital inicial | 100.0 |
| `base_bet_amount` | Apuesta base | 1.0 |
| `sizing_strategy` | Estrategia de sizing | half_kelly |
| `kelly_fraction` | Fracción de Kelly | 0.5 |

### Parámetros de Predicción

| Parámetro | Descripción | Default |
|-----------|-------------|---------|
| `confidence_threshold` | Umbral mínimo de confianza | 0.62 |
| `use_order_book` | Usar features de order book | true |
| `use_trade_flow` | Usar features de trade flow | true |

### Parámetros de Riesgo

| Parámetro | Descripción | Default |
|-----------|-------------|---------|
| `max_daily_loss` | Pérdida máxima diaria | 20.0 |
| `circuit_breaker_consecutive_losses` | Pérdidas para activar circuit breaker | 5 |
| `max_trades_per_day` | Máximo de operaciones diarias | 100 |

## Estrategias de Sizing

### Fixed Amount
Apuesta un monto fijo en cada operación.

### Kelly Criterion
Calcula el tamaño óptimo basado en:
```
Kelly% = (p * b - q) / b
```
- p = probabilidad de ganar
- q = probabilidad de perder
- b = ratio de pago (0.95 en Binance Prediction)

### Half-Kelly (Recomendado)
Versión conservadora del Kelly Criterion que reduce la varianza:
```
Bet = Kelly% * 0.5 * Capital
```

### Anti-Martingala
Aumenta la apuesta después de ganar, resetea después de perder.

## Gestión de Riesgo

### Circuit Breaker
Se activa automáticamente después de N pérdidas consecutivas:
- Pausa la operativa
- Espera el periodo de cooldown configurado
- Reanuda automáticamente

### Filtros de Volatilidad
- **Volatilidad baja**: No opera si el mercado está muy consolidado
- **Volatilidad alta**: Evita periodos de alta incertidumbre

### Límites Operativos
- Máximo de operaciones por hora y día
- Stop-loss diario
- Protección del capital

## Logging

Los logs se guardan en `./logs/` con el formato:
```
YYYY-MM-DD HH:MM:SS | LEVEL | module:function:line | message
```

Incluyen:
- Predicciones del modelo con confianza
- Ejecución de operaciones
- Resultados y PnL acumulado
- Eventos de riesgo y circuit breaker

## Métricas de Backtest

El sistema genera las siguientes métricas:

- **Win Rate**: Porcentaje de operaciones ganadoras
- **Profit Factor**: Ganancias totales / Pérdidas totales
- **Sharpe Ratio**: Retorno ajustado por riesgo
- **Max Drawdown**: Pérdida máxima desde un pico
- **Consecutive Wins/Losses**: Rachas de operaciones

## Advertencias

⚠️ **DISCLAIMER**: Este software es solo para fines educativos y de investigación.

- El trading de criptomonedas conlleva riesgos significativos
- Los resultados pasados no garantizan resultados futuros
- Nunca inviertas más de lo que puedas permitirte perder
- Verifica la legalidad del trading automatizado en tu jurisdicción

## Mejoras Futuras

- [ ] Integración con más exchanges
- [ ] Soporte para múltiples pares
- [ ] Dashboard web para monitoreo
- [ ] Optimización de hiperparámetros automática
- [ ] Ensemble de modelos
- [ ] Detección de cambios de régimen de mercado

## Contribuir

Las contribuciones son bienvenidas. Por favor:

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

Este proyecto está bajo la licencia MIT. Ver `LICENSE` para más detalles.

## Contacto

Para preguntas o soporte, abre un issue en el repositorio.
