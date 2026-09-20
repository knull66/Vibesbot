"""
Dashboard Backtest - Backtesting integrado para el dashboard.

Permite probar estrategias con datos históricos.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import aiohttp

from .strategy_manager import StrategyConfig, get_strategy_manager
from .utils.logger import get_logger

logger = get_logger("dashboard_backtest")


@dataclass
class BacktestResult:
    """Resultado de un backtest."""
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    best_trade: float
    worst_trade: float
    profit_factor: float
    trades: List[Dict]
    equity_curve: List[float]
    
    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "period": {
                "start": self.start_date,
                "end": self.end_date
            },
            "capital": {
                "initial": self.initial_capital,
                "final": self.final_capital,
                "return_pct": ((self.final_capital - self.initial_capital) / self.initial_capital) * 100
            },
            "trades": {
                "total": self.total_trades,
                "wins": self.wins,
                "losses": self.losses,
                "win_rate": self.win_rate
            },
            "metrics": {
                "total_pnl": self.total_pnl,
                "max_drawdown": self.max_drawdown,
                "best_trade": self.best_trade,
                "worst_trade": self.worst_trade,
                "profit_factor": self.profit_factor
            },
            "equity_curve": self.equity_curve[-100:],  # Últimos 100 puntos
            "recent_trades": self.trades[-20:]  # Últimos 20 trades
        }


class DashboardBacktester:
    """Backtester integrado para el dashboard."""
    
    API_URL = "https://data-api.binance.vision/api/v3"
    
    def __init__(self):
        self.is_running = False
        self.progress = 0
        self.current_result: Optional[BacktestResult] = None
    
    async def fetch_historical_data(
        self, 
        symbol: str = "BTCUSDT",
        interval: str = "5m",
        days: int = 7
    ) -> List[Dict]:
        """Obtiene datos históricos de Binance."""
        
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        
        all_candles = []
        
        try:
            async with aiohttp.ClientSession() as session:
                current_start = start_time
                
                while current_start < end_time:
                    url = f"{self.API_URL}/klines"
                    params = {
                        "symbol": symbol,
                        "interval": interval,
                        "startTime": current_start,
                        "endTime": end_time,
                        "limit": 1000
                    }
                    
                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            logger.error(f"API error: {response.status}")
                            break
                        
                        data = await response.json()
                        
                        if not data:
                            break
                        
                        for candle in data:
                            all_candles.append({
                                "timestamp": candle[0],
                                "open": float(candle[1]),
                                "high": float(candle[2]),
                                "low": float(candle[3]),
                                "close": float(candle[4]),
                                "volume": float(candle[5])
                            })
                        
                        current_start = data[-1][0] + 1
                        
                        if len(data) < 1000:
                            break
                        
                        await asyncio.sleep(0.1)
            
            logger.info(f"Fetched {len(all_candles)} candles")
            return all_candles
            
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return []
    
    def calculate_indicators(self, candles: List[Dict], strategy: StrategyConfig) -> List[Dict]:
        """Calcula indicadores técnicos para cada candle."""
        import pandas as pd
        import numpy as np
        
        df = pd.DataFrame(candles)
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=strategy.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=strategy.rsi_period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = df['close'].ewm(span=strategy.macd_fast, adjust=False).mean()
        exp2 = df['close'].ewm(span=strategy.macd_slow, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=strategy.macd_signal, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(window=strategy.bb_period).mean()
        df['bb_std'] = df['close'].rolling(window=strategy.bb_period).std()
        df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * strategy.bb_std)
        df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * strategy.bb_std)
        
        # Momentum
        df['momentum'] = df['close'] - df['close'].shift(strategy.momentum_period)
        
        return df.to_dict('records')
    
    def generate_signal(self, candle: Dict, strategy: StrategyConfig) -> tuple:
        """Genera señal basada en la estrategia."""
        
        rsi = candle.get('rsi', 50)
        macd_hist = candle.get('macd_hist', 0)
        close = candle.get('close', 0)
        bb_upper = candle.get('bb_upper', close)
        bb_lower = candle.get('bb_lower', close)
        momentum = candle.get('momentum', 0)
        
        # Calcular señales individuales
        signals = []
        total_weight = 0
        
        # RSI Signal
        if strategy.rsi_weight > 0:
            if rsi < strategy.rsi_oversold:
                signals.append(('UP', strategy.rsi_weight))
            elif rsi > strategy.rsi_overbought:
                signals.append(('DOWN', strategy.rsi_weight))
            total_weight += strategy.rsi_weight
        
        # MACD Signal
        if strategy.macd_weight > 0:
            if macd_hist > 0:
                signals.append(('UP', strategy.macd_weight))
            else:
                signals.append(('DOWN', strategy.macd_weight))
            total_weight += strategy.macd_weight
        
        # Bollinger Signal
        if strategy.bollinger_weight > 0:
            if close < bb_lower:
                signals.append(('UP', strategy.bollinger_weight))
            elif close > bb_upper:
                signals.append(('DOWN', strategy.bollinger_weight))
            total_weight += strategy.bollinger_weight
        
        # Momentum Signal
        if strategy.momentum_weight > 0:
            if momentum > 0:
                signals.append(('UP', strategy.momentum_weight))
            else:
                signals.append(('DOWN', strategy.momentum_weight))
            total_weight += strategy.momentum_weight
        
        # Calcular señal final
        if not signals or total_weight == 0:
            return 'WAIT', 0.5
        
        up_weight = sum(w for s, w in signals if s == 'UP')
        down_weight = sum(w for s, w in signals if s == 'DOWN')
        
        if up_weight > down_weight:
            confidence = up_weight / total_weight
            return 'UP', confidence
        elif down_weight > up_weight:
            confidence = down_weight / total_weight
            return 'DOWN', confidence
        else:
            return 'WAIT', 0.5
    
    async def run_backtest(
        self,
        strategy: Optional[StrategyConfig] = None,
        days: int = 7,
        initial_capital: float = 100.0,
        bet_amount: float = 1.0,
        progress_callback=None
    ) -> BacktestResult:
        """Ejecuta un backtest completo."""
        
        self.is_running = True
        self.progress = 0
        
        if strategy is None:
            strategy = get_strategy_manager().get_active_strategy()
        
        # Obtener datos
        if progress_callback:
            await progress_callback(5, "Fetching historical data...")
        
        candles = await self.fetch_historical_data("BTCUSDT", "5m", days)
        
        if len(candles) < 50:
            self.is_running = False
            raise ValueError("Not enough data for backtest")
        
        # Calcular indicadores
        if progress_callback:
            await progress_callback(20, "Calculating indicators...")
        
        candles_with_indicators = self.calculate_indicators(candles, strategy)
        
        # Simular trades
        capital = initial_capital
        trades = []
        equity_curve = [capital]
        max_equity = capital
        max_drawdown = 0
        
        # Iterar cada 5 minutos (simular rondas de Binance Prediction)
        total_candles = len(candles_with_indicators)
        
        for i, candle in enumerate(candles_with_indicators[50:], start=50):
            # Actualizar progreso
            progress = 20 + int((i / total_candles) * 70)
            self.progress = progress
            
            if progress_callback and i % 100 == 0:
                await progress_callback(progress, f"Processing candle {i}/{total_candles}")
            
            # Generar señal
            signal, confidence = self.generate_signal(candle, strategy)
            
            # Solo tradear si hay confianza suficiente
            if signal in ['UP', 'DOWN'] and confidence >= strategy.min_confidence:
                entry_price = candle['close']
                
                # Obtener precio de cierre (siguiente candle)
                if i + 1 < total_candles:
                    exit_price = candles_with_indicators[i + 1]['close']
                    
                    # Determinar resultado
                    price_went_up = exit_price > entry_price
                    is_win = (signal == 'UP' and price_went_up) or (signal == 'DOWN' and not price_went_up)
                    
                    # Calcular P&L
                    pnl = bet_amount * 0.95 if is_win else -bet_amount
                    capital += pnl
                    
                    trades.append({
                        "timestamp": datetime.fromtimestamp(candle['timestamp'] / 1000).isoformat(),
                        "signal": signal,
                        "confidence": confidence,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "result": "WIN" if is_win else "LOSS",
                        "pnl": pnl,
                        "capital_after": capital
                    })
                    
                    equity_curve.append(capital)
                    
                    # Track drawdown
                    if capital > max_equity:
                        max_equity = capital
                    current_drawdown = ((max_equity - capital) / max_equity) * 100
                    if current_drawdown > max_drawdown:
                        max_drawdown = current_drawdown
        
        # Calcular métricas
        wins = len([t for t in trades if t['result'] == 'WIN'])
        losses = len([t for t in trades if t['result'] == 'LOSS'])
        total_trades = len(trades)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        pnls = [t['pnl'] for t in trades]
        best_trade = max(pnls) if pnls else 0
        worst_trade = min(pnls) if pnls else 0
        
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        if progress_callback:
            await progress_callback(100, "Backtest complete!")
        
        self.is_running = False
        self.progress = 100
        
        result = BacktestResult(
            strategy_name=strategy.name,
            start_date=datetime.fromtimestamp(candles[0]['timestamp'] / 1000).isoformat(),
            end_date=datetime.fromtimestamp(candles[-1]['timestamp'] / 1000).isoformat(),
            initial_capital=initial_capital,
            final_capital=capital,
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            total_pnl=capital - initial_capital,
            max_drawdown=max_drawdown,
            best_trade=best_trade,
            worst_trade=worst_trade,
            profit_factor=profit_factor,
            trades=trades,
            equity_curve=equity_curve
        )
        
        self.current_result = result
        return result


# Singleton
_backtester: Optional[DashboardBacktester] = None

def get_backtester() -> DashboardBacktester:
    """Obtiene el backtester."""
    global _backtester
    if _backtester is None:
        _backtester = DashboardBacktester()
    return _backtester
