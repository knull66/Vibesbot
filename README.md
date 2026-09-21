# Vibesbot

App Mac + dashboard local para **Binance Wallet Prediction** (Predict.fun en BNB Smart Chain): mercados BTC/USDT 5m Up or Down.

Esto **no** es Binance Exchange Event Contracts (`binance.com/prediction`). No hay API oficial de apuestas ahí. Vibesbot usa solo la SAPI oficial:

`https://api.binance.com/sapi/v1/w3w/wallet/prediction`

Clona el repo público: [knull66/Vibesbot](https://github.com/knull66/Vibesbot).

## Qué hace de verdad

- **SIM**: paper trading contra el lock de Wallet (Price to Beat) y el mid de Binance Spot `bookTicker`.
- **REAL**: `get-quote` + `place-order-bundle` firmados. Gasta el **Prediction Account** de `wallet/list` (Portfolio → Transfer In), no Web3 My Wallet.
- **Settlement REAL**: `position/settled-history` / posiciones ENDED. No inventa WIN/LOSS con velas 5m locales.
- **Señal**: mayoría de indicadores + tape (`round_signal`). No es un modelo ML en el camino de apuesta del dashboard. El umbral efectivo por defecto es **0.50** (un 0.62 legado se mapea a 0.50 porque bloqueaba casi todo).
- **Edge**: solo apuesta si el share price está ~0.38–0.62 y el precio ya se movió ≥ $12 vs Price to Beat.

## Lo que no está cableado (aún)

El dashboard **no** llama a `RiskManager` / circuit breaker en `_execute_trade`. Sí respeta los límites de Settings: pérdida diaria y máximo de trades. No vendas el circuit breaker como si frenara el bot hoy.

Playwright y el clicker de Event Contracts están eliminados.

## Requisitos para REAL

1. API key de Binance **live** (no testnet).
2. Permiso **Enable Prediction Trading**.
3. **Restricción de IP** a la IP de este Mac (Binance lo exige para ese permiso).
4. USDT en el **Prediction Account** (Transfer In ≥ 1.50), red BNB Smart Chain.
5. En Settings, deja la wallet vacía salvo que quieras forzar una address que **sí** aparezca en `wallet/list`.

El API secret se guarda cifrado (Keychain en macOS, sidecar `chmod 0600` en el resto). No va en texto plano dentro de `user_settings.json`.

## App Mac (uso previsto)

Actualiza desde GitHub Releases (`knull66/Vibesbot`). Tras un overlay zip: **Quit desde el Dock** y vuelve a abrir; el Python que sigue en memoria es el viejo hasta que cierras. Al abrir, la app borra restos de Playwright (`run_bot.py`, `browser_execution.py`) en la carpeta que corre y en `~/Downloads/Vibesbot`.

```bash
python3 run_dashboard.py
```

Dashboard en `http://localhost:8080`. PIN de companion si lo usas en LAN.

## Clone

```bash
git clone https://github.com/knull66/Vibesbot.git
cd Vibesbot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 run_dashboard.py
```

## Settings que importan

| Campo | Default real | Notas |
|-------|----------------|-------|
| `bet_amount` | 1.50 USDT | Mínimo de Wallet. $1 se sube a $1.50. |
| `confidence_threshold` | 0.50 | 0.62 legado → 0.50 |
| `max_daily_loss` | 50 | Sí se aplica en el motor del dashboard |
| `max_trades_per_day` | 50 | Sí se aplica |

## Advertencia

Predicción 5m es ~50/50 con fee ~2%. Apostar al open sin movimiento vs Price to Beat es -EV. Usa poco capital. Resultados pasados no predicen el futuro.
