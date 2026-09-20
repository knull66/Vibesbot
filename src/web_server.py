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
        self._time_offset = 0.0
        
        # Última predicción
        self._last_prediction = None
        self._last_prediction_confidence = 0.5
        
        # Estadísticas avanzadas
        self._equity_history = [100.0]  # Historial de capital
        self._streak = 0  # Racha actual (positivo = wins, negativo = losses)
        self._best_streak = 0
        self._worst_streak = 0
        self._max_equity = 100.0
        self._max_drawdown = 0.0
        
        # Cargar datos guardados
        self._load_saved_data()
    
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
        """Genera predicción usando múltiples estrategias."""
        import random
        
        try:
            signal = "WAIT"
            confidence = 0.5
            prob_up = 0.5
            prob_down = 0.5
            strategy_used = "none"
            
            # Intentar usar el modelo ML real
            if self.predictor and self.predictor.is_ready:
                prediction = await self.predictor.predict(self.data_stream)
                signal = prediction.signal.value
                confidence = prediction.confidence
                prob_up = prediction.probability_up
                prob_down = prediction.probability_down
                strategy_used = "ML Model"
            elif self.data_stream:
                df = self.data_stream.get_candles_df("1m")
                if len(df) > 26:
                    try:
                        import ta
                        close = df["close"].astype(float)
                        high = df["high"].astype(float)
                        low = df["low"].astype(float)
                        
                        # === ESTRATEGIA 1: RSI ===
                        rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
                        rsi_signal = 0  # -1 DOWN, 0 neutral, 1 UP
                        if rsi < 30:
                            rsi_signal = 1  # Oversold = UP
                        elif rsi > 70:
                            rsi_signal = -1  # Overbought = DOWN
                        
                        # === ESTRATEGIA 2: MACD ===
                        macd = ta.trend.MACD(close)
                        macd_line = macd.macd().iloc[-1]
                        macd_signal_line = macd.macd_signal().iloc[-1]
                        macd_signal = 1 if macd_line > macd_signal_line else -1
                        
                        # === ESTRATEGIA 3: Bollinger Bands ===
                        bb = ta.volatility.BollingerBands(close, window=20)
                        bb_high = bb.bollinger_hband().iloc[-1]
                        bb_low = bb.bollinger_lband().iloc[-1]
                        current_price = close.iloc[-1]
                        bb_signal = 0
                        if current_price < bb_low:
                            bb_signal = 1  # Below lower band = UP
                        elif current_price > bb_high:
                            bb_signal = -1  # Above upper band = DOWN
                        
                        # === ESTRATEGIA 4: Momentum ===
                        momentum = close.iloc[-1] - close.iloc[-5]
                        mom_signal = 1 if momentum > 0 else -1
                        
                        # === COMBINAR SEÑALES ===
                        # Pesos: RSI=2, MACD=2, BB=1, Momentum=1
                        total_signal = (rsi_signal * 2) + (macd_signal * 2) + (bb_signal * 1) + (mom_signal * 1)
                        
                        # Determinar señal final
                        if total_signal >= 3:
                            signal = "UP"
                            confidence = 0.55 + min(0.15, abs(total_signal) * 0.02)
                            strategy_used = "Multi-strategy (RSI+MACD+BB)"
                        elif total_signal <= -3:
                            signal = "DOWN"
                            confidence = 0.55 + min(0.15, abs(total_signal) * 0.02)
                            strategy_used = "Multi-strategy (RSI+MACD+BB)"
                        elif rsi_signal != 0:
                            signal = "UP" if rsi_signal > 0 else "DOWN"
                            confidence = 0.52 + random.uniform(0, 0.10)
                            strategy_used = f"RSI={rsi:.0f}"
                        else:
                            signal = "UP" if total_signal > 0 else "DOWN"
                            confidence = 0.50 + random.uniform(0, 0.08)
                            strategy_used = "Weak signal"
                        
                        prob_up = confidence if signal == "UP" else 1 - confidence
                        prob_down = 1 - prob_up
                        
                    except Exception as e:
                        logger.error(f"Strategy error: {e}")
            
            # Guardar predicción para el trade
            self._last_prediction = signal
            self._last_prediction_confidence = confidence
            
            # Obtener precio actual como "Price to Beat"
            price_to_beat = 80000.0
            if self.data_stream:
                price_to_beat = self.data_stream.get_current_price() or price_to_beat
            self._price_to_beat = price_to_beat
            
            await self.manager.broadcast({
                "type": "signal",
                "signal": signal,
                "confidence": confidence,
                "prob_up": prob_up,
                "prob_down": prob_down,
                "price_to_beat": price_to_beat
            })
            
            await self.manager.broadcast({
                "type": "log",
                "message": f"SIGNAL: {signal} ({confidence*100:.1f}%) | {strategy_used}",
                "level": "prediction"
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
                    "message": "WAITING FOR SIGNAL",
                    "level": "info"
                })
                return
            
            # Solo tradear si hay suficiente confianza (>50%)
            if confidence < 0.50:
                await self.manager.broadcast({
                    "type": "log", 
                    "message": f"SKIP: Confidence too low ({confidence*100:.0f}%)",
                    "level": "info"
                })
                return
            
            # Obtener precio actual
            current_price = 80000.0
            if self.data_stream:
                current_price = self.data_stream.get_current_price() or current_price
            
            # Guardar precio de entrada
            entry_price = current_price
            
            # Obtener amount de los settings
            from .user_settings import get_settings_manager
            sm = get_settings_manager()
            amount = sm.settings.trading.bet_amount
            
            # Esperar 3 segundos y ver el nuevo precio para determinar resultado
            await asyncio.sleep(3)
            
            new_price = current_price
            if self.data_stream:
                new_price = self.data_stream.get_current_price() or current_price
            
            # Determinar resultado basado en movimiento real del precio
            price_diff = new_price - entry_price
            price_moved_up = price_diff > 0
            price_moved_down = price_diff < 0
            price_unchanged = abs(price_diff) < 0.01
            
            # WIN si: predijimos UP y el precio subió, o predijimos DOWN y el precio bajó
            if price_unchanged:
                # Precio sin cambio significativo - usar probabilidad basada en confianza
                is_win = random.random() < (confidence * 0.7 + 0.15)
                actual_direction = "FLAT"
            else:
                actual_direction = "UP" if price_moved_up else "DOWN"
                is_win = (signal == actual_direction)
            
            pnl = amount * 0.95 if is_win else -amount
            result = "WIN" if is_win else "LOSS"
            
            # Actualizar estadísticas básicas
            if is_win:
                self._wins += 1
                self._streak = max(1, self._streak + 1) if self._streak >= 0 else 1
            else:
                self._losses += 1
                self._streak = min(-1, self._streak - 1) if self._streak <= 0 else -1
            
            self._cumulative_pnl += pnl
            
            # Actualizar estadísticas avanzadas
            self._best_streak = max(self._best_streak, self._streak)
            self._worst_streak = min(self._worst_streak, self._streak)
            
            current_equity = 100.0 + self._cumulative_pnl
            self._equity_history.append(current_equity)
            self._max_equity = max(self._max_equity, current_equity)
            
            # Calcular drawdown
            if self._max_equity > 0:
                current_drawdown = ((self._max_equity - current_equity) / self._max_equity) * 100
                self._max_drawdown = max(self._max_drawdown, current_drawdown)
            
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
            abs_diff = abs(new_price - entry_price)
            
            # Explicación clara
            if actual_direction == "FLAT":
                explanation = f"Price stable"
            elif actual_direction == signal:
                explanation = f"Price {actual_direction} [correct]"
            else:
                explanation = f"Price {actual_direction} [wrong]"
            
            log_level = "win" if is_win else "loss"
            
            await self.manager.broadcast({
                "type": "log",
                "message": f"TRADE {signal} | ${entry_price:,.2f} -> ${new_price:,.2f} | {result}",
                "level": log_level
            })
            
            await self.manager.broadcast({
                "type": "log",
                "message": f"{explanation} | P&L: ${pnl:+.2f}",
                "level": log_level
            })
            
            # Actualizar stats completas
            total_trades = self._wins + self._losses
            winrate = (self._wins / max(1, total_trades)) * 100
            
            # Kelly Criterion
            if total_trades >= 5:
                p = self._wins / total_trades
                b = 0.95  # odds (95% payout)
                kelly_pct = max(0, ((p * b - (1 - p)) / b) * 100)
            else:
                kelly_pct = 0
            
            # Profit factor
            total_wins_amount = self._wins * 0.95
            total_losses_amount = self._losses * 1.0
            profit_factor = total_wins_amount / max(0.01, total_losses_amount)
            
            await self.manager.broadcast({
                "type": "stats",
                "capital": 100.0 + self._cumulative_pnl,
                "pnl": self._cumulative_pnl,
                "trades": total_trades,
                "winrate": winrate,
                "wins": self._wins,
                "losses": self._losses,
                "streak": self._streak,
                "best_streak": self._best_streak,
                "worst_streak": self._worst_streak,
                "kelly": kelly_pct,
                "profit_factor": profit_factor,
                "max_drawdown": self._max_drawdown,
                "equity_history": self._equity_history[-50:]
            })
            
            logger.info(f"Trade: {signal} @ ${entry_price:.2f} -> ${new_price:.2f} = {result} (${pnl:+.2f})")
            
            # Registrar en SimulationAccount
            from .user_settings import get_settings_manager
            sm = get_settings_manager()
            sm.record_simulation_trade(
                direction=signal,
                amount=amount,
                result=result,
                pnl=pnl,
                price=entry_price
            )
            
            # Guardar datos
            self._save_data()
            
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
        
        # Obtener features técnicos
        rsi = 50.0
        macd = 0.0
        bb_position = "MID"
        momentum = 0.0
        
        if self.data_stream:
            df_1m = self.data_stream.get_candles_df("1m")
            if len(df_1m) > 26:
                try:
                    import ta
                    close = df_1m["close"].astype(float)
                    current_price = close.iloc[-1]
                    
                    # RSI
                    rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi()
                    if len(rsi_series.dropna()) > 0:
                        rsi = float(rsi_series.iloc[-1])
                    
                    # MACD
                    macd_indicator = ta.trend.MACD(close)
                    macd_diff = macd_indicator.macd_diff()
                    if len(macd_diff.dropna()) > 0:
                        macd = float(macd_diff.iloc[-1])
                    
                    # Bollinger Bands
                    bb = ta.volatility.BollingerBands(close, window=20)
                    bb_high = bb.bollinger_hband().iloc[-1]
                    bb_low = bb.bollinger_lband().iloc[-1]
                    if current_price > bb_high:
                        bb_position = "UPPER"
                    elif current_price < bb_low:
                        bb_position = "LOWER"
                    else:
                        bb_position = "MID"
                    
                    # Momentum
                    if len(close) >= 5:
                        momentum = float(close.iloc[-1] - close.iloc[-5])
                except Exception as e:
                    logger.debug(f"Error calculating features: {e}")
        
        # Enviar market data
        await self.manager.broadcast({
            "type": "market",
            "price": price,
            "timer": remaining,
            "features": {
                "rsi": rsi,
                "macd": macd,
                "bb": bb_position,
                "momentum": momentum
            }
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
        
        # Calcular profit factor
        total_wins_amount = self._wins * 0.95
        total_losses_amount = self._losses * 1.0
        profit_factor = total_wins_amount / max(0.01, total_losses_amount)
        
        # Enviar stats completas
        await self.manager.broadcast({
            "type": "stats",
            "capital": 100.0 + self._cumulative_pnl,
            "pnl": self._cumulative_pnl,
            "trades": total_trades,
            "winrate": winrate,
            "wins": self._wins,
            "losses": self._losses,
            "kelly": kelly_pct,
            "streak": self._streak,
            "best_streak": self._best_streak,
            "worst_streak": self._worst_streak,
            "max_drawdown": self._max_drawdown,
            "profit_factor": profit_factor,
            "equity_history": self._equity_history[-50:]  # Últimos 50 para gráfico
        })
    
    def _load_saved_data(self):
        """Carga datos guardados de sesiones anteriores."""
        import json
        data_file = Path(__file__).parent.parent / "trading_data.json"
        
        if data_file.exists():
            try:
                with open(data_file, 'r') as f:
                    data = json.load(f)
                
                self._trades = data.get('trades', [])
                self._cumulative_pnl = data.get('pnl', 0.0)
                self._wins = data.get('wins', 0)
                self._losses = data.get('losses', 0)
                self._equity_history = data.get('equity_history', [100.0])
                self._best_streak = data.get('best_streak', 0)
                self._worst_streak = data.get('worst_streak', 0)
                self._max_drawdown = data.get('max_drawdown', 0.0)
                
                logger.info(f"Loaded saved data: {self._wins}W/{self._losses}L, PnL: ${self._cumulative_pnl:.2f}")
            except Exception as e:
                logger.error(f"Error loading saved data: {e}")
    
    def _save_data(self):
        """Guarda datos para persistencia."""
        import json
        data_file = Path(__file__).parent.parent / "trading_data.json"
        
        try:
            data = {
                'trades': self._trades[-100:],  # Últimos 100 trades
                'pnl': self._cumulative_pnl,
                'wins': self._wins,
                'losses': self._losses,
                'equity_history': self._equity_history[-500:],  # Últimos 500 puntos
                'best_streak': self._best_streak,
                'worst_streak': self._worst_streak,
                'max_drawdown': self._max_drawdown,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    async def cleanup(self):
        """Limpia recursos."""
        self._save_data()  # Guardar antes de cerrar
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
        
        # También reiniciar contadores del bot
        bot._wins = 0
        bot._losses = 0
        bot._cumulative_pnl = 0.0
        bot._trades = []
        bot._equity_history = [100.0]
        bot._streak = 0
        bot._best_streak = 0
        bot._worst_streak = 0
        bot._max_equity = 100.0
        bot._max_drawdown = 0.0
        bot._save_data()
        
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
        from .updater import get_updater, Updater
        
        # Forzar nueva instancia para evitar cache
        updater = Updater()
        info = await updater.check_for_updates()
        
        logger.info(f"Update check: current={info.current_version}, latest={info.latest_version}, available={info.available}")
        
        return {
            "available": info.available,
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "release_notes": info.release_notes,
            "download_url": info.download_url
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
