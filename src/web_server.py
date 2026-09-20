"""
Servidor web para el dashboard de Vibesbot.

Proporciona:
- Dashboard visual en tiempo real
- WebSocket para actualizaciones
- Control del bot (start/stop/pause)
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set
import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .config import Config, load_config
from .data_stream import DataStream
from .predictor import Predictor, Signal, ModelType
from .risk_manager import RiskManager, RiskStatus
from .utils.logger import setup_logger, get_logger
from .utils.helpers import calculate_time_to_next_round, calculate_round_times


logger = get_logger("web_server")


class ConnectionManager:
    """Gestiona conexiones WebSocket activas."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Envía mensaje a todos los clientes conectados."""
        if not self.active_connections:
            return
        
        data = json.dumps(message)
        disconnected = set()
        
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception:
                disconnected.add(connection)
        
        for conn in disconnected:
            self.active_connections.discard(conn)


class DashboardBot:
    """
    Bot de trading con interfaz web.
    
    Versión simplificada del bot principal que funciona sin navegador,
    enviando actualizaciones al dashboard web.
    """
    
    def __init__(self, config: Config, manager: ConnectionManager):
        self.config = config
        self.manager = manager
        
        self.data_stream: Optional[DataStream] = None
        self.predictor: Optional[Predictor] = None
        self.risk_manager: Optional[RiskManager] = None
        
        self._running = False
        self._paused = False
        self._task: Optional[asyncio.Task] = None
        self._data_task: Optional[asyncio.Task] = None
        
        self._trades = []
        self._cumulative_pnl = 0.0
        self._wins = 0
        self._losses = 0
        self._time_offset = 0.0  # Offset de sincronización con Binance
        
        # Última predicción generada (para usar en el trade)
        self._last_prediction = None
        self._last_prediction_confidence = 0.5
    
    async def initialize(self) -> bool:
        """Inicializa los componentes del bot."""
        try:
            # Sincronizar tiempo con Binance
            from .utils.helpers import sync_binance_time
            logger.info("Synchronizing time with Binance...")
            self._time_offset = await sync_binance_time()
            logger.info(f"Time offset: {self._time_offset:.3f}s")
            
            logger.info("Initializing data stream...")
            self.data_stream = DataStream(self.config.data_stream)
            await self.data_stream.start()
            
            logger.info("Initializing predictor...")
            self.predictor = Predictor(self.config.prediction, ModelType.LIGHTGBM)
            model_loaded = await self.predictor.initialize()
            
            logger.info("Initializing risk manager...")
            self.risk_manager = RiskManager(self.config.risk, self.config.trading)
            
            await self.manager.broadcast({
                "type": "status",
                "running": False,
                "paused": False,
                "model_loaded": model_loaded
            })
            
            # Iniciar loop de datos en background (siempre activo)
            self._data_task = asyncio.create_task(self._data_loop())
            
            return True
            
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            return False
    
    async def _data_loop(self):
        """Loop que siempre envía datos de mercado, incluso sin trading."""
        logger.info("Data loop started - sending market updates")
        
        while True:
            try:
                # Solo enviar si NO está corriendo el trading loop
                # (para evitar duplicados)
                if not self._running:
                    await self._send_updates()
                
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in data loop: {e}")
                await asyncio.sleep(2)
    
    async def start(self):
        """Inicia el loop de trading."""
        if self._running:
            return
        
        self._running = True
        self._paused = False
        self._task = asyncio.create_task(self._run_loop())
        
        await self.manager.broadcast({
            "type": "status",
            "running": True,
            "paused": False,
            "model_loaded": self.predictor.is_ready if self.predictor else False
        })
    
    async def stop(self):
        """Detiene el loop de trading."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        await self.manager.broadcast({
            "type": "status",
            "running": False,
            "paused": False,
            "model_loaded": self.predictor.is_ready if self.predictor else False
        })
    
    def pause(self):
        """Pausa el trading."""
        self._paused = True
        asyncio.create_task(self.manager.broadcast({
            "type": "status",
            "running": True,
            "paused": True,
            "model_loaded": self.predictor.is_ready if self.predictor else False
        }))
    
    def resume(self):
        """Reanuda el trading."""
        self._paused = False
        asyncio.create_task(self.manager.broadcast({
            "type": "status",
            "running": True,
            "paused": False,
            "model_loaded": self.predictor.is_ready if self.predictor else False
        }))
    
    async def _run_loop(self):
        """Loop principal de trading."""
        import random
        logger.info("Trading loop started")
        
        last_prediction_round = -1
        last_trade_round = -1
        
        # Enviar mensaje de inicio
        await self.manager.broadcast({
            "type": "log",
            "message": "Bot started - waiting for next prediction window",
            "level": "info"
        })
        
        while self._running:
            try:
                await self._send_updates()
                
                if self._paused:
                    await asyncio.sleep(1)
                    continue
                
                round_times = calculate_round_times(5, self._time_offset)
                remaining = round_times["seconds_remaining"]
                current_round = round_times.get("round_number", 0)
                
                # Generar predicción cuando quedan 60-90 segundos
                if 60 <= remaining <= 90 and current_round != last_prediction_round:
                    await self._generate_prediction()
                    last_prediction_round = current_round
                
                # Ejecutar trade cuando quedan 10-20 segundos
                if 10 <= remaining <= 20 and current_round != last_trade_round:
                    await self._execute_trade()
                    last_trade_round = current_round
                
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(2)
        
        logger.info("Trading loop ended")
    
    async def _generate_prediction(self):
        """Genera y envía una predicción (con modelo o simulada)."""
        import random
        
        try:
            signal = "WAIT"
            confidence = 0.5
            prob_up = 0.5
            prob_down = 0.5
            
            # Intentar usar el modelo real
            if self.predictor and self.predictor.is_ready:
                prediction = await self.predictor.predict(self.data_stream)
                signal = prediction.signal.value
                confidence = prediction.confidence
                prob_up = prediction.probability_up
                prob_down = prediction.probability_down
            else:
                # Simulación basada en indicadores
                if self.data_stream:
                    df = self.data_stream.get_candles_df("1m")
                    if len(df) > 14:
                        try:
                            import ta
                            close = df["close"].astype(float)
                            rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
                            
                            # RSI < 30 = oversold (probable UP), RSI > 70 = overbought (probable DOWN)
                            if rsi < 35:
                                signal = "UP"
                                confidence = 0.55 + random.uniform(0, 0.15)
                                prob_up = confidence
                                prob_down = 1 - confidence
                            elif rsi > 65:
                                signal = "DOWN"
                                confidence = 0.55 + random.uniform(0, 0.15)
                                prob_down = confidence
                                prob_up = 1 - confidence
                            else:
                                # Random con ligero sesgo
                                if random.random() > 0.5:
                                    signal = "UP"
                                    confidence = 0.52 + random.uniform(0, 0.12)
                                else:
                                    signal = "DOWN"
                                    confidence = 0.52 + random.uniform(0, 0.12)
                                prob_up = confidence if signal == "UP" else 1 - confidence
                                prob_down = 1 - prob_up
                        except:
                            pass
            
            # Guardar predicción para el trade
            self._last_prediction = signal
            self._last_prediction_confidence = confidence
            
            await self.manager.broadcast({
                "type": "prediction",
                "signal": signal,
                "confidence": confidence * 100,
                "prob_up": prob_up * 100,
                "prob_down": prob_down * 100
            })
            
            # Obtener razón de la predicción
            reason = ""
            if self.data_stream:
                df = self.data_stream.get_candles_df("1m")
                if len(df) > 14:
                    try:
                        import ta
                        close = df["close"].astype(float)
                        rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
                        macd = ta.trend.MACD(close).macd_diff().iloc[-1]
                        
                        if rsi < 35:
                            reason = f"RSI={rsi:.0f} (oversold)"
                        elif rsi > 65:
                            reason = f"RSI={rsi:.0f} (overbought)"
                        else:
                            reason = f"RSI={rsi:.0f}, MACD={macd:.1f}"
                    except:
                        reason = "technical analysis"
            
            await self.manager.broadcast({
                "type": "log",
                "message": f"📊 Prediction: {signal} ({confidence*100:.1f}%) - {reason}",
                "level": "info"
            })
            
            logger.info(f"Prediction: {signal} @ {confidence:.1%}")
            
        except Exception as e:
            logger.error(f"Error generating prediction: {e}")
    
    async def _execute_trade(self):
        """Ejecuta un trade simulado basado en la última predicción."""
        import random
        from datetime import datetime
        
        try:
            # Usar la predicción guardada
            signal = self._last_prediction
            confidence = self._last_prediction_confidence
            
            # Si no hay predicción válida, saltar
            if not signal or signal == "WAIT":
                await self.manager.broadcast({
                    "type": "log", 
                    "message": "Skipped: No valid prediction",
                    "level": "warn"
                })
                return
            
            # Solo tradear si hay suficiente confianza (>55%)
            if confidence < 0.55:
                await self.manager.broadcast({
                    "type": "log", 
                    "message": f"Skipped: Low confidence ({confidence*100:.1f}%)",
                    "level": "warn"
                })
                return
            
            # Obtener precio actual
            current_price = 80000.0
            if self.data_stream:
                current_price = self.data_stream.get_current_price() or current_price
            
            # Guardar precio de entrada
            entry_price = current_price
            
            amount = 1.0  # $1 por trade
            
            # Esperar 3 segundos y ver el nuevo precio para determinar resultado
            await asyncio.sleep(3)
            
            new_price = current_price
            if self.data_stream:
                new_price = self.data_stream.get_current_price() or current_price
            
            # Determinar resultado basado en movimiento real del precio
            price_moved_up = new_price > entry_price
            
            # WIN si: predijimos UP y el precio subió, o predijimos DOWN y el precio bajó
            is_win = (signal == "UP" and price_moved_up) or (signal == "DOWN" and not price_moved_up)
            
            # Si el precio no se movió, usar probabilidad basada en confianza
            if abs(new_price - entry_price) < 0.01:
                is_win = random.random() < (confidence * 0.8 + 0.1)
            
            pnl = amount * 0.95 if is_win else -amount
            result = "WIN" if is_win else "LOSS"
            
            # Actualizar estadísticas
            if is_win:
                self._wins += 1
            else:
                self._losses += 1
            self._cumulative_pnl += pnl
            
            # Calcular cambio de precio
            price_change = new_price - entry_price
            price_direction = "↑" if price_change > 0 else "↓" if price_change < 0 else "→"
            
            # Enviar trade al frontend
            await self.manager.broadcast({
                "type": "trade",
                "timestamp": datetime.now().isoformat(),
                "direction": signal,
                "amount": amount,
                "entry_price": entry_price,
                "exit_price": new_price,
                "confidence": confidence * 100,
                "pnl": pnl,
                "result": result
            })
            
            # Enviar log detallado
            emoji = "✓" if is_win else "✗"
            price_diff = abs(new_price - entry_price)
            
            explanation = ""
            if signal == "UP":
                if price_moved_up:
                    explanation = "Price went UP as predicted"
                else:
                    explanation = "Price went DOWN (wrong)"
            else:  # DOWN
                if not price_moved_up:
                    explanation = "Price went DOWN as predicted"
                else:
                    explanation = "Price went UP (wrong)"
            
            await self.manager.broadcast({
                "type": "log",
                "message": f"{emoji} Bet {signal} @ ${entry_price:,.0f} → ${new_price:,.0f} ({price_direction}${price_diff:.2f}) = {result}",
                "level": "success" if is_win else "error"
            })
            
            await self.manager.broadcast({
                "type": "log",
                "message": f"   {explanation}. P&L: ${pnl:+.2f}",
                "level": "success" if is_win else "error"
            })
            
            # Actualizar stats
            total_trades = self._wins + self._losses
            winrate = (self._wins / max(1, total_trades)) * 100
            
            await self.manager.broadcast({
                "type": "stats",
                "capital": 100.0 + self._cumulative_pnl,
                "pnl": self._cumulative_pnl,
                "trades": total_trades,
                "winrate": winrate,
                "wins": self._wins,
                "losses": self._losses,
                "streak": 0,
                "max_drawdown": 0
            })
            
            logger.info(f"Trade: {signal} @ ${entry_price:.2f} -> ${new_price:.2f} = {result} (${pnl:+.2f})")
            
            # Limpiar predicción después de usarla
            self._last_prediction = None
            
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            import traceback
            traceback.print_exc()
    
    async def _send_updates(self):
        """Envía actualizaciones periódicas al dashboard."""
        import random
        
        # Calcular tiempo de ronda (sincronizado con Binance)
        round_times = calculate_round_times(5, self._time_offset)
        remaining = int(round_times["seconds_remaining"])
        
        # Obtener precio
        price = None
        if self.data_stream:
            price = self.data_stream.get_current_price()
        
        if not price:
            if not hasattr(self, '_sim_price'):
                self._sim_price = 80000.0
            self._sim_price += random.uniform(-20, 20)
            price = self._sim_price
        
        # Guardar historial de precios para el chart
        if not hasattr(self, '_price_history'):
            self._price_history = []
        self._price_history.append({"time": datetime.now().isoformat(), "price": price})
        if len(self._price_history) > 300:  # Mantener últimos 5 minutos
            self._price_history = self._price_history[-300:]
        
        # Obtener features
        rsi = 50.0
        macd = 0.0
        obi = 0.0
        volatility = 0.002
        
        if self.data_stream:
            volatility = self.data_stream.get_volatility("1m", 20) or 0.002
            trade_flow = self.data_stream.calculate_trade_flow(60)
            obi = trade_flow.get("flow_imbalance", 0) or 0.0
            
            df_1m = self.data_stream.get_candles_df("1m")
            if len(df_1m) > 20:
                try:
                    import ta
                    close = df_1m["close"].astype(float)
                    rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi()
                    if len(rsi_series.dropna()) > 0:
                        rsi = float(rsi_series.iloc[-1])
                    macd_series = ta.trend.MACD(close).macd_diff()
                    if len(macd_series.dropna()) > 0:
                        macd = float(macd_series.iloc[-1])
                except:
                    pass
        
        # Enviar market_data con historial para chart
        await self.manager.broadcast({
            "type": "market_data",
            "price": price,
            "round_timer": remaining,
            "features": {
                "rsi": rsi,
                "macd": macd,
                "obi": obi,
                "volatility": volatility
            },
            "chart_data": self._price_history[-60:]  # Últimos 60 puntos para el chart
        })
        
        # Calcular stats
        total_trades = self._wins + self._losses
        winrate = (self._wins / max(1, total_trades)) * 100
        
        # Calcular Kelly Criterion
        kelly_pct = 0.0
        if total_trades >= 5:
            win_prob = self._wins / max(1, total_trades)
            kelly = win_prob - ((1 - win_prob) / 0.95)
            kelly_pct = max(0, min(100, kelly * 100))
        
        # Enviar stats
        await self.manager.broadcast({
            "type": "stats",
            "capital": 100.0 + self._cumulative_pnl,
            "pnl": self._cumulative_pnl,
            "trades": total_trades,
            "winrate": winrate,
            "wins": self._wins,
            "losses": self._losses,
            "kelly": kelly_pct,
            "streak": 0,
            "max_drawdown": 0
        })
    
    async def cleanup(self):
        """Limpia recursos."""
        await self.stop()
        if self.data_stream:
            await self.data_stream.stop()


def create_app(config: Optional[Config] = None) -> FastAPI:
    """Crea la aplicación FastAPI."""
    
    config = config or load_config()
    
    app = FastAPI(title="Vibesbot Dashboard")
    
    # Buscar directorio web en varias ubicaciones posibles
    possible_web_dirs = [
        Path(__file__).parent.parent / "web",  # Desarrollo normal
        Path.cwd() / "web",  # Directorio actual
        Path(__file__).parent / "web",  # Mismo nivel que src
    ]
    
    web_dir = None
    for d in possible_web_dirs:
        if d.exists() and (d / "templates").exists():
            web_dir = d
            logger.info(f"Found web directory at: {web_dir}")
            break
    
    if web_dir is None:
        web_dir = Path(__file__).parent.parent / "web"
        logger.warning(f"Web directory not found, using default: {web_dir}")
    
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
    
    manager = ConnectionManager()
    bot = DashboardBot(config, manager)
    
    @app.on_event("startup")
    async def startup():
        await bot.initialize()
    
    @app.on_event("shutdown")
    async def shutdown():
        await bot.cleanup()
    
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")
    
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        
        await websocket.send_json({
            "type": "status",
            "running": bot._running,
            "paused": bot._paused,
            "model_loaded": bot.predictor.is_ready if bot.predictor else False
        })
        
        try:
            while True:
                data = await websocket.receive_json()
                action = data.get("action") or data.get("command")
                
                if action == "start":
                    await bot.start()
                elif action == "stop":
                    await bot.stop()
                elif action == "pause":
                    if bot._paused:
                        bot.resume()
                    else:
                        bot.pause()
                elif action == "resume":
                    bot.resume()
                elif action == "set_mode":
                    simulation = data.get("simulation", True)
                    logger.info(f"Mode changed to: {'SIMULATION' if simulation else 'REAL'}")
                    
        except WebSocketDisconnect:
            manager.disconnect(websocket)
    
    # ═══════════════════════════════════════════════════════════
    # API Endpoints para Settings
    # ═══════════════════════════════════════════════════════════
    
    from .user_settings import get_settings_manager, TradingMode
    from .updater import get_updater
    
    @app.get("/api/settings")
    async def get_settings():
        """Obtiene la configuración actual."""
        sm = get_settings_manager()
        return sm.get_settings_for_frontend()
    
    @app.post("/api/settings/trading")
    async def update_trading_settings(request: Request):
        """Actualiza la configuración de trading."""
        data = await request.json()
        sm = get_settings_manager()
        sm.update_trading_settings(**data)
        return {"success": True, "settings": sm.settings.trading.to_dict()}
    
    @app.post("/api/settings/binance")
    async def update_binance_credentials(request: Request):
        """Actualiza las credenciales de Binance."""
        data = await request.json()
        sm = get_settings_manager()
        sm.update_binance_credentials(
            api_key=data.get("api_key", ""),
            api_secret=data.get("api_secret", ""),
            is_testnet=data.get("is_testnet", True)
        )
        return {"success": True}
    
    @app.post("/api/settings/binance/test")
    async def test_binance_connection(request: Request):
        """Prueba la conexión con Binance."""
        data = await request.json()
        sm = get_settings_manager()
        
        # Actualizar temporalmente las credenciales para la prueba
        sm.update_binance_credentials(
            api_key=data.get("api_key", ""),
            api_secret=data.get("api_secret", ""),
            is_testnet=data.get("use_testnet", True)
        )
        
        result = await sm.test_binance_connection()
        return result
    
    @app.post("/api/simulation/reset")
    async def reset_simulation():
        """Reinicia la cuenta de simulación."""
        sm = get_settings_manager()
        sm.reset_simulation(100.0)
        return {"success": True, "simulation": sm.settings.simulation.to_dict()}
    
    @app.get("/api/simulation/history")
    async def get_simulation_history():
        """Obtiene el historial de trades de simulación."""
        sm = get_settings_manager()
        return {
            "history": sm.settings.simulation.history,
            "stats": sm.settings.simulation.to_dict()
        }
    
    # ═══════════════════════════════════════════════════════════
    # API Endpoints para Auto-Update
    # ═══════════════════════════════════════════════════════════
    
    @app.get("/api/updates/check")
    async def check_for_updates():
        """Verifica si hay actualizaciones disponibles."""
        updater = get_updater()
        info = await updater.check_for_updates()
        return {
            "available": info.available,
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "release_notes": info.release_notes
        }
    
    @app.post("/api/updates/install")
    async def install_update():
        """Instala la actualización disponible."""
        updater = get_updater()
        success, message = await updater.update()
        return {"success": success, "message": message}
    
    @app.get("/api/version")
    async def get_version():
        """Obtiene la versión actual."""
        updater = get_updater()
        return {"version": updater.current_version}
    
    return app


def run_dashboard(host: str = "0.0.0.0", port: int = 8080, config_path: Optional[str] = None):
    """Inicia el servidor del dashboard."""
    setup_logger("web_server", console_output=True)
    
    config = load_config(config_path)
    app = create_app(config)
    
    logger.info(f"Starting dashboard at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_dashboard()
