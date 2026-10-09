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
    daily_loss_hit,
    harvest_amount,
    marked_equity,
    peak_drawdown_hit,
    fetch_spot_top_of_book,
    fetch_predict_fun_lock,
    fetch_spot_five_minute_open,
    resolve_stake,
    fill_from_quote,
    looks_like_btc_price,
    market_book,
    resolve_cached_lock,
    open_market_exposure,
    outcome_token,
    cut_loss_ready,
    live_equity_baseline,
    paper_fill,
    pending_trade_from_dict,
    sell_proceeds,
    settle_payout,
    skip_duplicate_entry,
    take_profit_ready,
    topic_id_of,
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
    live_available: float = 0.0
    live_open_value: float = 0.0
    pending_trade: Optional[PendingWalletTrade] = None
    wallet_start: float = 0.0
    wallet_day: str = ""
    wallet_day_start: float = 0.0
    wallet_day_peak: float = 0.0
    consecutive_losses: int = 0
    circuit_halted: bool = False
    session_started_at: str = ""
    session_elapsed: float = 0.0
    session_tick_at: float = 0.0
    session_peak: float = 0.0
    banked_session: float = 0.0
    banked_day: float = 0.0
    harvest_at: float = 0.0
    harvest_block_until: float = 0.0

    def session_elapsed_seconds(self) -> float:
        extra = 0.0
        tick = float(self.session_tick_at or 0)
        if self.running and not self.paused and tick:
            extra = max(0.0, time.time() - tick)
        return float(self.session_elapsed or 0) + extra

    def session_clock_payload(self) -> Dict[str, Any]:
        return {
            "session_elapsed": round(self.session_elapsed_seconds(), 1),
            "session_running": bool(self.running and not self.paused),
            "session_started_at": self.session_started_at or "",
            "wallet_start": 0.0 if self.simulation else float(self.wallet_start or 0),
        }
    
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
            **self.session_clock_payload(),
        }
    
    def stats_payload(self) -> dict:
        total = self.wins + self.losses
        winrate = (self.wins / max(1, total)) * 100
        kelly_pct = 0.0
        if total >= 5:
            p = self.wins / total
            kelly_pct = max(0, min(100, ((p * 0.95 - (1 - p)) / 0.95) * 100))
        profit_factor = (self.wins * 0.95) / max(0.01, self.losses * 1.0)
        try:
            from .user_settings import get_settings_manager
            trading = get_settings_manager().settings.trading
            if str(getattr(trading, "stake_mode", "percent")) == "fixed":
                stake_label = f"${float(trading.bet_amount):.2f}"
            else:
                stake_label = f"{float(trading.bet_percent):.0f}%"
        except Exception:
            stake_label = "3%"
        from .trade_journal import read_trades, summarize_trades
        journal = summarize_trades(read_trades(0), live=not self.simulation)
        if journal["trades"] or not self.simulation:
            total = journal["trades"]
   