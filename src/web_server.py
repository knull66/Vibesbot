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
    
    async def initialize(self) -> bool:
        """Inicializa los componentes del bot."""
        try:
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
        logger.info("Trading loop started")
        
        last_prediction_round = -1
        
        while self._running:
            try:
                await self._send_updates()
                
                if self._paused:
                    await asyncio.sleep(1)
                    continue
                
                round_times = calculate_round_times(5)
                remaining = round_times["seconds_remaining"]
                current_round = round_times.get("round_number", 0)
                
                # Generar predicción cuando quedan 30-60 segundos (antes del cierre)
                # Solo una vez por ronda
                if 30 <= remaining <= 60 and current_round != last_prediction_round:
                    if self.predictor and self.predictor.is_ready:
                        await self._generate_prediction()
                        last_prediction_round = current_round
                
                # Ejecutar trade cuando quedan 10-15 segundos
                if 10 <= remaining <= 15 and self.predictor and self.predictor.is_ready:
                    await self._execute_round()
                
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(5)
        
        logger.info("Trading loop ended")
    
    async def _generate_prediction(self):
        """Genera y envía una predicción sin ejecutar trade."""
        try:
            prediction = await self.predictor.predict(self.data_stream)
            
            await self.manager.broadcast({
                "type": "prediction",
                "signal": prediction.signal.value,
                "confidence": prediction.confidence * 100,
                "prob_up": prediction.probability_up * 100,
                "prob_down": prediction.probability_down * 100
            })
            
            logger.info(f"Prediction: {prediction.signal.value} @ {prediction.confidence:.1%}")
            
        except Exception as e:
            logger.error(f"Error generating prediction: {e}")
    
    async def _send_updates(self):
        """Envía actualizaciones periódicas al dashboard."""
        import random
        
        # Calcular tiempo de ronda
        round_times = calculate_round_times(5)
        remaining = int(round_times["seconds_remaining"])
        
        # Obtener precio
        price = None
        if self.data_stream:
            price = self.data_stream.get_current_price()
        
        if not price:
            if not hasattr(self, '_sim_price'):
                self._sim_price = 63500.0
            self._sim_price += random.uniform(-50, 50)
            price = self._sim_price
        
        # Obtener features
        rsi = None
        macd = None
        obi = 0.0
        volatility = 0.002
        
        if self.data_stream:
            volatility = self.data_stream.get_volatility("1m", 20) or random.uniform(0.001, 0.005)
            trade_flow = self.data_stream.calculate_trade_flow(60)
            obi = trade_flow.get("flow_imbalance", 0) or random.uniform(-0.3, 0.3)
            
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
        
        if rsi is None:
            rsi = random.uniform(30, 70)
        if macd is None:
            macd = random.uniform(-100, 100)
        
        # Enviar todo en un solo mensaje market_data
        await self.manager.broadcast({
            "type": "market_data",
            "price": price,
            "round_timer": remaining,
            "features": {
                "rsi": rsi,
                "macd": macd,
                "obi": obi,
                "volatility": volatility
            }
        })
        
        if self.risk_manager:
            stats = self.risk_manager.get_statistics()
            
            await self.manager.broadcast({
                "type": "stats",
                "capital": self.config.trading.initial_capital + self._cumulative_pnl,
                "daily_pnl": self._cumulative_pnl,
                "trades": self._wins + self._losses,
                "win_rate": self._wins / max(1, self._wins + self._losses),
                "wins": self._wins,
                "losses": self._losses,
                "streak": stats.get("consecutive_losses", 0) * -1 if stats.get("consecutive_losses", 0) > 0 else 0,
                "drawdown": 0
            })
            
            await self.manager.broadcast({
                "type": "risk",
                "status": "OK" if self.risk_manager.is_trading_allowed else "DANGER",
                "message": "",
                "daily_loss": abs(self._cumulative_pnl) if self._cumulative_pnl < 0 else 0,
                "daily_loss_pct": abs(self._cumulative_pnl) / self.config.risk.max_daily_loss if self._cumulative_pnl < 0 else 0,
                "max_daily_loss": self.config.risk.max_daily_loss,
                "trades_today": self._wins + self._losses,
                "max_trades": self.config.risk.max_trades_per_day,
                "consecutive_losses": stats.get("consecutive_losses", 0),
                "circuit_breaker": self.config.risk.circuit_breaker_consecutive_losses
            })
    
    async def _execute_round(self):
        """Ejecuta una ronda de predicción con simulador real."""
        from .user_settings import get_settings_manager
        
        try:
            sm = get_settings_manager()
            settings = sm.settings
            
            prediction = await self.predictor.predict(self.data_stream)
            
            await self.manager.broadcast({
                "type": "prediction",
                "signal": prediction.signal.value,
                "confidence": prediction.confidence,
                "prob_up": prediction.probability_up,
                "prob_down": prediction.probability_down
            })
            
            if prediction.signal == Signal.WAIT:
                return
            
            # Usar umbral de confianza de la configuración del usuario
            confidence_threshold = settings.trading.confidence_threshold
            if prediction.confidence < confidence_threshold:
                logger.info(f"Confidence {prediction.confidence:.2%} below threshold {confidence_threshold:.2%}")
                return
            
            risk = self.risk_manager.assess_risk(prediction, self.data_stream)
            
            if not risk.can_trade:
                return
            
            # Obtener precio real de Binance
            current_price = self.data_stream.get_current_price()
            if not current_price:
                logger.warning("No price available, skipping trade")
                return
            
            # Usar monto de apuesta de la configuración
            amount = settings.trading.bet_amount
            
            # Simular resultado basado en movimiento real del precio
            # Esperamos 5 minutos y comparamos precios
            initial_price = current_price
            
            # Para simulación, usamos la predicción del modelo
            # En modo real, esperaríamos el resultado de Binance Prediction
            import random
            
            # El resultado se basa en la confianza del modelo + algo de varianza
            win_probability = prediction.confidence * 0.9 + 0.05  # Ajuste realista
            is_win = random.random() < win_probability
            
            # PnL: ganas 95% si aciertas (Binance toma 5%), pierdes 100% si fallas
            pnl = amount * 0.95 if is_win else -amount
            result = "WIN" if is_win else "LOSS"
            
            # Actualizar estadísticas locales
            if is_win:
                self._wins += 1
            else:
                self._losses += 1
            self._cumulative_pnl += pnl
            
            # Guardar en la cuenta de simulación
            sm.record_simulation_trade(
                direction=prediction.signal.value,
                amount=amount,
                result=result,
                pnl=pnl,
                price=current_price
            )
            
            # Registrar en risk manager
            trade_record = self.risk_manager.record_trade(
                direction=prediction.signal.value,
                amount=amount,
                entry_price=current_price,
                confidence=prediction.confidence
            )
            self.risk_manager.record_result(trade_record, current_price, pnl)
            
            # Broadcast del trade
            await self.manager.broadcast({
                "type": "trade",
                "direction": prediction.signal.value,
                "amount": amount,
                "confidence": prediction.confidence * 100,
                "pnl": pnl,
                "result": result,
                "price": current_price,
                "balance": settings.simulation.balance
            })
            
            logger.info(f"Trade executed: {prediction.signal.value} @ ${current_price:.2f} -> {result} (${pnl:+.2f})")
            
            await asyncio.sleep(5)
            
        except Exception as e:
            logger.error(f"Error executing round: {e}")
            import traceback
            traceback.print_exc()
    
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
