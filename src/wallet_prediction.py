"""Binance Wallet → Predict.fun (web3.binance.com/en/prediction).

Two different Binance products exist. This module is only product B.

A) Binance Exchange Event Contracts — binance.com/prediction
   CEX binary options. No official bet API. Never used here.

B) Binance Wallet Prediction Markets — web3.binance.com/en/prediction
   Predict.fun markets on BNB Smart Chain. Official SAPI:
   https://api.binance.com/sapi/v1/w3w/wallet/prediction
   Official SAPI wallet/list returns the Prediction Account (MPC), not
   web3 My Wallet. REAL spends that listed account. My Wallet is Web3
   assets (Send/Receive) and is not used for Predict.fun orders.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import aiohttp

from .utils.logger import get_logger

logger = get_logger("wallet_prediction")

PREDICTION_API = "https://api.binance.com/sapi/v1/w3w/wallet/prediction"
USDT_WEI = 10**18
DEFAULT_FEE_BPS = 200
DEFAULT_SLIPPAGE_BPS = 500
SELL_SLIPPAGE_BPS = 1500
SELL_FRACTION = 0.995
MIN_BET_USDT = 1.0
MAX_BET_USDT = 100.0
DEFAULT_STAKE_MODE = "percent"
DEFAULT_BET_PERCENT = 3.0
MIN_BET_PERCENT = 1.0
MAX_BET_PERCENT = 8.0
DEFAULT_DAILY_LOSS_PCT = 20.0
DEFAULT_SESSION_LOCK_USD = 0.0
DEFAULT_SESSION_TRAIL_PCT = 0.0
MIN_SESSION_PEAK_PNL = 5.0
MAX_SESSION_LOCK_USD = 500.0
MAX_SESSION_TRAIL_PCT = 80.0
DEFAULT_WORKING_BANKROLL = 0.0
DEFAULT_HARVEST_MIN = 5.0
MAX_WORKING_BANKROLL = 500.0
MAX_HARVEST_MIN = 100.0
MIN_SHARE_PRICE = 0.20
# Allow lean favorites up to 65¢ — 62¢ still pays ~$0.50 on a $1 ticket.
# Block only true grinders (66¢+) that win pennies if they hit.
MAX_SHARE_PRICE = 0.65
MIN_WIN_PNL_RATIO = 0.35
DEFAULT_PEAK_DD_PCT = 15.0
# Mid-round scalp is -EV on 5m (second taker fee). Hold to Binance
# unless the ticket is almost resolved.
EXIT_MIN_HOLD_SECONDS = 75
TAKE_PROFIT_MIN_MARK = 0.90
TAKE_PROFIT_MIN_USD = 0.70
TAKE_PROFIT_MIN_SECONDS = 40
CUT_LOSS_MAX_MARK = 0.12
CUT_LOSS_MIN_SECONDS = 45
CUT_LOSS_MIN_SAVE = 0.20
BTC_PRICE_MIN = 1000.0
BTC_PRICE_MAX = 1_000_000.0
BSC_USDT = "0x55d398326f99059fF775485246999027B3197955"
BSC_CHAIN_ID = "56"
# Required by place-order-bundle even when spending the MPC Prediction Account.
# SPOT/FUNDING is the CEX fallback type; we do not send fundTransferAmount.
PREDICTION_ACCOUNT_TYPE = "SPOT"
BSC_RPCS = (
    "https://bsc-dataseed.binance.org/",
    "https://bsc-dataseed1.binance.org/",
    "https://bsc-dataseed2.binance.org/",
)


def normalize_evm_address(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith("0x") and len(text) == 40:
        text = "0x" + text
    if not text.startswith("0x") or len(text) != 42:
        return ""
    body = text[2:]
    if any(char not in "0123456789abcdefABCDEF" for char in body):
        return ""
    return "0x" + body


def same_address(left: Any, right: Any) -> bool:
    a = normalize_evm_address(left)
    b = normalize_evm_address(right)
    return bool(a) and a.lower() == b.lower()


def resolve_preferred_address(value: Any = None) -> str:
    """Optional override. Empty means spend the listed Prediction Account."""
    return normalize_evm_address(value)


def short_wallet_label(address: str) -> str:
    text = normalize_evm_address(address) or str(address or "").strip()
    if not text:
        return "My Wallet"
    if len(text) > 12:
        return f"{text[:6]}…{text[-4:]}"
    return text


def match_wallet_row(wallets: List[Dict[str, Any]], preferred: str) -> Optional[Dict[str, Any]]:
    target = normalize_evm_address(preferred)
    if not target:
        return None
    for row in wallets or []:
        if same_address(wallet_address_of(row), target):
            return row
    return None


def pick_tradable_wallet_row(wallets: List[Dict[str, Any]], preferred: str = "") -> Optional[Dict[str, Any]]:
    """Spend the official Prediction Account from wallet/list.

    If My Wallet is registered there, use it. Otherwise use the listed
    Prediction Account Binance created for Predict.fun.
    """
    matched = match_wallet_row(wallets, preferred)
    if matched and wallet_id_of(matched) and wallet_address_of(matched):
        return matched
    for row in wallets or []:
        if wallet_id_of(row) and wallet_address_of(row):
            return row
    return None


def spend_wallet_label(address: str, my_wallet: str = "") -> str:
    if same_address(address, my_wallet):
        return "My Wallet"
    return "Prediction Account"


def wallet_address_of(row: Dict[str, Any]) -> str:
    for key in ("walletAddress", "address", "evmAddress", "wallet_address"):
        address = normalize_evm_address(row.get(key))
        if address:
            return address
    return ""


def wallet_id_of(row: Dict[str, Any]) -> str:
    return str(row.get("walletId") or row.get("id") or row.get("wallet_id") or "").strip()


def wallets_from_payload(data: Any) -> List[Dict[str, Any]]:
    """wallet/list may be {wallets:[...]} or wrapped in data."""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("wallets", "items", "list"):
        rows = data.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    nested = data.get("data")
    if isinstance(nested, list):
        return [row for row in nested if isinstance(row, dict)]
    if isinstance(nested, dict):
        return wallets_from_payload(nested)
    return []


def unwrap_prediction_payload(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    inner = data.get("data")
    if inner is None:
        return data
    if isinstance(inner, (dict, list)) and ("code" in data or "success" in data or "msg" in data or "message" in data):
        return inner
    return data


def api_error_text(status: int, data: Any) -> str:
    if isinstance(data, dict):
        nested = data.get("data")
        msg = data.get("msg") or data.get("message") or data.get("error")
        if not msg and isinstance(nested, dict):
            msg = nested.get("msg") or nested.get("message")
        code = data.get("code")
        if msg:
            return f"HTTP {status} {code or ''} {msg}".strip()
        return f"HTTP {status} {str(data)[:180]}"
    return f"HTTP {status} {str(data)[:180]}"


def quote_id_of(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("quoteId", "quote_id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    nested = payload.get("data")
    if isinstance(nested, dict):
        return quote_id_of(nested)
    return ""


def order_id_of(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("orderId", "order_id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    nested = payload.get("data")
    if isinstance(nested, dict):
        return order_id_of(nested)
    return ""


def human_share_amount(qty: float) -> str:
    text = f"{float(qty):.8f}".rstrip("0").rstrip(".")
    return text or "0"


def sell_amount_candidates(qty: float) -> List[str]:
    """SELL amountIn is shares. Human first — wei 3e18 is what Binance calls SYSTEM_ERROR."""
    qty = float(qty or 0)
    if qty <= 0:
        return []
    seen: set[str] = set()
    out: List[str] = []
    values = [qty, qty * SELL_FRACTION]
    if qty >= 1 and abs(qty - round(qty)) < 1e-6:
        values.append(float(int(round(qty))))
    for value in values:
        human = human_share_amount(value)
        if human and human != "0" and human not in seen:
            seen.add(human)
            out.append(human)
    wei = str(int(round(qty * US