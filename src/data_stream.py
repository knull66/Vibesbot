"""
Módulo de streaming de datos en tiempo real.

Proporciona conexión WebSocket a Binance para capturar:
- Velas OHLCV en múltiples timeframes (1m, 5m)
- Libro de órdenes (Order Book Depth)
- Flujo de transacciones (Trade Tape)
"""
import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
import aiohttp
import numpy as np
import pandas as pd

from .config import DataStreamConfig
from .utils.logger import get_logger


logger = get_logger("data_stream")


@dataclass
class Candle:
    """Representa una vela OHLCV."""
    
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trades: int
    taker_buy_base: float
    taker_buy_quote: float
    is_closed: bool = False
    
    @classmethod
    def from_binance(cls, data: list) -> "Candle":
        """Crea una vela desde datos de Binance WebSocket."""
        return cls(
            timestamp=data[0],
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            volume=float(data[5]),
            close_time=data[6],
            quote_volume=float(data[7]),
            trades=data[8],
            taker_buy_base=float(data[9]),
            taker_buy_quote=float(data[10]),
            is_closed=False
        )
    
    @classmethod
    def from_ws_kline(cls, kline: dict) -> "Candle":
        """Crea una vela desde mensaje de kline WebSocket."""
        return cls(
            timestamp=kline["t"],
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            close_time=kline["T"],
            quote_volume=float(kline["q"]),
            trades=kline["n"],
            taker_buy_base=float(kline["V"]),
            taker_buy_quote=float(kline["Q"]),
            is_closed=kline["x"]
        )


@dataclass
class OrderBookLevel:
    """Representa un nivel del libro de órdenes."""
    price: float
    quantity: float


@dataclass
class OrderBook:
    """Representa el estado actual del libro de órdenes."""
    
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    last_update_id: int = 0
    timestamp: int = 0
    
    @property
    def best_bid(self) -> Optional[float]:
        """Mejor precio de compra."""
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        """Mejor precio de venta."""
        return self.asks[0].price if self.asks else None
    
    @property
    def mid_price(self) -> Optional[float]:
        """Precio medio."""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None
    
    @property
    def spread(self) -> Optional[float]:
        """Spread en términos absolutos."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    @property
    def spread_percent(self) -> Optional[float]:
        """Spread como porcentaje del mid price."""
        if self.mid_price and self.spread:
            return self.spread / self.mid_price
        return None
    
    def calculate_imbalance(self, levels: int = 5) -> float:
        """
        Calcula el Order Book Imbalance (OBI).
        
        Positivo = más presión de compra
        Negativo = más presión de venta
        
        Args:
            levels: Número de niveles a considerar
            
        Returns:
            OBI normalizado entre -1 y 1
        """
        bid_volume = sum(b.quantity for b in self.bids[:levels])
        ask_volume = sum(a.quantity for a in self.asks[:levels])
        
        total = bid_volume + ask_volume
        if total == 0:
            return 0.0
            
        return (bid_volume - ask_volume) / total
    
    def calculate_weighted_mid_price(self, levels: int = 5) -> Optional[float]:
        """
        Calcula el precio medio ponderado por volumen.
        
        Args:
            levels: Número de niveles a considerar
            
        Returns:
            Precio medio ponderado
        """
        if not self.bids or not self.asks:
            return None
            
        bid_value = sum(b.price * b.quantity for b in self.bids[:levels])
        bid_volume = sum(b.quantity for b in self.bids[:levels])
        
        ask_value = sum(a.price * a.quantity for a in self.asks[:levels])
        ask_volume = sum(a.quantity for a in self.asks[:levels])
        
        total_volume = bid_volume + ask_volume
        if total_volume == 0:
            return None
            
        return (bid_value + ask_value) / total_volume


@dataclass
class Trade:
    """Representa una transacción individual."""
    
    id: int
    price: float
    quantity: float
    buyer_maker: bool
    timestamp: int
    
    @property
    def is_buy(self) -> bool:
        """True si es una compra agresiva (taker buy)."""
        return not self.buyer_maker
    
    @property
    def value(self) -> float:
        """Valor total de la transacción."""
        return self.price * self.quantity


class DataStream:
    """
    Gestor principal de streams de datos de Binance.
    
    Mantiene conexiones WebSocket para recibir datos en tiempo real
    y proporciona interfaces para acceder a los datos procesados.
    """
    
    def __init__(self, config: Optional[DataStreamConfig] = None):
        self.config = config or DataStreamConfig()
        
        self._candles: dict[str, deque[Candle]] = {}
        self._order_book = OrderBook()
        self._trades: deque[Trade] = deque(maxlen=self.config.trades_buffer_size)
        
        self._ws_session: Optional[aiohttp.ClientSession] = None
        self._ws_connections: list[aiohttp.ClientWebSocketResponse] = []
        self._running = False
        self._reconnect_count = 0
        
        self._callbacks: dict[str, list[Callable]] = {
            "candle": [],
            "orderbook": [],
            "trade": [],
            "error": []
        }
        
        for tf in self.config.timeframes:
            self._candles[tf] = deque(maxlen=500)
    
    @property
    def base_ws_url(self) -> str:
        """URL base para WebSocket."""
        if self.config.use_testnet:
            return "wss://testnet.binance.vision/ws"
        return "wss://fstream.binance.com/ws"
    
    @property
    def base_api_url(self) -> str:
        """URL base para API REST."""
        if self.config.use_testnet:
            return "https://testnet.binance.vision/api/v3"
        return "https://data-api.binance.vision/api/v3"
    
    def on_candle(self, callback: Callable[[str, Candle], None]) -> None:
        """Registra callback para nuevas velas."""
        self._callbacks["candle"].append(callback)
    
    def on_orderbook(self, callback: Callable[[OrderBook], None]) -> None:
        """Registra callback para actualizaciones del order book."""
        self._callbacks["orderbook"].append(callback)
    
    def on_trade(self, callback: Callable[[Trade], None]) -> None:
        """Registra callback para nuevos trades."""
        self._callbacks["trade"].append(callback)
    
    def on_error(self, callback: Callable[[Exception], None]) -> None:
        """Registra callback para errores."""
        self._callbacks["error"].append(callback)
    
    async def _emit(self, event: str, *args) -> None:
        """Emite un evento a todos los callbacks registrados."""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args)
                else:
                    callback(*args)
            except Exception as e:
                logger.error(f"Error in callback for {event}: {e}")
    
    async def start(self) -> None:
        """Inicia todos los streams de datos."""
        if self._running:
            logger.warning("DataStream already running")
            return
        
        self._running = True
        logger.info("Starting data streams...")
        
        self._ws_session = aiohttp.ClientSession()
        
        await self._load_historical_candles()
        
        streams = []
        
        symbol = self.config.symbol.replace("/", "").lower()
        
        for tf in self.config.timeframes:
            streams.append(f"{symbol}@kline_{tf}")
        
        streams.append(f"{symbol}@depth{self.config.orderbook_depth}@100ms")
        streams.append(f"{symbol}@aggTrade")
        
        combined_stream = "/".join(streams)
        ws_url = f"{self.base_ws_url}/{combined_stream}"
        
        asyncio.create_task(self._run_websocket(ws_url))
    
    async def stop(self) -> None:
        """Detiene todos los streams de datos."""
        self._running = False
        
        for ws in self._ws_connections:
            await ws.close()
        self._ws_connections.clear()
        
        if self._ws_session:
            await self._ws_session.close()
            self._ws_session = None
        
        logger.info("Data streams stopped")
    
    async def _load_historical_candles(self) -> None:
        """Carga velas históricas al iniciar."""
        symbol = self.config.symbol.replace("/", "")
        
        async with aiohttp.ClientSession() as session:
            for tf in self.config.timeframes:
                url = f"{self.base_api_url}/klines"
                params = {
                    "symbol": symbol,
                    "interval": tf,
                    "limit": self.config.prediction.lookback_periods if hasattr(self.config, 'prediction') else 100
                }
                
                try:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            for kline in data:
                                candle = Candle.from_binance(kline)
                                candle.is_closed = True
                                self._candles[tf].append(candle)
                            logger.info(f"Loaded {len(data)} historical candles for {tf}")
                        else:
                            logger.error(f"Failed to load historical candles: {response.status}")
                except Exception as e:
                    logger.error(f"Error loading historical candles: {e}")
    
    async def _run_websocket(self, url: str) -> None:
        """Mantiene la conexión WebSocket activa."""
        while self._running:
            try:
                async with self._ws_session.ws_connect(
                    url,
                    heartbeat=self.config.ws_ping_interval,
                    timeout=aiohttp.ClientWSTimeout(ws_close=self.config.ws_ping_timeout)
                ) as ws:
                    self._ws_connections.append(ws)
                    self._reconnect_count = 0
                    logger.info("WebSocket connected")
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._process_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WebSocket error: {ws.exception()}")
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            logger.warning("WebSocket closed")
                            break
                            
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await self._emit("error", e)
                
            if self._running:
                self._reconnect_count += 1
                if self._reconnect_count > self.config.ws_max_reconnect_attempts:
                    logger.critical("Max reconnection attempts reached")
                    self._running = False
                    break
                    
                delay = min(self.config.ws_reconnect_delay * self._reconnect_count, 60)
                logger.info(f"Reconnecting in {delay} seconds...")
                await asyncio.sleep(delay)
    
    async def _process_message(self, data: str) -> None:
        """Procesa un mensaje recibido del WebSocket."""
        try:
            msg = json.loads(data)
            
            if "e" in msg:
                event_type = msg["e"]
                
                if event_type == "kline":
                    await self._handle_kline(msg)
                elif event_type == "depthUpdate":
                    await self._handle_depth(msg)
                elif event_type == "aggTrade":
                    await self._handle_trade(msg)
                    
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    async def _handle_kline(self, msg: dict) -> None:
        """Procesa actualización de vela."""
        kline = msg["k"]
        interval = kline["i"]
        candle = Candle.from_ws_kline(kline)
        
        if interval in self._candles:
            candles = self._candles[interval]
            
            if candles and candles[-1].timestamp == candle.timestamp:
                candles[-1] = candle
            else:
                candles.append(candle)
            
            if candle.is_closed:
                await self._emit("candle", interval, candle)
    
    async def _handle_depth(self, msg: dict) -> None:
        """Procesa actualización del libro de órdenes."""
        self._order_book.bids = [
            OrderBookLevel(float(price), float(qty))
            for price, qty in msg.get("b", [])
        ]
        self._order_book.asks = [
            OrderBookLevel(float(price), float(qty))
            for price, qty in msg.get("a", [])
        ]
        self._order_book.last_update_id = msg.get("u", 0)
        self._order_book.timestamp = msg.get("E", 0)
        
        await self._emit("orderbook", self._order_book)
    
    async def _handle_trade(self, msg: dict) -> None:
        """Procesa nueva transacción."""
        trade = Trade(
            id=msg["a"],
            price=float(msg["p"]),
            quantity=float(msg["q"]),
            buyer_maker=msg["m"],
            timestamp=msg["E"]
        )
        
        self._trades.append(trade)
        await self._emit("trade", trade)
    
    def get_candles(self, timeframe: str) -> list[Candle]:
        """Retorna las velas del timeframe especificado."""
        return list(self._candles.get(timeframe, []))
    
    def get_candles_df(self, timeframe: str) -> pd.DataFrame:
        """Retorna las velas como DataFrame de pandas."""
        candles = self.get_candles(timeframe)
        if not candles:
            return pd.DataFrame()
        
        return pd.DataFrame([
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "quote_volume": c.quote_volume,
                "trades": c.trades,
                "taker_buy_base": c.taker_buy_base,
                "taker_buy_quote": c.taker_buy_quote,
            }
            for c in candles if c.is_closed
        ])
    
    def get_order_book(self) -> OrderBook:
        """Retorna el estado actual del libro de órdenes."""
        return self._order_book
    
    def get_recent_trades(self, count: Optional[int] = None) -> list[Trade]:
        """Retorna las transacciones recientes."""
        trades = list(self._trades)
        if count:
            return trades[-count:]
        return trades
    
    def get_current_price(self) -> Optional[float]:
        """Retorna el precio actual (mid price del order book o último trade)."""
        if self._order_book.mid_price:
            return self._order_book.mid_price
        if self._trades:
            return self._trades[-1].price
        
        for tf in self.config.timeframes:
            candles = self._candles.get(tf, [])
            if candles:
                return candles[-1].close
        
        return None
    
    def calculate_trade_flow(self, window_seconds: int = 60) -> dict:
        """
        Calcula métricas de flujo de transacciones.
        
        Args:
            window_seconds: Ventana de tiempo en segundos
            
        Returns:
            Diccionario con métricas de flujo
        """
        now = datetime.now(timezone.utc).timestamp() * 1000
        cutoff = now - (window_seconds * 1000)
        
        recent_trades = [t for t in self._trades if t.timestamp >= cutoff]
        
        if not recent_trades:
            return {
                "buy_volume": 0.0,
                "sell_volume": 0.0,
                "buy_value": 0.0,
                "sell_value": 0.0,
                "buy_count": 0,
                "sell_count": 0,
                "net_flow": 0.0,
                "flow_imbalance": 0.0,
                "vwap": 0.0,
            }
        
        buy_trades = [t for t in recent_trades if t.is_buy]
        sell_trades = [t for t in recent_trades if not t.is_buy]
        
        buy_volume = sum(t.quantity for t in buy_trades)
        sell_volume = sum(t.quantity for t in sell_trades)
        buy_value = sum(t.value for t in buy_trades)
        sell_value = sum(t.value for t in sell_trades)
        
        total_volume = buy_volume + sell_volume
        total_value = buy_value + sell_value
        
        flow_imbalance = 0.0
        if total_volume > 0:
            flow_imbalance = (buy_volume - sell_volume) / total_volume
        
        vwap = 0.0
        if total_volume > 0:
            vwap = total_value / total_volume
        
        return {
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "buy_value": buy_value,
            "sell_value": sell_value,
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "net_flow": buy_volume - sell_volume,
            "flow_imbalance": flow_imbalance,
            "vwap": vwap,
        }
    
    def get_volatility(self, timeframe: str = "1m", periods: int = 20) -> float:
        """
        Calcula la volatilidad reciente.
        
        Args:
            timeframe: Timeframe a usar
            periods: Número de periodos
            
        Returns:
            Volatilidad como desviación estándar de retornos
        """
        candles = self.get_candles(timeframe)
        if len(candles) < periods + 1:
            return 0.0
        
        closes = [c.close for c in candles[-(periods + 1):]]
        returns = np.diff(np.log(closes))
        
        return float(np.std(returns))


async def create_data_stream(config: Optional[DataStreamConfig] = None) -> DataStream:
    """
    Factory function para crear e iniciar un DataStream.
    
    Args:
        config: Configuración opcional
        
    Returns:
        DataStream iniciado y listo para usar
    """
    stream = DataStream(config)
    await stream.start()
    return stream
