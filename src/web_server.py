"""
Servidor web para el dashboard de Vibesbot.

Proporciona:
- Dashboard visual en tiempo real
- WebSocket para actualizaciones
- Control del bot (start/stop/pause)
"""
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
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
from .wallet_prediction import (
    PendingWalletTrade,
    WalletPredictionClient,
    clamp_bet_amount,
    fill_from_quote,
    looks_like_btc_price,
    market_book,
    outcome_token,
    paper_fill,
    settle_payout,
    tradable_edge,
)


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
    live_balance: Optional[float] = None
    live_wallet: str = ""
    live_wallets: Dict[str, float] = field(default_factory=dict)
    live_wallet_address: str = ""
    live_network: str = ""
    live_error: str = ""
    live_can_trade: bool = False
    live_trade_error: str = ""
    live_fetched_at: float = 0.0
    pending_trade: Optional[PendingWalletTrade] = None
    
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
        self.pending_trade = None
    
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
        if not self.simulation:
            capital = self.live_balance if self.live_balance is not None else max(0.0, self.initial_capital + self.cumulative_pnl)
            return {
                "type": "stats",
                "capital": capital,
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
                "equity_history": self.equity_history[-50:] or [capital],
                "live": True,
                "simulation": False,
                "wallet": self.live_wallet,
                "wallets": self.live_wallets,
                "wallet_address": self.live_wallet_address,
                "network": self.live_network or "BNB Smart Chain",
                "live_error": self.live_error,
            }
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
            "live": False,
            "simulation": True,
            "wallet": "Simulation",
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
        self._last_prediction_round = -1
        self._market_book: Dict[str, Any] = {}
        self._market_topic: Optional[Dict[str, Any]] = None
        self._market_fetched_at = 0.0
        self._price_to_beat = 0.0
        self._price_to_beat_round = -1
        
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

    async def refresh_live_balances(self, session: ClientSession) -> None:
        from .user_settings import get_settings_manager

        result = await get_settings_manager().fetch_live_balances()
        session.live_wallets = result.get("wallets") or {}
        session.live_wallet = result.get("display_wallet") or "My Wallet"
        session.live_wallet_address = result.get("wallet_address") or ""
        session.live_network = result.get("network") or "BNB Smart Chain"
        session.live_balance = float(result.get("display_balance") or 0)
        session.live_error = result.get("error") or ""
        session.live_can_trade = bool(result.get("can_trade"))
        session.live_trade_error = str(result.get("trade_error") or "")
        session.live_fetched_at = time.time()

    async def refresh_market_book(self, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        if not force and self._market_book and now - self._market_fetched_at < 5:
            return self._market_book
        from .user_settings import get_settings_manager

        sm = get_settings_manager()
        creds = sm.settings.binance
        if not creds.is_configured or creds.is_testnet:
            return self._market_book
        try:
            client = WalletPredictionClient(
                creds.api_key,
                creds.api_secret,
                preferred_address=creds.prediction_wallet,
            )
            topic = await client.find_btc_5m_market()
            if topic:
                self._market_topic = topic
                self._market_book = market_book(topic)
                self._market_fetched_at = now
        except Exception as exc:
            logger.warning(f"Wallet market book failed: {exc}")
        return self._market_book

    def _five_minute_open(self) -> float:
        if not self.data_stream:
            return 0.0
        candle = self.data_stream.get_latest_candle("5m")
        if candle and looks_like_btc_price(candle.open):
            return float(candle.open)
        return 0.0

    def _last_closed_five_minute(self) -> Optional[Any]:
        if not self.data_stream:
            return None
        return self.data_stream.get_last_closed_candle("5m")

    def _resolve_price_to_beat(self, book: Optional[Dict[str, Any]], round_number: int) -> float:
        book = book or {}
        from_book = float(book.get("price_to_beat") or 0)
        if looks_like_btc_price(from_book):
            self._price_to_beat = from_book
            self._price_to_beat_round = round_number
            return from_book
        if self._price_to_beat_round == round_number and looks_like_btc_price(self._price_to_beat):
            return self._price_to_beat
        open_px = self._five_minute_open()
        if looks_like_btc_price(open_px):
            self._price_to_beat = open_px
            self._price_to_beat_round = round_number
            return open_px
        if looks_like_btc_price(self._price_to_beat):
            return self._price_to_beat
        return 0.0

    def _round_close_price(self) -> float:
        closed = self._last_closed_five_minute()
        if closed and looks_like_btc_price(closed.close):
            return float(closed.close)
        if self.data_stream:
            price = self.data_stream.get_current_price()
            if looks_like_btc_price(price):
                return float(price)
        return 0.0

    def _today_session_stats(self, session: ClientSession) -> Dict[str, float]:
        today = datetime.now(timezone.utc).date().isoformat()
        pnl = 0.0
        count = 0
        for row in session.trades:
            stamp = str(row.get("timestamp") or "")
            if stamp.startswith(today):
                try:
                    pnl += float(row.get("pnl") or 0)
                except (TypeError, ValueError):
                    pass
                count += 1
        return {"pnl": pnl, "count": count}
    
    async def _data_loop(self):
        """Loop que siempre envía datos de mercado, incluso sin trading."""
        logger.info("Data loop started - sending market updates")
        
        while True:
            try:
                await self._send_market()
                now = time.time()
                for session in list(self.sessions.values()):
                    if not session.simulation and now - session.live_fetched_at > 20:
                        try:
                            await self.refresh_live_balances(session)
                        except Exception as exc:
                            logger.error(f"Live balance refresh failed: {exc}")
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
        """Motor único: predicción + apuesta Wallet (SIM paper / REAL API)."""
        logger.info("Session engine started")
        last_prediction_round = -1
        last_trade_round = -1
        
        while True:
            try:
                active = [s for s in self.sessions.values() if s.running and not s.paused]
                round_times = calculate_round_times(5, self._time_offset)
                remaining = round_times["seconds_remaining"]
                current_round = round_times.get("round_number", 0)

                await self._settle_due(current_round)
                
                if active:
                    if 60 <= remaining <= 95 and current_round != last_prediction_round:
                        await self._generate_prediction(active, current_round)
                        last_prediction_round = current_round
                    
                    if 50 <= remaining <= 85 and current_round != last_trade_round:
                        await asyncio.gather(*[self._execute_trade(session, current_round) for session in active])
                        last_trade_round = current_round
                
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session engine: {e}")
                await asyncio.sleep(2)
    
    async def _run_loop(self):
        return
    
    async def _generate_prediction(self, sessions: Optional[List[ClientSession]] = None, current_round: int = 0):
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
            self._last_prediction_round = current_round

            round_times = calculate_round_times(5, self._time_offset)
            round_number = int(round_times.get("round_number") or current_round)
            book = await self.refresh_market_book(force=True)
            binance_up = float(book.get("up") or 0.5) if book else 0.5
            binance_down = float(book.get("down") or 0.5) if book else 0.5
            price_to_beat = self._resolve_price_to_beat(book, round_number)

            await self._emit_sessions(sessions, {
                "type": "signal",
                "signal": signal,
                "confidence": confidence,
                "prob_up": binance_up,
                "prob_down": binance_down,
                "up_odds": (book or {}).get("up_odds"),
                "down_odds": (book or {}).get("down_odds"),
                "price_to_beat": price_to_beat
            })
            
            await self._emit_sessions(sessions, {
                "type": "log",
                "message": (
                    f"SIGNAL: {signal} {confidence*100:.0f}% | Binance Up {binance_up*100:.0f}% "
                    f"({float((book or {}).get('up_odds') or 2):.2f}x) / Down {binance_down*100:.0f}% "
                    f"({float((book or {}).get('down_odds') or 2):.2f}x)"
                    + (f" | {strategy_used}" if strategy_used and strategy_used != "none" else "")
                    + (f" | beat ${price_to_beat:,.2f}" if price_to_beat else " | waiting for round open")
                ),
                "level": "prediction"
            })
            
            logger.info(f"Prediction: {signal} @ {confidence:.1%}")
            
        except Exception as e:
            logger.error(f"Error generating prediction: {e}")
    
    async def _emit_sessions(self, sessions: Optional[List[ClientSession]], message: dict):
        targets = sessions if sessions is not None else list(self.sessions.values())
        for session in targets:
            await self.manager.send_to_session(session.session_id, message)
    
    async def _execute_trade(self, session: Optional[ClientSession] = None, current_round: int = 0):
        """Coloca una apuesta Wallet: paper en SIM, orden oficial en REAL."""
        if session is None:
            return
        if session.pending_trade and session.pending_trade.round_number == current_round:
            return
        try:
            signal = self._last_prediction
            confidence = self._last_prediction_confidence
            if not signal or signal == "WAIT":
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": "WAITING FOR SIGNAL",
                    "level": "info",
                })
                return

            from .user_settings import effective_confidence_threshold, get_settings_manager
            sm = get_settings_manager()
            if self._last_prediction_round != current_round:
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": "WAITING FOR THIS ROUND'S SIGNAL",
                    "level": "info",
                })
                return
            threshold = effective_confidence_threshold(sm.settings.trading.confidence_threshold)
            if confidence < threshold:
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": f"SKIP: Confidence {confidence*100:.0f}% < {threshold*100:.0f}%",
                    "level": "info",
                })
                return

            amount = clamp_bet_amount(sm.settings.trading.bet_amount)
            day = self._today_session_stats(session)
            max_loss = float(sm.settings.trading.max_daily_loss or 0)
            if max_loss > 0 and day["pnl"] <= -max_loss:
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": f"SKIP: daily loss ${day['pnl']:.2f} hit the ${max_loss:.2f} Settings limit",
                    "level": "info",
                })
                return
            max_trades = int(sm.settings.trading.max_trades_per_day or 0)
            if max_trades > 0 and day["count"] >= max_trades:
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": f"SKIP: {day['count']} trades already hit the daily cap",
                    "level": "info",
                })
                return

            book = await self.refresh_market_book(force=True)
            open_price = self._resolve_price_to_beat(book, current_round)
            share_price = 0.50
            if book:
                if signal == "UP":
                    share_price = float(book.get("up") or 0.5)
                elif signal == "DOWN":
                    share_price = float(book.get("down") or 0.5)
            edge = tradable_edge(share_price, amount)
            if not edge["ok"]:
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": f"SKIP: {signal} {edge['reason']}",
                    "level": "info",
                })
                return
            fill = paper_fill(amount, edge["share_price"])
            live = False
            order_id = ""
            market_title = "BTC 5m Wallet (paper)"
            balance_before = 0.0

            if not session.simulation:
                creds = sm.settings.binance
                if not creds.is_configured:
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": "REAL needs a live Binance API key",
                        "level": "loss",
                    })
                    return
                client = WalletPredictionClient(
                    creds.api_key,
                    creds.api_secret,
                    preferred_address=creds.prediction_wallet,
                )
                wallet = await client.ensure_wallet(refresh=True)
                pred_balance = float(wallet.get("usdt") or 0)
                balance_before = pred_balance
                if (
                    not wallet.get("can_trade")
                    or not wallet.get("walletId")
                    or not wallet.get("orderAddress")
                ):
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": wallet.get("error") or (
                            "REAL blocked: Binance wallet/list did not return a Prediction Account."
                        ),
                        "level": "loss",
                    })
                    return
                if pred_balance < amount:
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": (
                            f"Prediction Account USDT ${pred_balance:.2f} is below ${amount:.2f}. "
                            "Use Transfer In on Binance Prediction → Portfolio. "
                            "My Wallet tokens are not this balance."
                        ),
                        "level": "loss",
                    })
                    return
                topic = await client.find_btc_5m_market()
                if not topic:
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": "No open BTC 5m Wallet market. Check Wallet → Prediction in Binance.",
                        "level": "loss",
                    })
                    return
                topic_book = market_book(topic)
                open_price = self._resolve_price_to_beat(topic_book, current_round) or open_price
                token = outcome_token(topic, signal)
                fee_bps = int(topic.get("feeRateBps") or 200)
                if token:
                    share_price = float(token.get("price") or share_price)
                edge = tradable_edge(share_price, amount, fee_bps)
                if not edge["ok"]:
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": f"SKIP: {signal} {edge['reason']}",
                        "level": "info",
                    })
                    return
                fill = paper_fill(amount, edge["share_price"], fee_bps)
                placed = await client.quote_and_buy(topic, signal, amount, edge["share_price"])
                if not placed.get("success"):
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": f"REAL order failed: {placed.get('error') or 'unknown'}",
                        "level": "loss",
                    })
                    return
                quote_fill = fill_from_quote(
                    placed.get("quote") if isinstance(placed.get("quote"), dict) else {},
                    amount,
                    placed.get("share_price") or edge["share_price"],
                    fee_bps,
                )
                live_edge = tradable_edge(quote_fill["share_price"], amount, fee_bps)
                if not live_edge["ok"]:
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": (
                            f"REAL filled {signal} ${amount:.2f} @ {quote_fill['share_price']:.2f} "
                            f"but that book is lopsided — {live_edge['reason']}"
                        ),
                        "level": "info",
                    })
                live = True
                order_id = str(placed.get("order_id") or "")
                fill = quote_fill
                market_title = str(placed.get("title") or topic.get("title") or "Wallet BTC 5m")
                await self.refresh_live_balances(session)
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": (
                        f"REAL {signal} ${amount:.2f} sent from "
                        f"{placed.get('wallet_address') or wallet.get('walletAddress')} "
                        f"on BNB Smart Chain order {order_id or 'submitted'}"
                    ),
                    "level": "info",
                })

            session.pending_trade = PendingWalletTrade(
                session_id=session.session_id,
                round_number=current_round,
                signal=signal,
                stake=amount,
                open_price=open_price,
                share_price=fill["share_price"],
                shares=fill["shares"],
                fee=fill["fee"],
                cost=fill["cost"],
                live=live,
                order_id=order_id,
                market_title=market_title,
                balance_before=balance_before,
            )
            mode = "REAL" if live else "SIM"
            beat = f"${open_price:,.2f}" if open_price else "unknown open"
            await self.manager.send_to_session(session.session_id, {
                "type": "log",
                "message": (
                    f"{mode} {signal} ${amount:.2f} @ {fill['share_price']:.2f} "
                    f"(win ~${fill['win_pnl']:.2f}) | fee ${fill['fee']:.3f} | beat {beat}"
                ),
                "level": "info",
            })
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            import traceback
            traceback.print_exc()

    async def _settle_due(self, current_round: int) -> None:
        close_price = self._round_close_price()
        for session in list(self.sessions.values()):
            pending = session.pending_trade
            if not pending or pending.round_number >= current_round:
                continue
            await self._settle_trade(session, pending, close_price)

    async def _settle_trade(self, session: ClientSession, pending: PendingWalletTrade, close_price: float) -> None:
        from datetime import datetime

        closed = self._last_closed_five_minute()
        if closed:
            if not looks_like_btc_price(pending.open_price) and looks_like_btc_price(closed.open):
                pending.open_price = float(closed.open)
            if not looks_like_btc_price(close_price) and looks_like_btc_price(closed.close):
                close_price = float(closed.close)

        if not looks_like_btc_price(pending.open_price) or not looks_like_btc_price(close_price):
            logger.warning(
                f"Delay settle {pending.signal}: open={pending.open_price} close={close_price}"
            )
            return

        actual, result, pnl = settle_payout(
            pending.signal, pending.open_price, close_price, pending.shares, pending.cost
        )
        if result == "WIN":
            session.wins += 1
            session.streak = max(1, session.streak + 1) if session.streak >= 0 else 1
        elif result == "LOSS":
            session.losses += 1
            session.streak = min(-1, session.streak - 1) if session.streak <= 0 else -1
        session.cumulative_pnl += pnl
        session.best_streak = max(session.best_streak, session.streak)
        session.worst_streak = min(session.worst_streak, session.streak)
        current_equity = (session.live_balance if (not session.simulation and session.live_balance is not None)
                          else session.initial_capital + session.cumulative_pnl)
        session.equity_history.append(current_equity)
        session.max_equity = max(session.max_equity, current_equity)
        if session.max_equity > 0:
            drawdown = ((session.max_equity - current_equity) / session.max_equity) * 100
            session.max_drawdown = max(session.max_drawdown, drawdown)
        session.trades.append({
            "timestamp": datetime.now().isoformat(),
            "direction": pending.signal,
            "amount": pending.stake,
            "entry_price": pending.open_price,
            "exit_price": close_price,
            "pnl": pnl,
            "result": result,
            "live": pending.live,
            "fee": pending.fee,
        })
        session.pending_trade = None
        if not session.simulation:
            try:
                await self.refresh_live_balances(session)
            except Exception:
                pass
        await self.manager.send_to_session(session.session_id, {
            "type": "trade",
            "timestamp": datetime.now().isoformat(),
            "direction": pending.signal,
            "amount": pending.stake,
            "entry_price": pending.open_price,
            "exit_price": close_price,
            "confidence": self._last_prediction_confidence * 100,
            "pnl": pnl,
            "result": result,
        })
        if actual == "FLAT":
            explanation = "Tie 50-50 (Chainlink rule)"
            level = "info"
        else:
            explanation = f"Price {actual} [{'correct' if result == 'WIN' else 'wrong'}]"
            level = "win" if result == "WIN" else "loss"
        await self.manager.send_to_session(session.session_id, {
            "type": "log",
            "message": f"{'REAL' if pending.live else 'SIM'} {pending.signal} | ${pending.open_price:,.2f} -> ${close_price:,.2f} | {result} | {explanation} | P&L ${pnl:+.2f}",
            "level": level,
        })
        await self.manager.send_to_session(session.session_id, session.stats_payload())
        self._save_session(session)
        logger.info(f"[{session.session_id[:8]}] Settled {pending.signal} {result} ${pnl:+.2f}")
    
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
            },
            "prob_up": (self._market_book or {}).get("up"),
            "prob_down": (self._market_book or {}).get("down"),
            "up_odds": (self._market_book or {}).get("up_odds"),
            "down_odds": (self._market_book or {}).get("down_odds"),
            "price_to_beat": self._resolve_price_to_beat(
                self._market_book, int(round_times.get("round_number") or 0)
            ) or None,
            "signal": self._last_prediction,
        })
        if remaining % 5 == 0:
            await self.refresh_market_book()
    
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
            session.simulation = data.get("simulation", True)
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
                    "simulation": session.simulation,
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
        "/api/updates/check",
        "/api/updates/install",
        "/api/version",
        "/api/system/quit",
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
            target = "/static/lobby.html" if _is_local(request) else "/companion"
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
        response = RedirectResponse("/static/lobby.html", status_code=302)
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

    @app.post("/api/system/quit")
    async def quit_app(request: Request):
        if not _is_local(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)

        async def _die():
            await asyncio.sleep(0.15)
            os._exit(0)

        asyncio.create_task(_die())
        return {"success": True}

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
        if not session.simulation:
            try:
                await bot.refresh_live_balances(session)
            except Exception as exc:
                logger.error(f"Live balance refresh on connect failed: {exc}")
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
                        await manager.send_to(websocket, session.status_payload(model_ready))
                        await manager.send_to(websocket, session.stats_payload())
                        continue
                    session.simulation = data.get("simulation", True)
                    logger.info(f"[{user.username}] Mode: {'SIM' if session.simulation else 'REAL'}")
                    if session.simulation:
                        await manager.send_to(websocket, {
                            "type": "log",
                            "message": "Simulation account",
                            "level": "info",
                        })
                    else:
                        await bot.refresh_live_balances(session)
                        if session.live_error:
                            await manager.send_to(websocket, {
                                "type": "log",
                                "message": session.live_error,
                                "level": "loss",
                            })
                        elif not session.live_can_trade:
                            await manager.send_to(websocket, {
                                "type": "log",
                                "message": (
                                    session.live_trade_error
                                    or "REAL blocked: no Prediction Account in wallet/list."
                                ),
                                "level": "loss",
                            })
                        else:
                            await manager.send_to(websocket, {
                                "type": "log",
                                "message": (
                                    f"Live {session.live_wallet} ${session.live_balance:.2f} "
                                    f"{session.live_wallet_address}. "
                                    "This is Binance Prediction → Portfolio (Transfer In). "
                                    "My Wallet tokens are not spent."
                                ),
                                "level": "info",
                            })
                    bot._save_session(session)
                    await manager.send_to(websocket, session.status_payload(model_ready))
                    await manager.send_to(websocket, session.stats_payload())
                    
        except WebSocketDisconnect:
            manager.disconnect(websocket)
    
    # ═══════════════════════════════════════════════════════════
    # API Endpoints para Settings
    # ═══════════════════════════════════════════════════════════
    
    from .user_settings import get_settings_manager, TradingMode, binance_testnet_from_payload
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
            is_testnet=binance_testnet_from_payload(data),
            prediction_wallet=data.get("prediction_wallet") or data.get("wallet_address") or "",
        )
        return {"success": True}
    
    @app.post("/api/settings/binance/test")
    async def test_binance_connection(request: Request):
        """Prueba la conexión con Binance."""
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can test API keys"}, status_code=403)
        data = await request.json()
        sm = get_settings_manager()
        sm.update_binance_credentials(
            api_key=data.get("api_key", ""),
            api_secret=data.get("api_secret", ""),
            is_testnet=binance_testnet_from_payload(data),
            prediction_wallet=data.get("prediction_wallet") or data.get("wallet_address") or "",
        )
        result = await sm.test_binance_connection()
        return result

    @app.get("/api/binance/balances")
    async def binance_balances(request: Request):
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can read balances"}, status_code=403)
        sm = get_settings_manager()
        return await sm.fetch_live_balances()
    
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
        if not _is_local(request):
            return JSONResponse({"error": "Updates can only be installed on the Mac app"}, status_code=403)
        updater = get_updater()
        success, message = await updater.update()
        if success:
            from .runtime import relaunch_app
            relaunch_app(delay=1.4)
        return {"success": success, "message": message, "relaunching": bool(success)}
    
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
