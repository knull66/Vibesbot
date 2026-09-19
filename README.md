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

### 🌐 Automatización del Navegador
- Playwright con contexto persistente de usuario
- Sincronización precisa con el reloj de Binance
- Ejecución de apuestas 10-12 segundos antes del cierre
- Manejo robusto de errores y reintentos

## Estructura del Proyecto

```
vibesbot/
├── src/
│   ├── __init__.py
│   ├── config.py           # Configuración centralizada
│   ├── data_stream.py      # WebSocket y datos en tiempo real
│   ├── predictor.py        # Modelo de IA y generación de features
│   ├── risk_manager.py     # Gestión de riesgo y Kelly Criterion
│   ├── browser_execution.py # Automatización con Playwright
│   ├── main.py             # Orquestador principal
│   ├── backtest.py         # Sistema de backtesting
│   └── utils/
│       ├── __init__.py
│       ├── logger.py       # Sistema de logging
│       └── helpers.py      # Funciones auxiliares
├── models/                  # Modelos entrenados
├── logs/                    # Archivos de log
├── user_data/              # Datos de sesión del navegador
├── data/                   # Datos históricos
├── config.example.json     # Ejemplo de configuración
├── requirements.txt        # Dependencias
└── README.md
```

## Instalación

### Requisitos
- Python 3.10+
- Cuenta de Binance con sesión activa

### Pasos

1. **Clonar el repositorio**
```bash
git clone https://github.com/knullproject/Vibesbot.git
cd Vibesbot
```

2. **Crear entorno virtual**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows
```

3. **Instalar dependencias**
```bash
pip install -r requirements.txt
playwright install chromium
```

4. **Configurar**
```bash
cp config.example.json config.json
# Editar config.json según tus preferencias
```

## Uso

### 1. Entrenamiento y Backtest

Antes de operar en vivo, entrena el modelo con datos históricos:

```bash
python -m src.backtest --days 30
```

Opciones disponibles:
- `--days N`: Número de días de datos históricos (default: 30)
- `--config PATH`: Ruta al archivo de configuración
- `--no-save-model`: No guardar el modelo entrenado
- `-o, --output DIR`: Directorio de salida para resultados

### 2. Iniciar Sesión en Binance

La primera vez, necesitas iniciar sesión manualmente:

```bash
python -m src.main
```

El navegador se abrirá. Inicia sesión en tu cuenta de Binance y navega a la página de Prediction. El bot guardará la sesión para futuros usos.

### 3. Ejecutar el Bot

```bash
python -m src.main
```

Opciones disponibles:
- `-c, --config PATH`: Ruta al archivo de configuración
- `--headless`: Ejecutar en modo sin interfaz gráfica
- `--testnet`: Usar testnet de Binance
- `--dry-run`: Ejecutar sin realizar apuestas reales

### Variables de Entorno

Puedes configurar el bot mediante variables de entorno:

```bash
export VIBESBOT_CAPITAL=100
export VIBESBOT_CONFIDENCE=0.62
export VIBESBOT_MAX_DAILY_LOSS=20
export VIBESBOT_HEADLESS=true
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
