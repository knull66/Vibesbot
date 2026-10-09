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
            await self.send_to(connec