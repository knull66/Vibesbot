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
from .predictor import Predictor
from .risk_manager import RiskManager, RiskStatus
from .utils.logger import setup_logger, get_logger
from .utils.helpers import calculate_round_times
from .round_signal import combine_indicator_votes, crowd_agrees, price_confirms, tape_vote
from .auth import COOKIE_NAME, SESSION_DAYS, get_auth
from .companion import dashboard_bind_host, get_companion, is_loopback
from .wallet_prediction import (
    PendingWalletTrade,
    WalletPredictionClient,
    clamp_bet_amount,
    fetch_spot_top_of_book,
    fill_from_quote,
    looks_like_btc_price,
    market_book,
    outcome_token,
    cut_loss_ready,
    live_equity_baseline,
    paper_fill,
    pending_trade_from_dict,
    sell_proceeds,
    settle_payout,
    take_profit_ready,
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
            "model_loaded": True,
            "signal_engine": "indicators+tape",
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
        self._price_to_beat_source = ""
        
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
            from .utils.helpers import sync_binance_time
            logger.info("Synchronizing time with Binance...")
            self._time_offset = await sync_binance_time()
            logger.info(f"Time offset: {self._time_offset:.3f}s")
        except Exception as e:
            logger.warning(f"Time sync failed, using local clock: {e}")
            self._time_offset = 0.0
        try:
            logger.info("Initializing data stream...")
            self.data_stream = DataStream(self.config.data_stream)
            await self.data_stream.start()
        except Exception as e:
            logger.error(f"Data stream failed: {e}")
        # Live bets are indicators + tape. Skip LightGBM load — it is not on this path.
        try:
            logger.info("Initializing risk manager...")
            self.risk_manager = RiskManager(self.config.risk, self.config.trading)
        except Exception as e:
            logger.error(f"Risk manager failed: {e}")
        try:
            await self.manager.broadcast({
                "type": "status",
                "running": False,
                "paused": False,
                "model_loaded": True,
                "signal_engine": "indicators+tape",
            })
        except Exception:
            pass
        if self._data_task is None or self._data_task.done():
            self._data_task = asyncio.create_task(self._data_loop())
        if self._engine_task is None or self._engine_task.done():
            self._engine_task = asyncio.create_task(self._session_engine())
        return True
    
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
        healed = live_equity_baseline(session.live_balance, session.cumulative_pnl, session.max_equity)
        if healed:
            peak, drawdown = healed
            session.max_equity = peak
            session.initial_capital = peak
            session.equity_history = [peak] if abs(peak - session.live_balance) < 0.01 else [peak, session.live_balance]
            session.max_drawdown = drawdown

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
                book = market_book(topic)
                if not looks_like_btc_price(book.get("live_price")):
                    book["live_price"] = await fetch_spot_top_of_book()
                    if looks_like_btc_price(book.get("live_price")):
                        book["live_source"] = "binance-spot-tob"
                self._market_book = book
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
        """Official Wallet lock when Binance sends it; else this 5m Spot open."""
        book = book or {}
        from_book = float(book.get("price_to_beat") or 0)
        if looks_like_btc_price(from_book):
            self._price_to_beat = from_book
            self._price_to_beat_round = round_number
            self._price_to_beat_source = str(book.get("price_to_beat_source") or "wallet")
            return from_book
        if self._price_to_beat_round == round_number and looks_like_btc_price(self._price_to_beat):
            return self._price_to_beat
        fallback = self._five_minute_open()
        if looks_like_btc_price(fallback):
            self._price_to_beat = fallback
            self._price_to_beat_round = round_number
            self._price_to_beat_source = "spot-5m-open"
            return fallback
        self._price_to_beat_source = ""
        return 0.0

    def _price_to_beat_payload(self, book: Optional[Dict[str, Any]], round_number: int) -> Dict[str, Any]:
        beat = self._resolve_price_to_beat(book, round_number)
        return {
            "price_to_beat": beat or None,
            "price_to_beat_source": self._price_to_beat_source if beat else "",
        }

    def _live_btc_price(self, book: Optional[Dict[str, Any]] = None) -> float:
        """Live Chainlink-equivalent: topic oracle, else Binance Spot top-of-book."""
        book = book if book is not None else (self._market_book or {})
        live = float(book.get("live_price") or 0)
        if looks_like_btc_price(live):
            return live
        if self.data_stream:
            price = self.data_stream.get_current_price()
            if looks_like_btc_price(price):
                return float(price)
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
                if remaining >= 25:
                    holders = [s for s in self.sessions.values() if s.pending_trade]
                    if holders:
                        await asyncio.gather(*[
                            self._maybe_take_profit(session, remaining) for session in holders
                        ])

                if active:
                    # After ~1 min the open exists: join a move vs beat, not a 50/50 coin flip.
                    if 185 <= remaining <= 230 and current_round != last_prediction_round:
                        await self._generate_prediction(active, current_round)
                        last_prediction_round = current_round
                    
                    if 160 <= remaining <= 205 and current_round != last_trade_round:
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
        try:
            signal = "WAIT"
            confidence = 0.5
            prob_up = 0.5
            prob_down = 0.5
            strategy_used = "none"

            # Live Wallet bets use indicators + tape only. LightGBM is not on this path.
            if self.data_stream:
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

                        flow = self.data_stream.calculate_trade_flow(60)
                        book_imb = 0.0
                        try:
                            book_imb = float(self.data_stream.get_order_book().calculate_imbalance(5) or 0)
                        except Exception:
                            book_imb = 0.0
                        tape_signal = tape_vote(float(flow.get("flow_imbalance") or 0), book_imb)

                        weights = None
                        try:
                            from .strategy_manager import get_strategy_manager
                            active = get_strategy_manager().get_active_strategy()
                            weights = {
                                "rsi": active.rsi_weight,
                                "macd": active.macd_weight,
                                "bollinger": active.bollinger_weight,
                                "momentum": active.momentum_weight,
                            }
                        except Exception:
                            weights = None
                        signal, confidence, strategy_used = combine_indicator_votes(
                            rsi_signal, macd_signal, bb_signal, mom_signal, tape_signal, weights
                        )
                        
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
                "price_to_beat": price_to_beat,
                "price_to_beat_source": self._price_to_beat_source if price_to_beat else "",
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

            if self.risk_manager is None:
                try:
                    self.risk_manager = RiskManager(self.config.risk, self.config.trading)
                except Exception:
                    self.risk_manager = None
            if self.risk_manager:
                allowed, reason = self.risk_manager.circuit_status()
                if not allowed:
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": reason,
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
                if not crowd_agrees(signal, book):
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": (
                            f"SKIP: crowd disagrees ({signal} vs "
                            f"Up {float(book.get('up') or 0)*100:.0f}% / "
                            f"Down {float(book.get('down') or 0)*100:.0f}%)"
                        ),
                        "level": "info",
                    })
                    return
            current_px = self._live_btc_price(book)
            confirmed, confirm_reason = price_confirms(signal, current_px, open_price)
            if not confirmed:
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": f"SKIP: {confirm_reason}",
                    "level": "info",
                })
                return
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
                if topic_book and not crowd_agrees(signal, topic_book):
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": (
                            f"SKIP: crowd disagrees on Wallet book "
                            f"(Up {float(topic_book.get('up') or 0)*100:.0f}% / "
                            f"Down {float(topic_book.get('down') or 0)*100:.0f}%)"
                        ),
                        "level": "info",
                    })
                    return
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
                        f"REAL {signal} ${amount:.2f} submitted"
                        + (f" · order {order_id}" if order_id else "")
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
                topic_id=str(placed.get("topic_id") or topic.get("marketTopicId") or "") if live else "",
                token_id=str((placed.get("token") or {}).get("token_id") or "") if live else "",
                end_date_ms=int(placed.get("end_date") or topic.get("endDate") or 0) if live else 0,
                opened_at=time.time(),
            )
            mode = "REAL" if live else "SIM"
            beat = f"${open_price:,.2f}" if open_price else "unknown open"
            await self.manager.send_to_session(session.session_id, {
                "type": "log",
                "message": (
                    f"{mode} {signal} ${amount:.2f} @ {fill['share_price']:.2f} "
                    f"(win ~${fill['win_pnl']:.2f}) | {confirm_reason} | fee ${fill['fee']:.3f} | beat {beat}"
                    + (f" · {market_title}" if live and market_title else "")
                ),
                "level": "info",
            })
            self._save_session(session)
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            import traceback
            traceback.print_exc()

    async def _emit_open_position(self, session: ClientSession, mark: float, seconds_left: float) -> None:
        pending = session.pending_trade
        if not pending or mark <= 0:
            await self.manager.send_to_session(session.session_id, {"type": "active_trade", "active": False})
            return
        proceeds, _fee = sell_proceeds(pending.shares, mark)
        pnl = proceeds - float(pending.cost)
        span = 300.0
        progress = max(0.0, min(100.0, (1.0 - (float(seconds_left) / span)) * 100))
        await self.manager.send_to_session(session.session_id, {
            "type": "active_trade",
            "active": True,
            "direction": pending.signal,
            "entry_price": pending.share_price,
            "current_price": mark,
            "pnl": pnl,
            "progress": progress,
        })

    async def _exit_open_position(
        self,
        session: ClientSession,
        pending: PendingWalletTrade,
        book: Dict[str, Any],
        mark: float,
        reason: str,
        pnl: float,
        label: str,
    ) -> bool:
        if pending.live:
            client = await self._live_prediction_client(session)
            if not client or not pending.token_id:
                return False
            topic = {}
            if pending.topic_id:
                topic = await client.market_detail(pending.topic_id)
            if not topic:
                topic = {}
            if pending.topic_id and not topic.get("marketTopicId"):
                topic["marketTopicId"] = pending.topic_id
            sold = await client.quote_and_sell(topic, pending.token_id, pending.shares)
            if not sold.get("success"):
                last_fail = float(getattr(pending, "_last_sell_fail_log", 0) or 0)
                if time.time() - last_fail >= 20:
                    pending._last_sell_fail_log = time.time()
                    await self.manager.send_to_session(session.session_id, {
                        "type": "log",
                        "message": f"{label} failed: {sold.get('error') or 'sell rejected'}",
                        "level": "loss",
                    })
                return False
            proceeds = float(sold.get("proceeds") or 0)
            pnl = proceeds - float(pending.cost)
            mark = float(sold.get("share_price") or mark)
            reason = f"SOLD @ {mark:.2f} for ${proceeds:.2f}"
        result = "WIN" if pnl >= 0 else "LOSS"
        await self._record_settlement(
            session,
            pending,
            result=result,
            pnl=pnl,
            exit_price=self._live_btc_price(book),
            explanation=reason,
        )
        await self.manager.send_to_session(session.session_id, {"type": "active_trade", "active": False})
        return True

    async def _maybe_take_profit(self, session: ClientSession, seconds_left: float) -> None:
        """Lock a markup or cut a hard fade. Otherwise show the open mark."""
        pending = session.pending_trade
        if not pending:
            return
        book = await self.refresh_market_book()
        mark = 0.0
        if book:
            if pending.signal == "UP":
                mark = float(book.get("up") or 0)
            elif pending.signal == "DOWN":
                mark = float(book.get("down") or 0)
        await self._emit_open_position(session, mark, seconds_left)
        held = 0.0
        if pending.opened_at:
            held = max(0.0, time.time() - float(pending.opened_at))
        ok, reason, pnl = take_profit_ready(
            pending.share_price, mark, pending.shares, pending.cost, seconds_left,
            held_seconds=held,
        )
        label = "TAKE PROFIT"
        if not ok:
            ok, reason, pnl = cut_loss_ready(
                pending.share_price, mark, pending.shares, pending.cost, seconds_left,
                held_seconds=held,
            )
            label = "CUT LOSS"
        if not ok:
            return
        last_try = float(getattr(pending, "_last_sell_try", 0) or 0)
        if time.time() - last_try < 5:
            return
        pending._last_sell_try = time.time()
        await self._exit_open_position(session, pending, book or {}, mark, reason, pnl, label)

    async def _settle_due(self, current_round: int) -> None:
        for session in list(self.sessions.values()):
            pending = session.pending_trade
            if not pending:
                continue
            if pending.live:
                await self._settle_live_trade(session, pending)
                continue
            if pending.round_number >= current_round:
                continue
            await self._settle_paper_trade(session, pending)

    async def _live_prediction_client(self, session: ClientSession) -> Optional[WalletPredictionClient]:
        from .user_settings import get_settings_manager

        creds = get_settings_manager().settings.binance
        if not creds.is_configured:
            return None
        return WalletPredictionClient(
            creds.api_key,
            creds.api_secret,
            preferred_address=creds.prediction_wallet,
        )

    async def _settle_live_trade(self, session: ClientSession, pending: PendingWalletTrade) -> None:
        client = await self._live_prediction_client(session)
        if not client:
            return
        try:
            resolved = await client.resolve_live_result(pending)
        except Exception as exc:
            logger.warning(f"Binance settle poll failed: {exc}")
            return
        if not resolved.get("ready"):
            reason = str(resolved.get("reason") or "waiting")
            last_log = float(getattr(pending, "_last_wait_log", 0) or 0)
            if reason in ("polling", "market still open on Binance"):
                return
            if time.time() - last_log >= 30:
                pending._last_wait_log = time.time()
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": (
                        f"REAL {pending.signal} waiting for Binance result"
                        + (f" · {pending.market_title}" if pending.market_title else "")
                    ),
                    "level": "info",
                })
            return
        result = str(resolved.get("result") or "LOSS")
        pnl = float(resolved.get("pnl") or 0)
        actual = str(resolved.get("actual") or "")
        title = str(resolved.get("title") or pending.market_title or "Wallet BTC 5m")
        await self._record_settlement(
            session,
            pending,
            result=result,
            pnl=pnl,
            exit_price=0.0,
            explanation=f"Binance settled {result} · {title}" + (f" · outcome {actual}" if actual else ""),
        )

    async def _settle_paper_trade(self, session: ClientSession, pending: PendingWalletTrade) -> None:
        close_price = self._live_btc_price()
        topic_close = float((self._market_book or {}).get("close_price") or 0)
        if looks_like_btc_price(topic_close):
            close_price = topic_close
        if not looks_like_btc_price(pending.open_price):
            logger.warning(
                f"Delay paper settle {pending.signal}: no Wallet Price to Beat yet"
            )
            return
        if not looks_like_btc_price(close_price):
            logger.warning(
                f"Delay paper settle {pending.signal}: no live BTC print yet"
            )
            return

        actual, result, pnl = settle_payout(
            pending.signal, pending.open_price, close_price, pending.shares, pending.cost
        )
        if actual == "FLAT":
            explanation = "Tie 50-50 (Chainlink rule)"
        else:
            explanation = f"Price {actual} [{'correct' if result == 'WIN' else 'wrong'}]"
        await self._record_settlement(
            session,
            pending,
            result=result,
            pnl=pnl,
            exit_price=close_price,
            explanation=explanation,
        )

    async def _record_settlement(
        self,
        session: ClientSession,
        pending: PendingWalletTrade,
        result: str,
        pnl: float,
        exit_price: float,
        explanation: str,
    ) -> None:
        if result == "WIN":
            session.wins += 1
            session.streak = max(1, session.streak + 1) if session.streak >= 0 else 1
        elif result == "LOSS":
            session.losses += 1
            session.streak = min(-1, session.streak - 1) if session.streak <= 0 else -1
        session.cumulative_pnl += pnl
        session.best_streak = max(session.best_streak, session.streak)
        session.worst_streak = min(session.worst_streak, session.streak)
        if not session.simulation:
            try:
                await self.refresh_live_balances(session)
            except Exception:
                pass
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
            "exit_price": exit_price,
            "pnl": pnl,
            "result": result,
            "live": pending.live,
            "fee": pending.fee,
            "market": pending.market_title,
            "order_id": pending.order_id,
        })
        session.pending_trade = None
        await self.manager.send_to_session(session.session_id, {
            "type": "trade",
            "timestamp": datetime.now().isoformat(),
            "direction": pending.signal,
            "amount": pending.stake,
            "entry_price": pending.open_price,
            "exit_price": exit_price,
            "confidence": self._last_prediction_confidence * 100,
            "pnl": pnl,
            "result": result,
        })
        level = "win" if result == "WIN" else ("info" if result == "PUSH" else "loss")
        mode = "REAL" if pending.live else "SIM"
        price_bit = ""
        if looks_like_btc_price(pending.open_price) and looks_like_btc_price(exit_price):
            price_bit = f"${pending.open_price:,.2f} -> ${exit_price:,.2f} | "
        await self.manager.send_to_session(session.session_id, {
            "type": "log",
            "message": f"{mode} {pending.signal} | {price_bit}{result} | {explanation} | P&L ${pnl:+.2f}",
            "level": level,
        })
        await self.manager.send_to_session(session.session_id, session.stats_payload())
        self._save_session(session)
        try:
            from .trade_journal import append_trade
            append_trade({
                "timestamp": datetime.now().isoformat(),
                "session_id": session.session_id,
                "direction": pending.signal,
                "amount": pending.stake,
                "entry_price": pending.open_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "result": result,
                "live": pending.live,
                "fee": pending.fee,
                "market": pending.market_title,
                "order_id": pending.order_id,
                "mode": "REAL" if pending.live else "SIM",
            })
        except Exception as exc:
            logger.warning(f"Journal append failed: {exc}")
        if self.risk_manager:
            tripped = self.risk_manager.record_settled(result, pnl)
            if tripped:
                await self.manager.send_to_session(session.session_id, {
                    "type": "log",
                    "message": tripped,
                    "level": "info",
                })
        try:
            from .strategy_manager import get_strategy_manager
            if result in ("WIN", "LOSS"):
                get_strategy_manager().record_trade_result(result == "WIN", pnl)
        except Exception:
            pass
        logger.info(f"[{session.session_id[:8]}] Settled {pending.signal} {result} ${pnl:+.2f}")
    
    async def _send_market(self):
        """Envía datos de mercado a todos los clientes (compartido)."""
        round_times = calculate_round_times(5, self._time_offset)
        remaining = int(round_times["seconds_remaining"])
        
        price = self._live_btc_price()
        if not looks_like_btc_price(price) and self.data_stream:
            raw = self.data_stream.get_current_price()
            if looks_like_btc_price(raw):
                price = float(raw)
        if not looks_like_btc_price(price) and getattr(self, "_price_history", None):
            price = self._price_history[-1]["price"]
        
        if looks_like_btc_price(price):
            if not hasattr(self, '_price_history'):
                self._price_history = []
            self._price_history.append({"time": datetime.now().isoformat(), "price": price})
            if len(self._price_history) > 300:
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
        payload = {
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
            "price_to_beat": None,
            "price_to_beat_source": "",
            "signal": self._last_prediction,
        }
        try:
            payload.update(self._price_to_beat_payload(
                self._market_book, int(round_times.get("round_number") or 0)
            ))
        except Exception as exc:
            logger.warning(f"Price to beat unavailable: {exc}")
        await self.manager.broadcast(payload)
        if remaining % 5 == 0:
            try:
                await self.refresh_market_book()
            except Exception as exc:
                logger.warning(f"Market book refresh failed: {exc}")
    
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
            session.pending_trade = pending_trade_from_dict(data.get("pending_trade"))
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
                    "pending_trade": session.pending_trade.to_dict() if session.pending_trade else None,
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
        try:
            from .updater import maybe_daily_update
            result = await maybe_daily_update(apply=False)
            if result.get("available"):
                logger.info(f"Update available: {result.get('latest')}")
                await bot.manager.broadcast({
                    "type": "update",
                    "available": True,
                    "current_version": result.get("current"),
                    "latest_version": result.get("latest"),
                    "release_notes": result.get("message") or "",
                })
        except Exception as exc:
            logger.warning(f"Daily update skipped: {exc}")
    
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
        payload = {"success": True, **companion.info(port=8080)}
        if companion.enabled:
            payload["listen"] = "0.0.0.0"
            payload["hint"] = "Quit and reopen so the app listens on LAN for the phone."
        else:
            payload["listen"] = "127.0.0.1"
        return payload

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
        await manager.send_to(websocket, session.status_payload(True))
        await manager.send_to(websocket, session.stats_payload())
        try:
            from .trade_journal import read_trades
            await manager.send_to(websocket, {"type": "journal", "trades": read_trades(80)})
        except Exception:
            pass
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
                    try:
                        await bot._send_market()
                    except Exception as exc:
                        logger.error(f"Market snapshot failed: {exc}")
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
    
    @app.get("/api/journal")
    async def get_journal(request: Request):
        from .trade_journal import read_trades
        return {"trades": read_trades(200)}

    @app.post("/api/settings/trading")
    async def update_trading_settings(request: Request):
        """Actualiza la configuración de trading."""
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can change trading settings"}, status_code=403)
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
        
        from .updater import update_is_snoozed
        prompt = bool(info.available) and not update_is_snoozed(info.latest_version)
        return {
            "available": info.available,
            "prompt": prompt,
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "release_notes": info.release_notes,
            "download_url": info.download_url
        }

    @app.post("/api/updates/later")
    async def snooze_update_prompt(request: Request):
        from .updater import snooze_update
        data = {}
        try:
            data = await request.json()
        except Exception:
            data = {}
        latest = str(data.get("latest_version") or data.get("version") or "")
        return snooze_update(latest)
    
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
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can change strategy"}, status_code=403)
        data = await request.json()
        sm = get_strategy_manager()
        success = sm.set_active_strategy(data.get("id", "default"))
        return {"success": success, "active": sm.active_strategy}
    
    @app.post("/api/strategies")
    async def create_strategy(request: Request):
        """Crea una nueva estrategia."""
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can change strategy"}, status_code=403)
        data = await request.json()
        sm = get_strategy_manager()
        strategy = sm.create_strategy(data.get("name", "Custom"), data)
        return {"success": True, "strategy": strategy.to_dict()}
    
    @app.put("/api/strategies/{strategy_id}")
    async def update_strategy(strategy_id: str, request: Request):
        """Actualiza una estrategia."""
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can change strategy"}, status_code=403)
        data = await request.json()
        sm = get_strategy_manager()
        strategy = sm.update_strategy(strategy_id, data)
        if strategy:
            return {"success": True, "strategy": strategy.to_dict()}
        return {"success": False, "error": "Strategy not found"}
    
    @app.delete("/api/strategies/{strategy_id}")
    async def delete_strategy(strategy_id: str, request: Request):
        """Elimina una estrategia."""
        if not _native_owner(request):
            return JSONResponse({"error": "Only the Mac owner can change strategy"}, status_code=403)
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


def run_dashboard(host: Optional[str] = None, port: int = 8080, config_path: Optional[str] = None):
    """Inicia el servidor del dashboard."""
    setup_logger("web_server", console_output=True)
    try:
        from .updater import purge_retired_installs
        purge_retired_installs()
    except Exception as exc:
        logger.warning(f"Leftover Playwright cleanup skipped: {exc}")
    
    config = load_config(config_path)
    app = create_app(config)
    bind_host = dashboard_bind_host(host)
    
    logger.info(f"Starting dashboard at http://{bind_host}:{port}")
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


# Crear instancia de app para usar con uvicorn directamente (ej: uvicorn src.web_server:app)
app = create_app()


if __name__ == "__main__":
    run_dashboard()
