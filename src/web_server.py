"""
Servidor web para el dashboard de Vibesbot.

Proporciona:
- Dashboard visual en tiempo real
- WebSocket para actualizaciones
- Control del bot (start/stop/pause)
"""
import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .config import Config, load_config
from .data_stream import DataStream
from .predictor import Predictor, Signal, ModelType
from .risk_manager import RiskManager, RiskStatus
from .utils.logger import setup_logger, get_logger
from .utils.helpers import calculate_time_to_next_round, calculate_round_times
from .auth import COOKIE_NAME, SESSION_DAYS, get_auth
from .companion import get_companion, is_loopback


logger = get_logger("web_server")


class ConnectionManager:
    """Gestiona conexiones WebSocket activas, con envío global o por sesión."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.session_sockets: Dict[str, Set[WebSocket]] = {}
        self.socket_session: Dict[WebSocket, str] = {}
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")
    
    def bind_session(self, websocket: WebSocket, session_id: str):
        old = self.socket_session.get(websocket)
        if old and old in self.session_sockets:
            self.session_sockets[old].discard(websocket)
        self.socket_session[websocket] = session_id
        self.session_sockets.setdefault(session_id, set()).add(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        session_id = self.socket_session.pop(websocket, None)
        if session_id and session_id in self.session_sockets:
            self.session_sockets[session_id].discard(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")
    
    async def send_to(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            self.disconnect(websocket)
    
    async def send_to_session(self, session_id: str, message: dict):
        sockets = list(self.session_sockets.get(session_id, set()))
        for connection in sockets:
            await self.send_to(connection, message)
    
    async def broadcast(self, message: dict):
        """Envía mensaje a todos los clientes (datos de mercado)."""
        if not self.active_connections:
            return
        
        data = json.dumps(message)
        disconnected = set()
        
        for connection in list(self.active_connections):
            try:
                await connection.send_text(data)
            except Exception:
                disconnected.add(connection)
        
        for conn in disconnected:
            self.disconnect(conn)


@dataclass
class ClientSession:
    """Estado de trading independiente por dispositivo/navegador."""
    
    session_id: str
    running: bool = False
    paused: bool = False
    simulation: bool = True
    wins: int = 0
    losses: int = 0
    cumulative_pnl: float = 0.0
    trades: List[dict] = field(default_factory=list)
    equity_history: List[float] = field(default_factory=lambda: [100.0])
    streak: int = 0
    best_streak: int = 0
    worst_streak: int = 0
    max_equity: float = 100.0
    max_drawdown: float = 0.0
    initial_capital: float = 100.0
    
    def reset(self, capital: float = 100.0):
        self.wins = 0
        self.losses = 0
        self.cumulative_pnl = 0.0
        self.trades = []
        self.equity_history = [capital]
        self.streak = 0
        self.best_streak = 0
        self.worst_streak = 0
        self.max_equity = capital
        self.max_drawdown = 0.0
        self.initial_capital = capital
    
    def status_payload(self, model_loaded: bool = False) -> dict:
        return {
            "type": "status",
            "running": self.running,
            "paused": self.paused,
            "model_loaded": model_loaded,
            "session_id": self.session_id,
            "simulation": self.simulation,
        }
    
    def stats_payload(self) -> dict:
        total = self.wins + self.losses
        winrate = (self.wins / max(1, total)) * 100
        kelly_pct = 0.0
        if total >= 5:
            p = self.wins / total
            kelly_pct = max(0, min(100, ((p * 0.95 - (1 - p)) / 0.95) * 100))
        profit_factor = (self.wins * 0.95) / max(0.01, self.losses * 1.0)
        return {
            "type": "stats",
            "capital": self.initial_capital + self.cumulative_pnl,
            "pnl": self.cumulative_pnl,
            "trades": total,
            "winrate": winrate,
            "wins": self.wins,
            "losses": self.losses,
            "kelly": kelly_pct,
            "streak": self.streak,
            "best_streak": self.best_streak,
            "worst_streak": self.worst_streak,
            "max_drawdown": self.max_drawdown,
            "profit_factor": profit_factor,
            "equity_history": self.equity_history[-50:],
        }


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
        self._engine_task: Optional[asyncio.Task] = None
        
        self.sessions: Dict[str, ClientSession] = {}
        
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
            self._engine_task = asyncio.create_task(self._session_engine())
            
            return True
            
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            return False
    
    def get_session(self, session_id: str) -> ClientSession:
        if session_id not in self.sessions:
            self.sessions[session_id] = ClientSession(session_id=session_id)
            self._load_session(self.sessions[session_id])
        return self.sessions[session_id]
    
    def attach_client(self, websocket: WebSocket, session_id: str) -> ClientSession:
        session_id = (session_id or "").strip() or str(uuid.uuid4())
        session = self.get_session(session_id)
        self.manager.bind_session(websocket, session.session_id)
        logger.info(f"Client bound to session {session.session_id[:8]}")
        return session
    
    async def _data_loop(self):
        """Loop que siempre envía datos de mercado, incluso sin trading."""
        logger.info("Data loop started - sending market updates")
        
        while True:
            try:
                await self._send_market()
                for session in list(self.sessions.values()):
                    await self.manager.send_to_session(session.session_id, session.stats_payload())
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in data loop: {e}")
                await asyncio.sleep(2)
    
    async def start_session(self, session: ClientSession):
        """Inicia el trading solo para esta sesión."""
        session.running = True
        session.paused = False
        await self.manager.send_to_session(session.session_id, session.status_payload(
            self.predictor.is_ready if self.predictor else False
        ))
        await self.manager.send_to_session(session.session_id, {
            "type": "log",
            "message": "Bot started - waiting for next prediction window",
            "level": "info"
        })
    
    async def stop_session(self, session: ClientSession):
        session.running = False
        session.paused = False
        await self.manager.send_to_session(session.session_id, session.status_payload(
            self.predictor.is_ready if self.predictor else False
        ))
        await self.manager.send_to_session(session.session_id, {
            "type": "log",
            "message": "Bot stopped",
            "level": "info"
        })
    
    async def pause_session(self, session: ClientSession):
        session.paused = not session.paused
        await self.manager.send_to_session(session.session_id, session.status_payload(
            self.predictor.is_ready if self.predictor else False
        ))
        await self.manager.send_to_session(session.session_id, {
            "type": "log",
            "message": "Bot paused" if session.paused else "Bot resumed",
            "level": "info"
        })
    
    async def start(self):
        """Compatibilidad: inicia todas las sesiones no es el flujo nuevo."""
        return
    
    async def stop(self):
        """Detiene todas las sesiones (shutdown)."""
        self._running = False
        for session in self.sessions.values():
            session.running = False
            session.paused = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    def pause(self):
        return
    
    def resume(self):
        return
    
    async def _session_engine(self):
        """Motor único: predicción de mercado + trades por sesión activa."""
        logger.info("Session engine started")
        last_prediction_round = -1
        last_trade_round = -1
        
        while True:
            try:
                active = [s for s in self.sessions.values() if s.running and not s.paused]
                
                if active:
                    round_times = calculate_round_times(5, self._time_offset)
                    remaining = round_times["seconds_remaining"]
                    current_round = round_times.get("round_number", 0)
                    
                    if 60 <= remaining <= 90 and current_round != last_prediction_round:
                        await self._generate_prediction(active)
                        last_prediction_round = current_round
                    
                    if 10 <= remaining <= 20 and current_round != last_trade_round:
                        await asyncio.gather(*[self._execute_trade(session) for session in active])
                        self._last_prediction = None
                        last_trade_round = current_round
                
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session engine: {e}")
                await asyncio.sleep(2)
    
    async def _run_loop(self):
        return
    
    async def _generate_prediction(self, sessions: Optional[List[ClientSession]] = None):
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
            
            await self._emit_sessions(sessions, {
                "type": "signal",
                "signal": signal,
                "confidence": confidence,
                "prob_up": prob_up,
                "prob_down": prob_down,
                "price_to_beat": price_to_beat
            })
            
            await self._emit_sessions(sessions, {
                "type": "log",
                "message": f"SIGNAL: {signal} ({confidence*100:.1f}%) | {strategy_used}",
                "level": "prediction"
            })
            
            logger.info(f"Prediction: {signal} @ {confidence:.1%}")
            
        except Exception as e:
            logger.error(f"Error generating prediction: {e}")
    
    async def _emit_sessions(self, sessions: Optional[List[ClientSession]], message: dict):
        targets = sessions if sessions is not None else list(self.sessions.values())
        for session in targets:
            await self.manager.send_to_session(session.session_id, message)
    
    async def _execute_trade(self, session: Optional[ClientSession] = None):
        """Ejecuta un trade simulado basado en la última predicción."""
        import random
        from datetime import datetime
        
        if session is None:
            return
        
        try:
            # Usar la predicción guardada
            signal = self._last_prediction
            confidence = self._last_prediction_confidence
            
            # Si no hay predicción válida, saltar
            if not signal or signal == "WAIT":
                await self.manager.send_to_session(session.session_id, {
                    "type": "log", 
                    "message": "WAITING FOR SIGNAL",
                    "level": "info"
                })
                return
            
            # Solo tradear si hay suficiente confianza (>50%)
            if confidence < 0.50:
                await self.manager.send_to_session(session.session_id, {
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
                session.wins += 1
                session.streak = max(1, session.streak + 1) if session.streak >= 0 else 1
            else:
                session.losses += 1
                session.streak = min(-1, session.streak - 1) if session.streak <= 0 else -1
            
            session.cumulative_pnl += pnl
            
            # Actualizar estadísticas avanzadas
            session.best_streak = max(session.best_streak, session.streak)
            session.worst_streak = min(session.worst_streak, session.streak)
            
            current_equity = session.initial_capital + session.cumulative_pnl
            session.equity_history.append(current_equity)
            session.max_equity = max(session.max_equity, current_equity)
            
            # Calcular drawdown
            if session.max_equity > 0:
                current_drawdown = ((session.max_equity - current_equity) / session.max_equity) * 100
                session.max_drawdown = max(session.max_drawdown, current_drawdown)
            
            session.trades.append({
                "timestamp": datetime.now().isoformat(),
                "direction": signal,
                "amount": amount,
                "entry_price": entry_price,
                "exit_price": new_price,
                "pnl": pnl,
                "result": result,
            })
            
            # Calcular cambio de precio
            price_change = new_price - entry_price
            price_direction = "↑" if price_change > 0 else "↓" if price_change < 0 else "→"
            
            # Enviar trade al frontend de ESTA sesión
            await self.manager.send_to_session(session.session_id, {
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
            
            await self.manager.send_to_session(session.session_id, {
                "type": "log",
                "message": f"TRADE {signal} | ${entry_price:,.2f} -> ${new_price:,.2f} | {result}",
                "level": log_level
            })
            
            await self.manager.send_to_session(session.session_id, {
                "type": "log",
                "message": f"{explanation} | P&L: ${pnl:+.2f}",
                "level": log_level
            })
            
            await self.manager.send_to_session(session.session_id, session.stats_payload())
            
            logger.info(f"[{session.session_id[:8]}] Trade: {signal} @ ${entry_price:.2f} -> ${new_price:.2f} = {result} (${pnl:+.2f})")
            
            self._save_session(session)
            
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            import traceback
            traceback.print_exc()
    
    async def _send_market(self):
        """Envía datos de mercado a todos los clientes (compartido)."""
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
        
        # Enviar market data a TODOS (el precio es el mismo)
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
    
    def _sessions_dir(self) -> Path:
        path = Path(__file__).parent.parent / "data" / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def _load_session(self, session: ClientSession):
        data_file = self._sessions_dir() / f"{session.session_id}.json"
        if not data_file.exists():
            return
        try:
            with open(data_file, "r") as f:
                data = json.load(f)
            session.wins = data.get("wins", 0)
            session.losses = data.get("losses", 0)
            session.cumulative_pnl = data.get("pnl", 0.0)
            session.trades = data.get("trades", [])
            session.equity_history = data.get("equity_history", [100.0])
            session.best_streak = data.get("best_streak", 0)
            session.worst_streak = data.get("worst_streak", 0)
            session.max_drawdown = data.get("max_drawdown", 0.0)
            session.max_equity = data.get("max_equity", 100.0)
            session.initial_capital = data.get("initial_capital", 100.0)
        except Exception as e:
            logger.error(f"Error loading session {session.session_id[:8]}: {e}")
    
    def _save_session(self, session: ClientSession):
        data_file = self._sessions_dir() / f"{session.session_id}.json"
        try:
            with open(data_file, "w") as f:
                json.dump({
                    "wins": session.wins,
                    "losses": session.losses,
                    "pnl": session.cumulative_pnl,
                    "trades": session.trades[-100:],
                    "equity_history": session.equity_history[-500:],
                    "best_streak": session.best_streak,
                    "worst_streak": session.worst_streak,
                    "max_drawdown": session.max_drawdown,
                    "max_equity": session.max_equity,
                    "initial_capital": session.initial_capital,
                    "last_updated": datetime.now().isoformat(),
                }, f)
        except Exception as e:
            logger.error(f"Error saving session {session.session_id[:8]}: {e}")
    
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
        for session in self.sessions.values():
            self._save_session(session)
        self._save_data()
        await self.stop()
        if self._engine_task:
            self._engine_task.cancel()
        if self._data_task:
            self._data_task.cancel()
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
    auth = get_auth()
    companion = get_companion()
    public_exact = {
        "/login",
        "/logout",
        "/companion",
        "/api/auth/status",
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/logout",
        "/api/companion/status",
        "/api/companion/pair",
    }

    def _client_host(request: Request) -> str:
        if request.client:
            return request.client.host or ""
        return ""

    def _is_local(request: Request) -> bool:
        return is_loopback(_client_host(request))

    def _set_session_cookie(request: Request, response, token: str, days: int = SESSION_DAYS):
        forwarded = request.headers.get("x-forwarded-proto", request.url.scheme)
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="lax",
            secure=str(forwarded).split(",")[0].strip() == "https",
            max_age=days * 24 * 3600,
            path="/",
        )

    def _clear_session_cookie(response):
        response.delete_cookie(COOKIE_NAME, path="/")

    def _user_from_request(request: Request):
        return auth.user_from_cookies(request.cookies)

    def _is_companion(request: Request) -> bool:
        session = auth.session_from_cookies(request.cookies)
        if session and session.companion:
            return True
        return not _is_local(request)

    def _native_owner(request: Request):
        user = getattr(request.state, "user", None)
        if not user or not user.is_owner or getattr(request.state, "is_companion", False):
            return None
        return user

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        path = request.url.path
        if path.startswith("/static") or path in public_exact:
            if path in ("/api/auth/login", "/api/auth/register") and not _is_local(request):
                return JSONResponse(
                    {"success": False, "error": "Accounts can only be created on the Mac app"},
                    status_code=403,
                )
            return await call_next(request)

        local = _is_local(request)
        user = _user_from_request(request)
        session = auth.session_from_cookies(request.cookies)

        if not local:
            if not companion.enabled:
                if path.startswith("/api/"):
                    return JSONResponse({"error": "companion_disabled"}, status_code=403)
                return RedirectResponse("/companion", status_code=302)
            if not user or not session or not session.companion:
                if path.startswith("/api/"):
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
                return RedirectResponse("/companion", status_code=302)
        elif not user:
            if path.startswith("/api/") or path.startswith("/ws"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse("/login", status_code=302)

        request.state.user = user
        request.state.is_companion = bool(session and session.companion)
        return await call_next(request)
    
    @app.on_event("startup")
    async def startup():
        await bot.initialize()
    
    @app.on_event("shutdown")
    async def shutdown():
        await bot.cleanup()

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if not _is_local(request):
            return RedirectResponse("/companion", status_code=302)
        if _user_from_request(request):
            return RedirectResponse("/", status_code=302)
        return templates.TemplateResponse(request, "login.html")

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            target = "/login" if _is_local(request) else "/companion"
            return RedirectResponse(target, status_code=302)
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    @app.get("/companion", response_class=HTMLResponse)
    async def companion_page(request: Request):
        if _is_local(request):
            return RedirectResponse("/login" if not _user_from_request(request) else "/", status_code=302)
        session = auth.session_from_cookies(request.cookies)
        if session and session.companion and auth.user_from_token(session.token):
            return RedirectResponse("/", status_code=302)
        return templates.TemplateResponse(request, "companion.html")

    @app.get("/api/companion/status")
    async def companion_status(request: Request):
        return {
            "is_local": _is_local(request),
            "setup_required": not auth.has_users(),
            **companion.public_status(),
        }

    @app.get("/api/companion/info")
    async def companion_info(request: Request):
        if not _native_owner(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return companion.info(port=8080)

    @app.post("/api/companion/enable")
    async def companion_enable(request: Request):
        if not _native_owner(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        data = await request.json()
        companion.set_enabled(bool(data.get("enabled", False)))
        return {"success": True, **companion.info(port=8080)}

    @app.post("/api/companion/pin")
    async def companion_pin(request: Request):
        if not _native_owner(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        companion.rotate_pin()
        return {"success": True, **companion.info(port=8080)}

    @app.post("/api/companion/pair")
    async def companion_pair(request: Request):
        if _is_local(request):
            return JSONResponse({"success": False, "error": "Pairing is only for the phone"}, status_code=400)
        if not auth.has_users():
            return JSONResponse({"success": False, "error": "Set up Vibesbot on your Mac first"}, status_code=400)
        data = await request.json()
        ok, error = companion.verify_pin(data.get("pin", ""))
        if not ok:
            return JSONResponse({"success": False, "error": error}, status_code=401)
        token, user, login_error = auth.login_companion()
        if login_error or not token or not user:
            return JSONResponse({"success": False, "error": login_error or "Pairing failed"}, status_code=400)
        response = JSONResponse({"success": True, "user": user.public_dict(), "companion": True})
        _set_session_cookie(request, response, token, days=1)
        return response

    @app.get("/logout")
    async def logout_page(request: Request):
        auth.logout(request.cookies.get(COOKIE_NAME))
        response = RedirectResponse("/login", status_code=302)
        _clear_session_cookie(response)
        return response

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        return {**auth.status(), "is_local": _is_local(request)}

    @app.get("/api/auth/me")
    async def auth_me(request: Request):
        user = _user_from_request(request)
        if not user:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        session = auth.session_from_cookies(request.cookies)
        return {
            "success": True,
            "user": user.public_dict(),
            "companion": bool(session and session.companion),
            "is_local": _is_local(request),
            **auth.status(),
        }

    @app.post("/api/auth/register")
    async def auth_register(request: Request):
        data = await request.json()
        user, error = auth.register(
            data.get("username", ""),
            data.get("password", ""),
            data.get("invite_code", ""),
        )
        if error or user is None:
            return JSONResponse({"success": False, "error": error}, status_code=400)
        token, _, login_error = auth.login(user.username, data.get("password", ""))
        if login_error or not token:
            return JSONResponse({"success": False, "error": login_error or "Login failed"}, status_code=400)
        response = JSONResponse({"success": True, "user": user.public_dict()})
        _set_session_cookie(request, response, token)
        return response

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        data = await request.json()
        token, user, error = auth.login(data.get("username", ""), data.get("password", ""))
        if error or not token or not user:
            return JSONResponse({"success": False, "error": error}, status_code=401)
        response = JSONResponse({"success": True, "user": user.public_dict()})
        _set_session_cookie(request, response, token)
        return response

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        auth.logout(request.cookies.get(COOKIE_NAME))
        response = JSONResponse({"success": True})
        _clear_session_cookie(response)
        return response

    @app.get("/api/auth/users")
    async def auth_users(request: Request):
        user = _native_owner(request)
        if not user:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return {"users": auth.list_users(), "invites": auth.invites, **auth.status()}

    @app.post("/api/auth/invite")
    async def auth_invite(request: Request):
        user = _native_owner(request)
        if not user:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        code, error = auth.create_invite(user)
        if error:
            return JSONResponse({"success": False, "error": error}, status_code=403)
        return {"success": True, "code": code, "invites": auth.invites}

    @app.post("/api/auth/registration")
    async def auth_registration(request: Request):
        user = _native_owner(request)
        if not user:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        data = await request.json()
        error = auth.set_open_registration(user, bool(data.get("enabled", False)))
        if error:
            return JSONResponse({"success": False, "error": error}, status_code=403)
        return {"success": True, **auth.status()}

    @app.post("/api/auth/password")
    async def auth_password(request: Request):
        user = getattr(request.state, "user", None)
        if not user or getattr(request.state, "is_companion", False):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        data = await request.json()
        error = auth.change_password(user, data.get("current", ""), data.get("new_password", ""))
        if error:
            return JSONResponse({"success": False, "error": error}, status_code=400)
        return {"success": True}

    @app.post("/api/auth/users/delete")
    async def auth_delete_user(request: Request):
        user = _native_owner(request)
        if not user:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        data = await request.json()
        error = auth.delete_user(user, data.get("user_id", ""))
        if error:
            return JSONResponse({"success": False, "error": error}, status_code=400)
        return {"success": True, "users": auth.list_users()}
    
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")
    
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        user = auth.user_from_cookies(websocket.cookies)
        ws_auth = auth.session_from_cookies(websocket.cookies)
        is_companion = bool(ws_auth and ws_auth.companion)
        if not user:
            try:
                await websocket.send_text(json.dumps({"type": "error", "message": "unauthorized"}))
            except Exception:
                pass
            await websocket.close(code=4401)
            return
        if is_companion and not companion.enabled:
            await websocket.close(code=4401)
            return

        manager.active_connections.add(websocket)
        session = bot.attach_client(websocket, f"user:{user.id}")
        model_ready = bot.predictor.is_ready if bot.predictor else False
        await manager.send_to(websocket, session.status_payload(model_ready))
        await manager.send_to(websocket, session.stats_payload())
        await manager.send_to(websocket, {
            "type": "log",
            "message": f"Signed in as {user.username}",
            "level": "info",
        })
        
        try:
            while True:
                data = await websocket.receive_json()
                action = data.get("action") or data.get("command")
                
                if action in ("hello", "identify"):
                    session = bot.attach_client(websocket, f"user:{user.id}")
                    await manager.send_to(websocket, session.status_payload(model_ready))
                    await manager.send_to(websocket, session.stats_payload())
                    continue
                
                if action == "start":
                    await bot.start_session(session)
                elif action == "stop":
                    await bot.stop_session(session)
                elif action == "pause":
                    await bot.pause_session(session)
                elif action == "resume":
                    session.paused = False
                    await manager.send_to_session(session.session_id, session.status_payload(
                        bot.predictor.is_ready if bot.predictor else False
                    ))
                elif action == "set_mode":
                    if is_companion or (not user.is_owner and not data.get("simulation", True)):
                        await manager.send_to(websocket, {
                            "type": "log",
                            "message": "REAL mode is only available on the Mac app",
                            "level": "loss",
                        })
                        continue
                    session.simulation = data.get("simulation", True)
                    logger.info(f"[{user.username}] Mode: {'SIM' if session.simulation else 'REAL'}")
                    
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
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can save API keys"}, status_code=403)
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
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can test API keys"}, status_code=403)
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
    async def reset_simulation(request: Request):
        """Reinicia la cuenta de simulación del usuario autenticado."""
        user = getattr(request.state, "user", None)
        session_id = f"user:{user.id}" if user else None
        
        if session_id:
            session = bot.get_session(session_id)
            session.reset(100.0)
            bot._save_session(session)
            await bot.manager.send_to_session(session_id, session.stats_payload())
        
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
    async def install_update(request: Request):
        """Instala la actualización disponible."""
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can install updates"}, status_code=403)
        updater = get_updater()
        success, message = await updater.update()
        return {"success": success, "message": message}
    
    @app.get("/api/version")
    async def get_version():
        """Obtiene la versión actual del bundle en ejecución."""
        version_path = Path(__file__).resolve().parent.parent / "VERSION"
        version = version_path.read_text().strip() if version_path.exists() else "0.0.0"
        return {"version": version.lstrip("vV")}
    
    # ═══════════════════════════════════════════════════════════
    # API Endpoints para Estrategias
    # ═══════════════════════════════════════════════════════════
    
    from .strategy_manager import get_strategy_manager
    
    @app.get("/api/strategies")
    async def get_strategies():
        """Obtiene todas las estrategias."""
        sm = get_strategy_manager()
        return {
            "strategies": sm.get_all_strategies(),
            "active": sm.active_strategy
        }
    
    @app.get("/api/strategies/active")
    async def get_active_strategy():
        """Obtiene la estrategia activa."""
        sm = get_strategy_manager()
        strategy = sm.get_active_strategy()
        return {"id": sm.active_strategy, **strategy.to_dict()}
    
    @app.post("/api/strategies/active")
    async def set_active_strategy(request: Request):
        """Establece la estrategia activa."""
        data = await request.json()
        sm = get_strategy_manager()
        success = sm.set_active_strategy(data.get("id", "default"))
        return {"success": success, "active": sm.active_strategy}
    
    @app.post("/api/strategies")
    async def create_strategy(request: Request):
        """Crea una nueva estrategia."""
        data = await request.json()
        sm = get_strategy_manager()
        strategy = sm.create_strategy(data.get("name", "Custom"), data)
        return {"success": True, "strategy": strategy.to_dict()}
    
    @app.put("/api/strategies/{strategy_id}")
    async def update_strategy(strategy_id: str, request: Request):
        """Actualiza una estrategia."""
        data = await request.json()
        sm = get_strategy_manager()
        strategy = sm.update_strategy(strategy_id, data)
        if strategy:
            return {"success": True, "strategy": strategy.to_dict()}
        return {"success": False, "error": "Strategy not found"}
    
    @app.delete("/api/strategies/{strategy_id}")
    async def delete_strategy(strategy_id: str):
        """Elimina una estrategia."""
        sm = get_strategy_manager()
        success = sm.delete_strategy(strategy_id)
        return {"success": success}
    
    @app.get("/api/strategies/compare")
    async def compare_strategies():
        """Compara rendimiento de estrategias."""
        sm = get_strategy_manager()
        return {"comparison": sm.compare_strategies()}
    
    # ═══════════════════════════════════════════════════════════
    # API Endpoints para Backtesting
    # ═══════════════════════════════════════════════════════════
    
    from .dashboard_backtest import get_backtester
    
    @app.post("/api/backtest/run")
    async def run_backtest(request: Request):
        """Ejecuta un backtest."""
        data = await request.json()
        
        backtester = get_backtester()
        
        if backtester.is_running:
            return {"success": False, "error": "Backtest already running"}
        
        try:
            # Obtener estrategia
            strategy = None
            strategy_id = data.get("strategy_id")
            if strategy_id:
                sm = get_strategy_manager()
                if strategy_id in sm.strategies:
                    strategy = sm.strategies[strategy_id]
            
            result = await backtester.run_backtest(
                strategy=strategy,
                days=data.get("days", 7),
                initial_capital=data.get("initial_capital", 100.0),
                bet_amount=data.get("bet_amount", 1.0)
            )
            
            return {"success": True, "result": result.to_dict()}
            
        except Exception as e:
            logger.error(f"Backtest error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.get("/api/backtest/status")
    async def get_backtest_status():
        """Obtiene el estado del backtest."""
        backtester = get_backtester()
        return {
            "running": backtester.is_running,
            "progress": backtester.progress,
            "has_result": backtester.current_result is not None
        }
    
    @app.get("/api/backtest/result")
    async def get_backtest_result():
        """Obtiene el resultado del último backtest."""
        backtester = get_backtester()
        if backtester.current_result:
            return {"success": True, "result": backtester.current_result.to_dict()}
        return {"success": False, "error": "No backtest result available"}
    
    # ═══════════════════════════════════════════════════════════
    # API Endpoints para Exportación
    # ═══════════════════════════════════════════════════════════
    
    from .data_exporter import get_exporter
    from fastapi.responses import Response
    
    @app.get("/api/export/trades/csv")
    async def export_trades_csv():
        """Exporta trades a CSV."""
        sm = get_settings_manager()
        exporter = get_exporter()
        
        trades = sm.settings.simulation.history
        csv_content = exporter.generate_csv_content(trades)
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=vibesbot_trades_{datetime.now().strftime('%Y%m%d')}.csv"
            }
        )
    
    @app.get("/api/export/trades/json")
    async def export_trades_json():
        """Exporta trades a JSON."""
        sm = get_settings_manager()
        
        return {
            "exported_at": datetime.now().isoformat(),
            "trades": sm.settings.simulation.history,
            "stats": sm.settings.simulation.to_dict()
        }
    
    @app.get("/api/export/report")
    async def export_report():
        """Genera un reporte de análisis."""
        sm = get_settings_manager()
        strategy_mgr = get_strategy_manager()
        exporter = get_exporter()
        
        trades = sm.settings.simulation.history
        stats = sm.settings.simulation.to_dict()
        strategy_name = strategy_mgr.get_active_strategy().name
        
        report = exporter.generate_report(trades, stats, strategy_name)
        return report
    
    return app


def run_dashboard(host: str = "0.0.0.0", port: int = 8080, config_path: Optional[str] = None):
    """Inicia el servidor del dashboard."""
    setup_logger("web_server", console_output=True)
    
    config = load_config(config_path)
    app = create_app(config)
    
    logger.info(f"Starting dashboard at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


# Crear instancia de app para usar con uvicorn directamente (ej: uvicorn src.web_server:app)
app = create_app()


if __name__ == "__main__":
    run_dashboard()
