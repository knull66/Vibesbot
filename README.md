# Vibesbot

App Mac + dashboard local para **Binance Wallet Prediction** (Predict.fun en BNB Smart Chain): mercados BTC/USDT 5m Up or Down.

Esto **no** es Binance Exchange Event Contracts (`binance.com/prediction`). No hay API oficial de apuestas ahí. Vibesbot usa solo la SAPI oficial:

`https://api.binance.com/sapi/v1/w3w/wallet/prediction`

Clona el repo público: [knull66/Vibesbot](https://github.com/knull66/Vibesbot).

## Qué hace de verdad

- **SIM**: paper trading contra el lock de Wallet (Price to Beat) y el mid de Binance Spot `bookTicker`.
- **REAL**: `get-quote` + `place-order-bundle` firmados. Gasta el **Prediction Account** de `wallet/list` (Portfolio → Transfer In), no Web3 My Wallet.
- **Settlement REAL**: `position/settled-history` / posiciones ENDED. No inventa WIN/LOSS con velas 5m locales.
- **Señal**: mayoría de indicadores + tape (`round_signal`). El panel Strategy ajusta esos pesos. No hay LightGBM en el camino de apuesta. Umbral ~**0.50**.
- **Filtros**: modo agresivo. Book 20–82% (un DOWN 76% sí). Solo corta 88%+ y 92¢ que pagan centavos. ≥ $3 vs Price to Beat. Señal con 2 votos (RSI solo ya cuenta).
- **Price to Beat**: lock oficial de Wallet si Binance lo manda; si no, el open de la vela 5m de Spot (etiqueta “Est. 5m open”). Sirve para no apostar un 50/50 al inicio de ronda. REAL se liquida con Binance, no con esa línea.
- **Circuit breaker**: 5 pérdidas seguidas pausan ~30 min. Settings de pérdida diaria y máximo de trades también cortan.
- **Salida**: lock si el book sube ≥ +6¢ (~$0.12). Cut si cae ≥ −12¢ y vender salva ≥ $0.25. Si no, Binance liquida. Más trades no significa perder el stake entero cada vez.
- **Drawdown**: en REAL el pico es el saldo de la wallet, no los $100 de SIM. Un −$1.50 sobre ~$9 es ~16%, no 92%.
- **Updates**: popup Actualizar / Más tarde al abrir y cada ~30 min. No hay que ir a Settings.

## Bind y Settings

El dashboard escucha **127.0.0.1** salvo que el companion LAN esté activo (`0.0.0.0`). Settings de trading y strategy son **owner-only**.

Playwright y el clicker de Event Contracts están eliminados. Al abrir, se purgan restos (`run_bot.py`).

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
