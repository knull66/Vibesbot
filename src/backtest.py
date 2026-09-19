"""
Sistema de backtesting para evaluar estrategias de trading.

Permite simular el rendimiento del modelo sobre datos históricos
antes de ejecutar en vivo.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
import argparse
import json

import numpy as np
import pandas as pd
import aiohttp

from .config import Config, load_config, SizingStrategy
from .predictor import Predictor, FeatureGenerator, PredictionModel, Signal, ModelType
from .risk_manager import PositionSizer
from .utils.logger import setup_logger, get_logger


logger = get_logger("backtest")


@dataclass
class BacktestTrade:
    """Registro de una operación en backtest."""
    
    timestamp: datetime
    direction: str
    amount: float
    entry_price: float
    exit_price: float
    pnl: float
    is_win: bool
    confidence: float
    cumulative_pnl: float = 0.0


@dataclass
class BacktestResult:
    """Resultado completo de un backtest."""
    
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    
    total_trades: int
    winning_trades: int
    losing_trades: int
    
    total_pnl: float
    max_drawdown: float
    max_drawdown_percent: float
    
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    
    max_consecutive_wins: int
    max_consecutive_losses: int
    
    trades: List[BacktestTrade] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convierte el resultado a diccionario."""
        return {
            "period": {
                "start": self.start_date.isoformat(),
                "end": self.end_date.isoformat(),
            },
            "capital": {
                "initial": self.initial_capital,
                "final": self.final_capital,
                "return_pct": ((self.final_capital / self.initial_capital) - 1) * 100,
            },
            "trades": {
                "total": self.total_trades,
                "winning": self.winning_trades,
                "losing": self.losing_trades,
                "win_rate": self.win_rate,
            },
            "performance": {
                "total_pnl": self.total_pnl,
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_percent,
                "profit_factor": self.profit_factor,
                "sharpe_ratio": self.sharpe_ratio,
            },
            "averages": {
                "trade_pnl": self.avg_trade_pnl,
                "win": self.avg_win,
                "loss": self.avg_loss,
            },
            "streaks": {
                "max_consecutive_wins": self.max_consecutive_wins,
                "max_consecutive_losses": self.max_consecutive_losses,
            },
        }
    
    def print_summary(self) -> None:
        """Imprime un resumen del backtest."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        print(f"Period: {self.start_date.date()} to {self.end_date.date()}")
        print("-" * 60)
        print(f"Initial Capital:     ${self.initial_capital:>12,.2f}")
        print(f"Final Capital:       ${self.final_capital:>12,.2f}")
        print(f"Total P&L:           ${self.total_pnl:>+12,.2f}")
        print(f"Return:              {((self.final_capital/self.initial_capital)-1)*100:>12.2f}%")
        print("-" * 60)
        print(f"Total Trades:        {self.total_trades:>12}")
        print(f"Winning Trades:      {self.winning_trades:>12}")
        print(f"Losing Trades:       {self.losing_trades:>12}")
        print(f"Win Rate:            {self.win_rate*100:>12.2f}%")
        print("-" * 60)
        print(f"Max Drawdown:        ${self.max_drawdown:>12,.2f}")
        print(f"Max Drawdown %:      {self.max_drawdown_percent*100:>12.2f}%")
        print(f"Profit Factor:       {self.profit_factor:>12.2f}")
        print(f"Sharpe Ratio:        {self.sharpe_ratio:>12.2f}")
        print("-" * 60)
        print(f"Avg Trade P&L:       ${self.avg_trade_pnl:>+12,.2f}")
        print(f"Avg Win:             ${self.avg_win:>12,.2f}")
        print(f"Avg Loss:            ${self.avg_loss:>12,.2f}")
        print("-" * 60)
        print(f"Max Consec. Wins:    {self.max_consecutive_wins:>12}")
        print(f"Max Consec. Losses:  {self.max_consecutive_losses:>12}")
        print("=" * 60 + "\n")


class DataLoader:
    """Carga datos históricos de Binance."""
    
    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self.base_url = "https://data-api.binance.vision/api/v3"
    
    async def fetch_klines(
        self,
        interval: str,
        start_time: datetime,
        end_time: datetime
    ) -> pd.DataFrame:
        """
        Descarga velas históricas de Binance.
        
        Args:
            interval: Intervalo de velas ('1m', '5m', etc.)
            start_time: Fecha de inicio
            end_time: Fecha de fin
            
        Returns:
            DataFrame con los datos históricos
        """
        all_klines = []
        current_start = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        
        async with aiohttp.ClientSession() as session:
            while current_start < end_ms:
                url = f"{self.base_url}/klines"
                params = {
                    "symbol": self.symbol,
                    "interval": interval,
                    "startTime": current_start,
                    "endTime": end_ms,
                    "limit": 1000
                }
                
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"API error: {response.status}")
                    
                    data = await response.json()
                    
                    if not data:
                        break
                    
                    all_klines.extend(data)
                    current_start = data[-1][6] + 1
                    
                    await asyncio.sleep(0.1)
        
        df = pd.DataFrame(all_klines, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        
        df = df.drop(columns=["ignore"])
        
        for col in ["open", "high", "low", "close", "volume", 
                    "quote_volume", "taker_buy_base", "taker_buy_quote"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        
        return df


class Backtester:
    """
    Motor de backtesting para estrategias de trading.
    
    Simula el comportamiento del bot sobre datos históricos
    para evaluar rendimiento y ajustar parámetros.
    """
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or load_config()
        self.data_loader = DataLoader(self.config.data_stream.symbol.replace("/", ""))
        
        self.feature_generator = FeatureGenerator(self.config.prediction)
        self.model: Optional[PredictionModel] = None
        
        self._df_1m: Optional[pd.DataFrame] = None
        self._df_5m: Optional[pd.DataFrame] = None
    
    async def load_data(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> None:
        """
        Carga datos históricos para el backtest.
        
        Args:
            start_date: Fecha de inicio
            end_date: Fecha de fin
        """
        logger.info(f"Loading historical data from {start_date} to {end_date}...")
        
        self._df_1m = await self.data_loader.fetch_klines("1m", start_date, end_date)
        logger.info(f"Loaded {len(self._df_1m)} 1m candles")
        
        self._df_5m = await self.data_loader.fetch_klines("5m", start_date, end_date)
        logger.info(f"Loaded {len(self._df_5m)} 5m candles")
    
    def prepare_training_data(
        self,
        train_ratio: float = 0.7
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
        """
        Prepara datos para entrenamiento del modelo.
        
        Args:
            train_ratio: Proporción de datos para entrenamiento
            
        Returns:
            X_train, y_train, X_test, y_test
        """
        if self._df_5m is None or self._df_1m is None:
            raise ValueError("Data not loaded. Call load_data first.")
        
        features_list = []
        labels = []
        errors = []
        
        window_5m = min(self.config.prediction.feature_window_5m, 20)
        min_1m_candles = 30
        
        logger.info(f"Processing {len(self._df_5m)} 5m candles...")
        
        for i in range(window_5m + 5, len(self._df_5m) - 1):
            try:
                ts_5m = self._df_5m.iloc[i]["timestamp"]
                
                mask_1m = self._df_1m["timestamp"] < ts_5m
                df_1m_window = self._df_1m[mask_1m].tail(60).copy()
                
                df_5m_window = self._df_5m.iloc[max(0, i - window_5m):i].copy()
                
                if len(df_1m_window) < min_1m_candles or len(df_5m_window) < 10:
                    continue
                
                features = self.feature_generator.generate_features(
                    df_1m_window, df_5m_window, None, None
                )
                
                current_open = float(self._df_5m.iloc[i]["open"])
                current_close = float(self._df_5m.iloc[i]["close"])
                label = 1 if current_close > current_open else 0
                
                features_list.append(features)
                labels.append(label)
                
            except Exception as e:
                errors.append(str(e))
                continue
        
        if not features_list:
            if errors:
                logger.error(f"Sample errors: {errors[:5]}")
            raise ValueError(f"Could not generate features. Total 5m candles: {len(self._df_5m)}, 1m candles: {len(self._df_1m)}")
        
        logger.info(f"Generated {len(features_list)} feature samples")
        
        X = pd.concat(features_list, ignore_index=True)
        y = pd.Series(labels)
        
        X = X.replace([np.inf, -np.inf], np.nan).fillna(0)
        
        split_idx = int(len(X) * train_ratio)
        
        X_train = X.iloc[:split_idx]
        y_train = y.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_test = y.iloc[split_idx:]
        
        logger.info(f"Training samples: {len(X_train)}, Test samples: {len(X_test)}")
        logger.info(f"Label distribution - UP: {y.sum()}, DOWN: {len(y) - y.sum()}")
        
        return X_train, y_train, X_test, y_test
    
    def train_model(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        model_type: ModelType = ModelType.LIGHTGBM
    ) -> dict:
        """
        Entrena el modelo de predicción.
        
        Args:
            X_train: Features de entrenamiento
            y_train: Labels de entrenamiento
            model_type: Tipo de modelo a usar
            
        Returns:
            Métricas de entrenamiento
        """
        self.model = PredictionModel(self.config.prediction, model_type)
        return self.model.train(X_train, y_train, validation_split=0.2)
    
    async def run_backtest(
        self,
        start_idx: Optional[int] = None,
        end_idx: Optional[int] = None
    ) -> BacktestResult:
        """
        Ejecuta el backtest sobre los datos cargados.
        
        Args:
            start_idx: Índice de inicio (opcional)
            end_idx: Índice de fin (opcional)
            
        Returns:
            Resultado completo del backtest
        """
        if self._df_5m is None or self.model is None:
            raise ValueError("Data and model must be loaded/trained first")
        
        window_1m = self.config.prediction.feature_window_1m
        window_5m = self.config.prediction.feature_window_5m
        
        start_idx = start_idx or max(window_5m, window_1m // 5) + 1
        end_idx = end_idx or len(self._df_5m) - 1
        
        position_sizer = PositionSizer(
            self.config.trading,
            self.config.trading.initial_capital
        )
        
        trades: List[BacktestTrade] = []
        cumulative_pnl = 0.0
        peak_capital = self.config.trading.initial_capital
        max_drawdown = 0.0
        
        consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        
        for i in range(start_idx, end_idx):
            start_idx_1m = max(0, i * 5 - window_1m)
            end_idx_1m = min(i * 5, len(self._df_1m))
            
            df_1m_window = self._df_1m.iloc[start_idx_1m:end_idx_1m].copy()
            df_5m_window = self._df_5m.iloc[max(0, i - window_5m):i].copy()
            
            if len(df_1m_window) < 30 or len(df_5m_window) < 10:
                continue
            
            try:
                features = self.feature_generator.generate_features(
                    df_1m_window, df_5m_window, None, None
                )
                
                prediction = self.model.predict(features)
                
                if prediction.signal == Signal.WAIT:
                    continue
                
                if prediction.confidence < self.config.prediction.confidence_threshold:
                    continue
                
                direction = prediction.signal.value
                amount = position_sizer.calculate_bet_size(prediction.confidence)
                
                entry_price = float(self._df_5m.iloc[i]["open"])
                exit_price = float(self._df_5m.iloc[i]["close"])
                
                actual_direction = "UP" if exit_price > entry_price else "DOWN"
                is_win = direction == actual_direction
                
                payout_rate = 0.95
                pnl = amount * payout_rate if is_win else -amount
                
                cumulative_pnl += pnl
                position_sizer.record_result(is_win, pnl)
                
                current_capital = self.config.trading.initial_capital + cumulative_pnl
                if current_capital > peak_capital:
                    peak_capital = current_capital
                
                drawdown = peak_capital - current_capital
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                
                if is_win:
                    consecutive_wins += 1
                    consecutive_losses = 0
                    max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
                else:
                    consecutive_losses += 1
                    consecutive_wins = 0
                    max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                
                trade = BacktestTrade(
                    timestamp=self._df_5m.iloc[i]["timestamp"],
                    direction=direction,
                    amount=amount,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    is_win=is_win,
                    confidence=prediction.confidence,
                    cumulative_pnl=cumulative_pnl
                )
                trades.append(trade)
                
            except Exception as e:
                logger.warning(f"Error processing candle {i}: {e}")
                continue
        
        if not trades:
            raise ValueError("No trades executed during backtest")
        
        winning_trades = [t for t in trades if t.is_win]
        losing_trades = [t for t in trades if not t.is_win]
        
        total_wins = sum(t.pnl for t in winning_trades)
        total_losses = abs(sum(t.pnl for t in losing_trades))
        profit_factor = total_wins / total_losses if total_losses > 0 else float("inf")
        
        returns = [t.pnl / t.amount for t in trades]
        sharpe_ratio = 0.0
        if len(returns) > 1:
            avg_return = np.mean(returns)
            std_return = np.std(returns)
            if std_return > 0:
                sharpe_ratio = (avg_return / std_return) * np.sqrt(252 * 288 / 5)
        
        final_capital = self.config.trading.initial_capital + cumulative_pnl
        
        return BacktestResult(
            start_date=self._df_5m.iloc[start_idx]["timestamp"],
            end_date=self._df_5m.iloc[end_idx - 1]["timestamp"],
            initial_capital=self.config.trading.initial_capital,
            final_capital=final_capital,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            total_pnl=cumulative_pnl,
            max_drawdown=max_drawdown,
            max_drawdown_percent=max_drawdown / peak_capital if peak_capital > 0 else 0,
            win_rate=len(winning_trades) / len(trades) if trades else 0,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            avg_trade_pnl=cumulative_pnl / len(trades) if trades else 0,
            avg_win=total_wins / len(winning_trades) if winning_trades else 0,
            avg_loss=total_losses / len(losing_trades) if losing_trades else 0,
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            trades=trades
        )
    
    def save_model(self, path: Optional[str] = None) -> None:
        """Guarda el modelo entrenado."""
        if self.model:
            self.model.save(path)
    
    def export_results(
        self,
        result: BacktestResult,
        output_dir: str = "backtest_results"
    ) -> None:
        """
        Exporta los resultados del backtest a archivos.
        
        Args:
            result: Resultado del backtest
            output_dir: Directorio de salida
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        summary_file = output_path / f"backtest_summary_{timestamp}.json"
        with open(summary_file, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        
        trades_data = [
            {
                "timestamp": str(t.timestamp),
                "direction": t.direction,
                "amount": t.amount,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "is_win": t.is_win,
                "confidence": t.confidence,
                "cumulative_pnl": t.cumulative_pnl
            }
            for t in result.trades
        ]
        
        trades_file = output_path / f"backtest_trades_{timestamp}.json"
        with open(trades_file, "w") as f:
            json.dump(trades_data, f, indent=2)
        
        logger.info(f"Results exported to {output_path}")


async def run_full_backtest(
    days: int = 30,
    config_path: Optional[str] = None,
    save_model: bool = True
) -> BacktestResult:
    """
    Ejecuta un backtest completo con entrenamiento.
    
    Args:
        days: Número de días de datos históricos
        config_path: Ruta al archivo de configuración
        save_model: Si guardar el modelo entrenado
        
    Returns:
        Resultado del backtest
    """
    config = load_config(config_path)
    backtester = Backtester(config)
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    await backtester.load_data(start_date, end_date)
    
    X_train, y_train, X_test, y_test = backtester.prepare_training_data(train_ratio=0.7)
    
    train_metrics = backtester.train_model(X_train, y_train)
    logger.info(f"Training metrics: {train_metrics}")
    
    result = await backtester.run_backtest()
    
    result.print_summary()
    
    if save_model:
        backtester.save_model()
        logger.info("Model saved successfully")
    
    backtester.export_results(result)
    
    return result


def main():
    """CLI entry point para backtest."""
    parser = argparse.ArgumentParser(
        description="Backtest the trading strategy on historical data"
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=30,
        help="Number of days of historical data to use"
    )
    parser.add_argument(
        "-c", "--config",
        type=str,
        help="Path to configuration file"
    )
    parser.add_argument(
        "--no-save-model",
        action="store_true",
        help="Don't save the trained model"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="backtest_results",
        help="Output directory for results"
    )
    
    args = parser.parse_args()
    
    setup_logger("backtest", console_output=True, file_output=True)
    
    asyncio.run(run_full_backtest(
        days=args.days,
        config_path=args.config,
        save_model=not args.no_save_model
    ))


if __name__ == "__main__":
    main()
