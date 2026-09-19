# Configuración de Vibesbot

Esta guía explica cómo configurar Vibesbot para operar en producción.

## 1. Instalación Rápida

```bash
# Clonar e instalar
git clone https://github.com/knullproject/Vibesbot.git
cd Vibesbot

# Instalar como aplicación de escritorio
python3 install.py
```

Después de instalar, puedes abrir Vibesbot desde tu menú de aplicaciones o ejecutando `python3 vibesbot.py`.

## 2. Entrenar el Modelo

**IMPORTANTE**: Antes de operar en vivo, debes entrenar el modelo con datos históricos.

```bash
# Entrenar con 30 días de datos (recomendado)
python3 run_backtest.py --days 30

# O con más datos para mejor precisión
python3 run_backtest.py --days 60
```

Esto genera:
- `models/prediction_model.pkl` - Modelo entrenado
- `models/feature_scaler.pkl` - Escalador de features
- `backtest_results/` - Métricas y estadísticas

## 3. Configuración

Crea tu archivo de configuración:

```bash
cp config.example.json config.json
```

Edita `config.json` con tus preferencias:

```json
{
  "trading": {
    "initial_capital": 100.0,      // Tu capital inicial en USDT
    "base_bet_amount": 1.0,        // Apuesta base
    "min_bet_amount": 0.5,         // Mínimo por operación
    "max_bet_amount": 10.0,        // Máximo por operación
    "sizing_strategy": "half_kelly" // fixed, kelly, half_kelly, percent
  },
  "prediction": {
    "confidence_threshold": 0.62   // Solo operar si confianza > 62%
  },
  "risk": {
    "max_daily_loss": 20.0,        // Stop loss diario
    "circuit_breaker_consecutive_losses": 5,  // Parar tras 5 pérdidas
    "max_trades_per_day": 100      // Límite de operaciones diarias
  }
}
```

## 4. Modos de Operación

### Modo Dashboard (Recomendado para empezar)

```bash
python3 run_dashboard.py
```

- Interfaz visual en `http://localhost:8080`
- Control manual con botones START/PAUSE/STOP
- **No ejecuta apuestas reales** - Modo simulación

### Modo Bot Real (Con Playwright)

```bash
python3 run_bot.py
```

Este modo:
1. Abre un navegador con tu sesión de Binance
2. Navega a Binance Prediction
3. Ejecuta apuestas automáticamente

**Primera vez:**
1. Se abrirá el navegador
2. Inicia sesión manualmente en Binance
3. La sesión se guardará en `user_data/`
4. Las próximas veces no necesitas login

## 5. Estrategias de Sizing

| Estrategia | Descripción | Riesgo |
|------------|-------------|--------|
| `fixed` | Monto fijo por operación | Bajo |
| `percent` | % del capital (ej. 2%) | Bajo |
| `half_kelly` | Kelly Criterion × 0.5 | Medio |
| `kelly` | Kelly Criterion completo | Alto |
| `anti_martingale` | Aumenta tras ganar | Variable |

**Recomendación**: Empieza con `fixed` o `half_kelly`.

## 6. Gestión de Riesgo

### Circuit Breaker
Se activa automáticamente tras N pérdidas consecutivas:
```json
{
  "risk": {
    "circuit_breaker_consecutive_losses": 5,
    "circuit_breaker_cooldown_minutes": 30
  }
}
```

### Filtros de Volatilidad
Evita operar en condiciones extremas:
```json
{
  "risk": {
    "min_volatility_threshold": 0.0005,  // Muy bajo = mercado muerto
    "max_volatility_threshold": 0.02     // Muy alto = muy riesgoso
  }
}
```

### Límites Diarios
```json
{
  "risk": {
    "max_daily_loss": 20.0,        // Stop loss en $
    "max_daily_loss_percent": 0.20, // O 20% del capital
    "max_trades_per_day": 100,
    "max_trades_per_hour": 12
  }
}
```

## 7. Variables de Entorno (Opcional)

Puedes configurar via variables de entorno:

```bash
export VIBESBOT_CAPITAL=100
export VIBESBOT_CONFIDENCE=0.62
export VIBESBOT_MAX_DAILY_LOSS=20
export VIBESBOT_HEADLESS=false    # true para modo sin interfaz
export VIBESBOT_TESTNET=false     # true para usar testnet
```

## 8. Monitoreo y Logs

Los logs se guardan en `logs/`:
- `vibesbot_YYYY-MM-DD.log` - Log principal
- Incluye: predicciones, trades, PnL, errores

Para ver los logs en tiempo real:
```bash
tail -f logs/vibesbot_$(date +%Y-%m-%d).log
```

## 9. Solución de Problemas

### Error 451 de Binance
La API de Binance está bloqueada en tu región. Soluciones:
- Usa un VPN
- El dashboard funciona con datos históricos en modo simulación

### Modelo no cargado
```bash
# Entrena el modelo primero
python3 run_backtest.py --days 30
```

### Puerto en uso
```bash
# Usa otro puerto
python3 run_dashboard.py --port 3000
```

### Sesión de Binance expirada
Borra los datos de sesión y vuelve a iniciar:
```bash
rm -rf user_data/
python3 run_bot.py  # Hará login de nuevo
```

## 10. Advertencias

⚠️ **IMPORTANTE**:
- Nunca inviertas más de lo que puedas perder
- Los resultados de backtest no garantizan resultados futuros
- El modelo puede tener overfitting
- Usa primero el modo simulación para probar
- Binance Prediction tiene una comisión del 5%

## 11. Flujo Recomendado

1. **Instalar**: `python3 install.py`
2. **Entrenar**: `python3 run_backtest.py --days 30`
3. **Probar en Dashboard**: `python3 run_dashboard.py` (modo simulación)
4. **Configurar**: Editar `config.json` según resultados
5. **Operar**: `python3 run_bot.py` (cuando estés listo)
