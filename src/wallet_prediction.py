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

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import aiohttp

from .utils.logger import get_logger

logger = get_logger("wallet_prediction")

PREDICTION_API = "https://api.binance.com/sapi/v1/w3w/wallet/prediction"
USDT_WEI = 10**18
DEFAULT_FEE_BPS = 200
DEFAULT_SLIPPAGE_BPS = 500
MIN_BET_USDT = 1.5
MAX_BET_USDT = 100.0
MIN_SHARE_PRICE = 0.38
MAX_SHARE_PRICE = 0.62
MIN_WIN_PNL_RATIO = 0.25
BTC_PRICE_MIN = 1000.0
BTC_PRICE_MAX = 1_000_000.0
BSC_USDT = "0x55d398326f99059fF775485246999027B3197955"
BSC_CHAIN_ID = "56"
DEFAULT_PREDICTION_WALLET = "0x5FB045Ed0C5e906Ab4D60817bf022650f9749a0A"
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
    return normalize_evm_address(value) or DEFAULT_PREDICTION_WALLET


def short_wallet_label(address: str) -> str:
    text = normalize_evm_address(address) or str(address or "").strip()
    if not text:
        return "My Wallet"
    if len(text) > 12:
        return f"{text[:6]}…{text[-4:]}"
    return text


def match_wallet_row(wallets: List[Dict[str, Any]], preferred: str) -> Optional[Dict[str, Any]]:
    target = resolve_preferred_address(preferred)
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


def mismatch_wallet_error(preferred: str, listed: List[str], extra: str = "") -> str:
    others = [addr for addr in listed if addr and not same_address(addr, preferred)]
    shown = ", ".join(short_wallet_label(addr) for addr in others) or "none"
    text = (
        f"My Wallet {preferred} is not in Binance wallet/list (listed: {shown}). "
        "Those listed addresses are Binance's auto Prediction Account, not web3 My Wallet. "
        "REAL will not spend them."
    )
    extra = (extra or "").strip()
    return f"{text} {extra}".strip() if extra else text


def encode_balance_of(address: str) -> str:
    body = normalize_evm_address(address)[2:]
    return "0x70a08231" + body.lower().rjust(64, "0")


def decode_wei_to_usdt(hex_value: Any) -> float:
    text = str(hex_value or "0x0").strip()
    if text.startswith("0x"):
        text = text[2:]
    if not text:
        return 0.0
    try:
        return int(text, 16) / float(USDT_WEI)
    except ValueError:
        return 0.0


async def fetch_bsc_usdt(address: str) -> float:
    """On-chain USDT on BNB Smart Chain — the same balance web3.binance.com/prediction shows."""
    checksum = normalize_evm_address(address)
    if not checksum:
        return 0.0
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": BSC_USDT, "data": encode_balance_of(checksum)}, "latest"],
    }
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for rpc in BSC_RPCS:
            try:
                async with session.post(rpc, json=payload) as response:
                    if response.status != 200:
                        continue
                    data = await response.json()
                    if isinstance(data, dict) and data.get("result"):
                        return decode_wei_to_usdt(data.get("result"))
            except Exception as exc:
                logger.warning(f"BSC USDT read failed via {rpc}: {exc}")
    return 0.0


def clamp_bet_amount(value: Any, default: float = MIN_BET_USDT) -> float:
    """Wallet Prediction min is 1.5 USDT. Same floor for SIM and REAL."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = float(default)
    if amount <= 0:
        amount = float(default)
    return min(max(amount, MIN_BET_USDT), MAX_BET_USDT)


def normalize_share_price(value: Any, default: float = 0.5) -> float:
    """Quote averagePrice may be 0-1, percent, or wei-scaled."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number > 1e6:
        number = number / float(USDT_WEI)
    if number > 1.0:
        number = number / 100.0
    if number <= 0:
        return float(default)
    return min(max(number, 0.01), 0.99)


def looks_like_btc_price(value: Any) -> bool:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return False
    return BTC_PRICE_MIN <= price <= BTC_PRICE_MAX


def taker_fee(stake: float, share_price: float, fee_bps: int = DEFAULT_FEE_BPS) -> float:
    price = normalize_share_price(share_price)
    shares = float(stake) / price
    return (fee_bps / 10000.0) * min(price, 1.0 - price) * shares


def paper_fill(stake: float, share_price: float, fee_bps: int = DEFAULT_FEE_BPS) -> Dict[str, float]:
    price = normalize_share_price(share_price)
    fee = taker_fee(stake, price, fee_bps)
    cost = float(stake) + fee
    shares = float(stake) / price
    return {
        "share_price": price,
        "shares": shares,
        "fee": fee,
        "cost": cost,
        "win_pnl": shares - cost,
        "lose_pnl": -cost,
    }


def fill_from_quote(
    quote: Optional[Dict[str, Any]],
    stake: float,
    fallback_price: float,
    fee_bps: int = DEFAULT_FEE_BPS,
) -> Dict[str, float]:
    quote = quote if isinstance(quote, dict) else {}
    price = normalize_share_price(quote.get("averagePrice") or fallback_price, fallback_price)
    raw_out = quote.get("amountOut") or quote.get("tokenAmount") or quote.get("shares")
    try:
        shares_out = float(raw_out)
        if shares_out > 1e6:
            shares_out = shares_out / float(USDT_WEI)
        if shares_out > 0:
            derived = float(stake) / shares_out
            if 0.01 <= derived <= 0.99:
                price = derived
    except (TypeError, ValueError):
        pass
    return paper_fill(stake, price, fee_bps)


def tradable_edge(
    share_price: Any,
    stake: float,
    fee_bps: int = DEFAULT_FEE_BPS,
) -> Dict[str, Any]:
    """Skip 0.92 favorites / 0.03 longshots: $1.50 at 0.92 only pays ~$0.13."""
    price = normalize_share_price(share_price)
    fill = paper_fill(stake, price, fee_bps)
    in_band = MIN_SHARE_PRICE <= price <= MAX_SHARE_PRICE
    enough_payout = fill["win_pnl"] >= float(stake) * MIN_WIN_PNL_RATIO
    ok = in_band and enough_payout
    reason = ""
    if not ok:
        reason = (
            f"{price * 100:.0f}% pays ${fill['win_pnl']:.2f} "
            f"on ${float(stake):.2f} — need 38–62%"
        )
    return {"ok": ok, "reason": reason, "share_price": price, **fill}


def settle_direction(open_price: float, close_price: float) -> str:
    if close_price > open_price:
        return "UP"
    if close_price < open_price:
        return "DOWN"
    return "FLAT"


def settle_payout(signal: str, open_price: float, close_price: float, shares: float, cost: float) -> tuple:
    """Wallet rule: Up/Down vs range; exact tie resolves 50-50 (0.50 per share)."""
    actual = settle_direction(open_price, close_price)
    if actual == "FLAT":
        return actual, "PUSH", (float(shares) * 0.5) - float(cost)
    if actual == str(signal).upper():
        return actual, "WIN", float(shares) - float(cost)
    return actual, "LOSS", -float(cost)


def is_btc_short_window(topic: Dict[str, Any], minutes: int = 5) -> bool:
    slug = str(topic.get("slug") or "").lower()
    title = str(topic.get("title") or "").lower()
    symbol = str(topic.get("symbol") or "").upper()
    text = f"{slug} {title}"
    is_btc = symbol == "BTCUSDT" or "btc" in text
    window = (
        f"{minutes}m" in text
        or f"{minutes}-m" in text
        or f"{minutes} min" in text
        or f"{minutes}min" in text
        or f"{minutes}-min" in text
    )
    return is_btc and window


def pick_active_btc_window(topics: List[Any], minutes: int = 5, now_ms: Optional[int] = None) -> Optional[Dict[str, Any]]:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    matches: List[Dict[str, Any]] = []
    rows = topics if isinstance(topics, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not is_btc_short_window(row, minutes):
            continue
        status = str(row.get("status") or "").upper()
        if status and status not in ("REGISTERED", "OPEN", "ACTIVE"):
            continue
        end = int(row.get("endDate") or 0)
        if end and end <= now_ms:
            continue
        matches.append(row)
    if not matches:
        return None
    matches.sort(key=lambda item: int(item.get("endDate") or 0))
    return matches[0]


def as_probability(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1.0:
        number = number / 100.0
    if number <= 0:
        return default
    return min(max(number, 0.01), 0.99)


def topic_start_price(topic: Dict[str, Any]) -> float:
    """Binance 'Price to Beat' is the locked round open, never the live tick."""
    keys = (
        "startPrice",
        "openPrice",
        "priceToBeat",
        "strikePrice",
        "startValue",
        "initialPrice",
        "eventStartPrice",
        "lockPrice",
        "lockedPrice",
        "oraclePrice",
        "chainlinkPrice",
        "referencePrice",
        "targetPrice",
        "openOraclePrice",
        "resolutionOpenPrice",
        "start_price",
        "open_price",
        "price_to_beat",
    )
    blobs: List[Any] = [topic]
    for nested in ("event", "metadata", "market", "stats", "oracle", "resolution", "condition"):
        row = topic.get(nested)
        if isinstance(row, dict):
            blobs.append(row)
    for market in topic.get("markets") or []:
        if isinstance(market, dict):
            blobs.append(market)
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        for key in keys:
            raw = blob.get(key)
            if isinstance(raw, str):
                raw = raw.replace(",", "")
            try:
                price = float(raw)
            except (TypeError, ValueError):
                continue
            if looks_like_btc_price(price):
                return price
    return 0.0


def market_book(topic: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Binance Wallet Up/Down odds for the active BTC 5m market."""
    topic = topic or {}
    up = outcome_token(topic, "UP") or {}
    down = outcome_token(topic, "DOWN") or {}
    up_p = as_probability(up.get("price"), 0.5)
    down_p = as_probability(down.get("price"), 0.5)
    return {
        "up": up_p,
        "down": down_p,
        "up_odds": (1.0 / up_p) if up_p else 2.0,
        "down_odds": (1.0 / down_p) if down_p else 2.0,
        "price_to_beat": topic_start_price(topic),
        "title": str(topic.get("title") or "BTC Up or Down 5m"),
    }


def outcome_token(topic: Dict[str, Any], signal: str) -> Optional[Dict[str, Any]]:
    want = "UP" if str(signal).upper() == "UP" else "DOWN"
    markets = topic.get("markets") or []
    for market in markets:
        if not isinstance(market, dict):
            continue
        title = str(market.get("title") or "").upper()
        for outcome in market.get("outcomes") or []:
            if not isinstance(outcome, dict):
                continue
            name = str(outcome.get("name") or outcome.get("outcome") or "").upper()
            token_id = str(outcome.get("tokenId") or outcome.get("id") or "")
            if not token_id:
                continue
            price = as_probability(outcome.get("price") or outcome.get("chance") or 0.5)
            if title == want and name in ("YES", want):
                return {"token_id": token_id, "label": f"{title}:{name}", "price": price, "market": market}
            if name == want:
                return {"token_id": token_id, "label": name, "price": price, "market": market}
    return None


@dataclass
class PendingWalletTrade:
    session_id: str
    round_number: int
    signal: str
    stake: float
    open_price: float
    share_price: float
    shares: float
    fee: float
    cost: float
    live: bool = False
    order_id: str = ""
    market_title: str = ""
    balance_before: float = 0.0


@dataclass
class WalletPredictionClient:
    api_key: str
    api_secret: str
    recv_window: int = 60000
    preferred_address: str = ""
    _wallet: Dict[str, str] = field(default_factory=dict)
    _last_wallet_list_error: str = ""

    def _signed_query(self, extra: Optional[Dict[str, Any]] = None) -> str:
        params = dict(extra or {})
        params["timestamp"] = int(time.time() * 1000)
        params.setdefault("recvWindow", self.recv_window)
        query = urlencode(params, doseq=True)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={signature}"

    async def _request(self, method: str, path: str, extra: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        if not self.api_key or not self.api_secret:
            return 400, {"msg": "API Key and Secret are required"}
        signed = self._signed_query(extra)
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{PREDICTION_API}/{path.lstrip('/')}"
        async with aiohttp.ClientSession() as session:
            if method.upper() == "GET":
                ctx = session.get(f"{url}?{signed}", headers=headers)
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                ctx = session.post(url, headers=headers, data=signed)
            async with ctx as response:
                try:
                    payload = await response.json()
                except Exception:
                    payload = {"msg": (await response.text())[:220]}
                payload = unwrap_prediction_payload(payload)
                return response.status, payload

    async def search_markets(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        status, data = await self._request("GET", "market/search", {"query": query, "topK": min(limit, 50)})
        if status != 200:
            logger.warning(f"Wallet market search failed: {status} {data}")
            return []
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            rows = data.get("marketTopics") or data.get("data") or []
            return [row for row in rows if isinstance(row, dict)]
        return []

    async def market_detail(self, market_topic_id: Any) -> Dict[str, Any]:
        status, data = await self._request("GET", "market/detail", {"marketTopicId": market_topic_id})
        if status == 200 and isinstance(data, dict):
            return data
        logger.warning(f"Wallet market detail failed: {status} {data}")
        return {}

    async def find_btc_5m_market(self) -> Optional[Dict[str, Any]]:
        topics: List[Dict[str, Any]] = []
        for query in ("BTC 5m", "BTC 5 min Up or Down", "btc-price-5m"):
            topics.extend(await self.search_markets(query, 20))
        picked = pick_active_btc_window(topics, 5)
        if not picked:
            return None
        detail = await self.market_detail(picked.get("marketTopicId"))
        return detail or picked

    async def list_wallets(self) -> List[Dict[str, Any]]:
        status, data = await self._request("GET", "wallet/list")
        if status != 200:
            self._last_wallet_list_error = api_error_text(status, data)
            logger.warning(f"wallet/list failed: {self._last_wallet_list_error}")
            return []
        wallets = wallets_from_payload(data)
        if not wallets:
            self._last_wallet_list_error = (
                "wallet/list empty. Enable Prediction Trading and add this Mac's IP "
                "to the API key restriction (Binance requires IP to use that permission)."
            )
            logger.warning(f"wallet/list empty payload: {str(data)[:240]}")
        else:
            self._last_wallet_list_error = ""
        return wallets

    async def fetch_prediction_wallet(self) -> Dict[str, Any]:
        """Spend the listed Prediction Account. My Wallet is display-only unless listed."""
        my_wallet = resolve_preferred_address(self.preferred_address)
        wallets = await self.list_wallets()
        listed = [wallet_address_of(row) for row in wallets if wallet_address_of(row)]
        matched = pick_tradable_wallet_row(wallets, my_wallet)
        order_address = wallet_address_of(matched) if matched else ""
        wallet_id = wallet_id_of(matched) if matched else ""
        can_trade = bool(matched and wallet_id and order_address)
        label = spend_wallet_label(order_address, my_wallet) if order_address else "Prediction Account"
        spend_usdt = await fetch_bsc_usdt(order_address) if order_address else 0.0
        my_usdt = spend_usdt if same_address(order_address, my_wallet) else await fetch_bsc_usdt(my_wallet)
        error = ""
        if not can_trade:
            error = self._last_wallet_list_error or mismatch_wallet_error(my_wallet, listed)
        return {
            "wallet_id": wallet_id if can_trade else "",
            "wallet_address": order_address or my_wallet,
            "order_address": order_address if can_trade else "",
            "usdt": spend_usdt,
            "label": label,
            "network": "BNB Smart Chain",
            "listed_wallets": listed,
            "can_trade": can_trade,
            "my_wallet_address": my_wallet,
            "my_wallet_usdt": my_usdt,
            "error": error,
        }

    async def ensure_wallet(self, refresh: bool = True) -> Dict[str, Any]:
        cached = self._wallet.get("walletId") and self._wallet.get("orderAddress")
        if cached and not refresh:
            return self._wallet
        picked = await self.fetch_prediction_wallet()
        can_trade = bool(picked.get("can_trade"))
        order_address = str(picked.get("order_address") or "") if can_trade else ""
        self._wallet = {
            "walletId": str(picked.get("wallet_id") or "") if can_trade else "",
            "walletAddress": order_address or str(picked.get("wallet_address") or ""),
            "orderAddress": order_address,
            "usdt": float(picked.get("usdt") or 0),
            "label": str(picked.get("label") or "Prediction Account"),
            "can_trade": can_trade,
            "my_wallet_address": str(picked.get("my_wallet_address") or ""),
            "error": str(picked.get("error") or ""),
        }
        return self._wallet

    async def quote_and_buy(
        self,
        topic: Dict[str, Any],
        signal: str,
        stake_usdt: float,
        share_price: float,
    ) -> Dict[str, Any]:
        token = outcome_token(topic, signal)
        if not token:
            return {"success": False, "error": f"No Wallet outcome token for {signal}"}
        wallet = await self.ensure_wallet(refresh=True)
        order_address = str(wallet.get("orderAddress") or "")
        if not wallet.get("can_trade") or not wallet.get("walletId") or not order_address:
            preferred = resolve_preferred_address(self.preferred_address)
            return {
                "success": False,
                "error": wallet.get("error") or self._last_wallet_list_error or mismatch_wallet_error(preferred, []),
            }
        usdt = await fetch_bsc_usdt(order_address)
        wallet["usdt"] = usdt
        if usdt < float(stake_usdt):
            return {
                "success": False,
                "error": (
                    f"Prediction Account USDT ${usdt:.2f} is below ${float(stake_usdt):.2f}. "
                    "Use Transfer In on Binance Prediction → Portfolio. "
                    "My Wallet tokens are not this balance."
                ),
            }
        amount_in = str(int(round(float(stake_usdt) * USDT_WEI)))
        slippage = int(topic.get("slippageBps") or DEFAULT_SLIPPAGE_BPS)
        quote_req = {
            "walletAddress": order_address,
            "tokenId": token["token_id"],
            "side": "BUY",
            "amountIn": amount_in,
            "orderType": "MARKET",
            "slippageBps": slippage,
            "binanceChainId": str(topic.get("chainId") or BSC_CHAIN_ID),
            "fundingSource": "MPC",
        }
        if topic.get("marketTopicId") not in (None, ""):
            quote_req["marketTopicId"] = topic.get("marketTopicId")
        status, quote = await self._request("POST", "trade/get-quote", quote_req)
        if status != 200 or not isinstance(quote, dict) or not quote.get("quoteId"):
            msg = ""
            if isinstance(quote, dict):
                msg = str(quote.get("msg") or quote.get("message") or quote.get("error") or quote)
            return {"success": False, "error": msg or f"Quote failed HTTP {status}"}
        quoted = fill_from_quote(quote, stake_usdt, token.get("price") or share_price)
        edge = tradable_edge(quoted["share_price"], stake_usdt, int(topic.get("feeRateBps") or DEFAULT_FEE_BPS))
        if not edge["ok"]:
            return {
                "success": False,
                "error": f"Quote rejected: {edge['reason']}",
                "quote": quote,
                "share_price": quoted["share_price"],
            }
        place_req = {
            "walletAddress": order_address,
            "walletId": wallet["walletId"],
            "quoteId": quote.get("quoteId"),
            "slippageBps": quote.get("slippageBps") or slippage,
            "orderType": "MARKET",
            "timeInForce": "FOK",
            "fundingSource": "MPC",
            "accountType": PREDICTION_ACCOUNT_TYPE,
        }
        status, placed = await self._request("POST", "trade/place-order-bundle", place_req)
        if status != 200 or not isinstance(placed, dict) or (
            isinstance(placed, dict) and not (placed.get("orderId") or placed.get("data"))
            and (placed.get("code") not in (None, 0, "0", "000000"))
        ):
            alt = {
                "walletAddress": order_address,
                "walletId": wallet["walletId"],
                "quoteId": quote.get("quoteId"),
                "slippageBps": quote.get("slippageBps") or slippage,
                "orderType": "MARKET",
                "timeInForce": "FOK",
                "fundingSource": "MPC",
                "accountType": PREDICTION_ACCOUNT_TYPE,
            }
            alt_status, alt_placed = await self._request("POST", "trade/place-order", alt)
            if alt_status == 200 and isinstance(alt_placed, dict):
                status, placed = alt_status, alt_placed
        if status != 200 or not isinstance(placed, dict):
            msg = ""
            if isinstance(placed, dict):
                msg = str(placed.get("msg") or placed.get("message") or placed)
            return {"success": False, "error": msg or f"Order failed HTTP {status}", "quote": quote}
        order_id = str(placed.get("orderId") or placed.get("data", {}).get("orderId") or "")
        fill = fill_from_quote(quote, stake_usdt, token.get("price") or share_price)
        return {
            "success": True,
            "order_id": order_id,
            "quote": quote,
            "placed": placed,
            "account_type": str(wallet.get("label") or "Prediction Account"),
            "wallet_address": order_address,
            "share_price": fill["share_price"],
            "shares": fill["shares"],
            "fee": fill["fee"],
            "cost": fill["cost"],
            "token": token,
            "title": topic.get("title") or "",
        }
