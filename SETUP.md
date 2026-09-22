# Configuración de Vibesbot (Wallet Prediction)

Producto: **Binance Wallet Prediction** (Predict.fun, BSC) vía SAPI oficial.  
No es Exchange Event Contracts. Repo: [knull66/Vibesbot](https://github.com/knull66/Vibesbot).

## 1. Instalar

```bash
git clone https://github.com/knull66/Vibesbot.git
cd Vibesbot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 run_dashboard.py
```

App Mac: descarga el release en `https://github.com/knull66/Vibesbot/releases/latest`. Después de actualizar, **Quit en el Dock** y abre de nuevo. Al arrancar borra restos de Playwright (`run_bot.py`, etc.) que el zip overlay no puede quitar.

## 2. API key (REAL)

En Binance → API Management:

1. Key **live** (desmarca Testnet en la app).
2. Activa **Enable Prediction Trading**.
3. Restringe a la **IP de este Mac**. Sin IP, `wallet/list` suele fallar.
4. Solo lectura + prediction. No hace falta Spot/Futures para apostar.

El secret se cifra al guardar (Keychain en Mac, archivo `binance_api_secret.enc` con permiso 0600). Si actualizas desde una versión que lo tenía en JSON plano, el primer load lo migra.

## 3. Dinero que se apuesta

| Sitio | ¿Se gasta? |
|-------|------------|
| Prediction Account (Portfolio → Transfer In) | Sí. Ahí va el REAL. |
| Web3 My Wallet | No. |
| Spot / Funding / Futures | No. |

Mínimo **1.50 USDT** por apuesta. Pasa USDT a BNB Smart Chain y Transfer In al Prediction Account.

Deja el campo wallet **vacío** para gastar la account listada. No pongas una address de My Wallet si no aparece en `wallet/list`.

## 4. Settings de trading

En la app (SIM y REAL comparten valores):

- Bet amount ≥ 1.50
- Confidence **0.50** (un 0.62 viejo se trata como 0.50)
- Daily loss y max trades al día **sí** cortan el motor
- Circuit breaker: 5 pérdidas seguidas, cooldown ~30 min
- Settings de trading/strategy: solo el owner en el Mac
- Bind: `127.0.0.1` (LAN `0.0.0.0` si activas companion; hay que reabrir)
- Popup de update al abrir (Actualizar / Más tarde ~12h). No hace falta ir a Settings.

Empieza en SIM. Pasa a REAL solo cuando el feed SIM y el book de Binance coinciden (Price to Beat = lock de Wallet, no la vela 5m local).

## 5. Cómo sabe si ganó

- **SIM**: lock (Chainlink/Wallet Price to Beat) vs mid Spot `bookTicker`.
- **REAL**: resultado de Binance (`isWinner` / `realizedPnl`). Si Portfolio dice Lost, Stats no puede mostrar WIN.

## 6. Problemas frecuentes

**wallet/list vacío / -2015**  
Enable Prediction Trading + IP de este Mac. Testnet no tiene Wallet Prediction.

**Apuesta $1.50 con Settings en $1**  
El mínimo de Wallet es 1.50; la app lo sube.

**Muchos SKIP**  
Solo corta favoritos 85¢+ / lotto 15¢ y un 50/50 plano vs el lock. Un DOWN 71–76% sí se apuesta.

**WIN falso vs Lost en Binance**  
Actualiza a ≥ 1.25: el settle REAL ya no usa velas locales.

**CUT LOSS / TAKE PROFIT failed: SYSTEM_ERROR**  
v1.35 vende shares humanas (no 3e18 wei). v1.36 ya no scalpea el +6¢: aguanta a Binance. Tras el overlay: Quit en el Dock.

**Gana $0.10 y pierde $0.40 todo el rato**  
Eso era el lock +6¢ / cut −12¢ vendiendo al momento de comprar. v1.36 aguanta la ronda.

**Sigue en versión vieja tras update**  
Quit desde el Dock. El overlay no mata el Python anterior.

## 7. Disclaimer

Puedes perder el Prediction Account entero. Fee ~2%. No es un bot de ML mágico.
