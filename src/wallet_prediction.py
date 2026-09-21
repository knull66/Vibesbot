"""Binance Wallet Prediction Markets (official SAPI)."""
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
BSC_USDT = "0x55d398326f99059fF775485246999027B3197955"
BSC_CHAIN_ID = "56"
DEFAULT_PREDICTION_WALLET = "0x5FB045Ed0C5e906Ab4D60817bf022650f9749a0A"
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


def wallet_address_of(row: Dict[str, Any]) -> str:
    for key in ("walletAddress", "address", "evmAddress", "wallet_address"):
        address = normalize_evm_address(row.get(key))
        if address:
            return address
    return ""


def wallet_id_of(row: Dict[str, Any]) -> str:
    return str(row.get("walletId") or row.get("id") or row.get("wallet_id") or "").strip()


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


def taker_fee(stake: float, share_price: float, fee_bps: int = DEFAULT_FEE_BPS) -> float:
    price = min(max(float(share_price), 0.01), 0.99)
    shares = float(stake) / price
    return (fee_bps / 10000.0) * min(price, 1.0 - price) * shares


def paper_fill(stake: float, share_price: float, fee_bps: int = DEFAULT_FEE_BPS) -> Dict[str, float]:
    price = min(max(float(share_price), 0.01), 0.99)
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
    keys = (
        "startPrice",
        "openPrice",
        "priceToBeat",
        "strikePrice",
        "startValue",
        "initialPrice",
        "eventStartPrice",
    )
    blobs: List[Any] = [topic]
    for nested in ("event", "metadata", "market", "stats"):
        row = topic.get(nested)
        if isinstance(row, dict):
            blobs.append(row)
    for market in topic.get("markets") or []:
        if isinstance(market, dict):
            blobs.append(market)
    for blob in blobs:
        for key in keys:
            raw = blob.get(key) if isinstance(blob, dict) else None
            try:
                price = float(raw)
            except (TypeError, ValueError):
                continue
            if price > 0:
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


@dataclass
class WalletPredictionClient:
    api_key: str
    api_secret: str
    recv_window: int = 10000
    preferred_address: str = ""
    _wallet: Dict[str, str] = field(default_factory=dict)

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

    async def payment_options(self, account_type: Optional[str] = None) -> List[Dict[str, Any]]:
        extra = {"type": account_type} if account_type else None
        status, data = await self._request("GET", "balance/payment-options", extra)
        if status != 200:
            return []
        items = data.get("items") if isinstance(data, dict) else data
        return [row for row in (items or []) if isinstance(row, dict)]

    async def fetch_prediction_wallet(self) -> Dict[str, Any]:
        """Always use the pinned Binance Wallet. Never pick another address by USDT."""
        preferred = resolve_preferred_address(self.preferred_address)
        wallets = await self.list_wallets()
        matched = match_wallet_row(wallets, preferred)
        usdt = await fetch_bsc_usdt(preferred)
        error = ""
        if not matched and wallets:
            error = "My Wallet is not in Binance wallet/list; reading BSC USDT on the pinned address."
        elif not wallets and not self.api_key:
            error = "API key required to place orders; BSC USDT is still read on-chain."
        return {
            "wallet_id": wallet_id_of(matched) if matched else "",
            "wallet_address": preferred,
            "usdt": usdt,
            "label": "My Wallet",
            "network": "BNB Smart Chain",
            "error": error,
        }

    async def fetch_prediction_accounts(self) -> Dict[str, Any]:
        picked = await self.fetch_prediction_wallet()
        wallets = await self.list_wallets()
        items = []
        if picked.get("wallet_address"):
            items.append({
                "accountType": "Prediction BSC",
                "availableBalanceDisplay": picked.get("usdt") or 0.0,
                "walletAddress": picked.get("wallet_address"),
                "enabled": True,
            })
        return {
            "items": items,
            "wallets": wallets,
            "picked": picked,
            "error": picked.get("error") or "",
        }

    async def list_wallets(self) -> List[Dict[str, Any]]:
        status, data = await self._request("GET", "wallet/list")
        if status != 200:
            return []
        wallets = data.get("wallets") if isinstance(data, dict) else data
        return [row for row in (wallets or []) if isinstance(row, dict)]

    async def ensure_wallet(self, refresh: bool = True) -> Dict[str, Any]:
        cached = self._wallet.get("walletId") and self._wallet.get("walletAddress")
        if cached and not refresh:
            return self._wallet
        picked = await self.fetch_prediction_wallet()
        self._wallet = {
            "walletId": str(picked.get("wallet_id") or ""),
            "walletAddress": str(picked.get("wallet_address") or ""),
            "usdt": float(picked.get("usdt") or 0),
            "label": str(picked.get("label") or "My Wallet"),
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
        if not wallet.get("walletId") or not wallet.get("walletAddress"):
            return {"success": False, "error": "No Binance Wallet found for Prediction Markets"}
        usdt = await fetch_bsc_usdt(wallet["walletAddress"])
        wallet["usdt"] = usdt
        if usdt < float(stake_usdt):
            return {
                "success": False,
                "error": (
                    f"Prediction BSC USDT ${usdt:.2f} is below ${float(stake_usdt):.2f}. "
                    f"Send USDT on BNB Smart Chain to {short_wallet_label(wallet['walletAddress'])}."
                ),
            }
        amount_in = str(int(round(float(stake_usdt) * USDT_WEI)))
        slippage = int(topic.get("slippageBps") or DEFAULT_SLIPPAGE_BPS)
        quote_req = {
            "walletAddress": wallet["walletAddress"],
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
        place_req = {
            "walletAddress": wallet["walletAddress"],
            "walletId": wallet["walletId"],
            "quoteId": quote.get("quoteId"),
            "slippageBps": quote.get("slippageBps") or slippage,
            "orderType": "MARKET",
            "timeInForce": "FOK",
            "fundingSource": "MPC",
        }
        status, placed = await self._request("POST", "trade/place-order-bundle", place_req)
        if status != 200 or not isinstance(placed, dict):
            msg = ""
            if isinstance(placed, dict):
                msg = str(placed.get("msg") or placed.get("message") or placed)
            return {"success": False, "error": msg or f"Order failed HTTP {status}", "quote": quote}
        order_id = str(placed.get("orderId") or placed.get("data", {}).get("orderId") or "")
        avg = float(quote.get("averagePrice") or token["price"] or share_price or 0.5)
        return {
            "success": True,
            "order_id": order_id,
            "quote": quote,
            "placed": placed,
            "account_type": "My Wallet",
            "wallet_address": wallet["walletAddress"],
            "share_price": avg,
            "token": token,
            "title": topic.get("title") or "",
        }
