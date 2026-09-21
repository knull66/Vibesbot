"""
Configuración centralizada del bot de trading.

Este módulo contiene todos los parámetros configurables del sistema,
incluyendo gestión de capital, umbrales de predicción, límites de riesgo
y credenciales de sesión.
"""
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import json


class SizingStrategy(Enum):
    """Estrategias de dimensionamiento de posición."""
    FIXED_AMOUNT = "fixed"
    KELLY_CRITERION = "kelly"
    HALF_KELLY = "half_kelly"
    ANTI_MARTINGALE = "anti_martingale"
    PERCENT_OF_CAPITAL = "percent"


@dataclass
class TradingConfig:
    """Configuración de parámetros de trading."""
    
    initial_capital: float = 100.0
    base_bet_amount: float = 1.0
    min_bet_amount: float = 0.1
    max_bet_amount: float = 10.0
    
    sizing_strategy: SizingStrategy = SizingStrategy.HALF_KELLY
    kelly_fraction: float = 0.5
    percent_of_capital: float = 0.02
    
    anti_martingale_multiplier: float = 1.5
    anti_martingale_max_streak: int = 3


@dataclass
class PredictionConfig:
    """Configuración del módulo de predicción."""
    
    confidence_threshold: float = 0.50
    min_confidence_for_high_bet: float = 0.70
    
    model_path: str = "models/prediction_model.pkl"
    scaler_path: str = "models/feature_scaler.pkl"
    
    lookback_periods: int = 100
    feature_window_1m: int = 60
    feature_window_5m: int = 20
    
    use_order_book: bool = True
    use_trade_flow: bool = True
    use_technical_indicators: bool = True


@dataclass
class RiskConfig:
    """Configuración de gestión de riesgo."""
    
    max_daily_loss: float = 20.0
    max_daily_loss_percent: float = 0.20
    
    circuit_breaker_consecutive_losses: int = 5
    circuit_breaker_cooldown_minutes: int = 30
    
    min_volatility_threshold: float = 0.0005
    max_volatility_threshold: float = 0.02
    
    max_trades_per_hour: int = 12
    max_trades_per_day: int = 100
    
    avoid_news_window_minutes: int = 15
    news_volatility_multiplier: float = 2.0
    
    stop_loss_daily: float = 0.15
    trailing_stop_percent: float = 0.10


@dataclass
class DataStreamConfig:
    """Configuración del stream de datos."""
    
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    
    timeframes: list[str] = field(default_factory=lambda: ["1m", "5m"])
    
    orderbook_depth: int = 20
    orderbook_update_interval_ms: int = 100
    
    trades_buffer_size: int = 1000
    
    ws_ping_interval: int = 20
    ws_ping_timeout: int = 10
    ws_reconnect_delay: int = 5
    ws_max_reconnect_attempts: int = 10
    
    use_testnet: bool = False


@dataclass
class LoggingConfig:
    """Configuración de logging."""
    
    log_dir: str = "./logs"
    log_level: str = "INFO"
    
    console_output: bool = True
    file_output: bool = True
    json_format: bool = False
    
    log_predictions: bool = True
    log_trades: bool = True
    log_features: bool = False


@dataclass
class Config:
    """Configuración principal que agrupa todas las sub-configuraciones."""
    
    trading: TradingConfig = field(default_factory=TradingConfig)
    prediction: PredictionConfig = field(default_factory=PredictionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    data_stream: DataStreamConfig = field(default_factory=DataStreamConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    environment: str = "development"
    
    def __post_init__(self):
        """Carga variables de entorno si existen."""
        self._load_from_env()
        
    def _load_from_env(self) -> None:
        """Carga configuración desde variables de entorno."""
        if os.getenv("VIBESBOT_CAPITAL"):
            self.trading.initial_capital = float(os.getenv("VIBESBOT_CAPITAL", "100"))
            
        if os.getenv("VIBESBOT_CONFIDENCE"):
            self.prediction.confidence_threshold = float(os.getenv("VIBESBOT_CONFIDENCE", "0.50"))
            
        if os.getenv("VIBESBOT_MAX_DAILY_LOSS"):
            self.risk.max_daily_loss = float(os.getenv("VIBESBOT_MAX_DAILY_LOSS", "20"))
            
        if os.getenv("VIBESBOT_ENV"):
            self.environment = os.getenv("VIBESBOT_ENV", "development")
            
        if os.getenv("VIBESBOT_TESTNET"):
            self.data_stream.use_testnet = os.getenv("VIBESBOT_TESTNET", "").lower() == "true"
    
    @classmethod
    def from_json(cls, path: str) -> "Config":
        """
        Carga configuración desde un archivo JSON.
        
        Args:
            path: Ruta al archivo de configuración
            
        Returns:
            Instancia de Config con los valores cargados
        """
        with open(path, "r") as f:
            data = json.load(f)
            
        config = cls()
        
        if "trading" in data:
            for key, value in data["trading"].items():
                if hasattr(config.trading, key):
                    if key == "sizing_strategy":
                        value = SizingStrategy(value)
                    setattr(config.trading, key, value)
                    
        if "prediction" in data:
            for key, value in data["prediction"].items():
                if hasattr(config.prediction, key):
                    setattr(config.prediction, key, value)
                    
        if "risk" in data:
            for key, value in data["risk"].items():
                if hasattr(config.risk, key):
                    setattr(config.risk, key, value)
                    
        if "data_stream" in data:
            for key, value in data["data_stream"].items():
                if hasattr(config.data_stream, key):
                    setattr(config.data_stream, key, value)

        if "logging" in data:
            for key, value in data["logging"].items():
                if hasattr(config.logging, key):
                    setattr(config.logging, key, value)
                    
        if "environment" in data:
            config.environment = data["environment"]
            
        return config
    
    def to_json(self, path: str) -> None:
        """
        Guarda la configuración actual a un archivo JSON.
        
        Args:
            path: Ruta donde guardar el archivo
        """
        data = {
            "trading": {
                "initial_capital": self.trading.initial_capital,
                "base_bet_amount": self.trading.base_bet_amount,
                "min_bet_amount": self.trading.min_bet_amount,
                "max_bet_amount": self.trading.max_bet_amount,
                "sizing_strategy": self.trading.sizing_strategy.value,
                "kelly_fraction": self.trading.kelly_fraction,
                "percent_of_capital": self.trading.percent_of_capital,
                "anti_martingale_multiplier": self.trading.anti_martingale_multiplier,
                "anti_martingale_max_streak": self.trading.anti_martingale_max_streak,
            },
            "prediction": {
                "confidence_threshold": self.prediction.confidence_threshold,
                "min_confidence_for_high_bet": self.prediction.min_confidence_for_high_bet,
                "model_path": self.prediction.model_path,
                "scaler_path": self.prediction.scaler_path,
                "lookback_periods": self.prediction.lookback_periods,
                "feature_window_1m": self.prediction.feature_window_1m,
                "feature_window_5m": self.prediction.feature_window_5m,
                "use_order_book": self.prediction.use_order_book,
                "use_trade_flow": self.prediction.use_trade_flow,
                "use_technical_indicators": self.prediction.use_technical_indicators,
            },
            "risk": {
                "max_daily_loss": self.risk.max_daily_loss,
                "max_daily_loss_percent": self.risk.max_daily_loss_percent,
                "circuit_breaker_consecutive_losses": self.risk.circuit_breaker_consecutive_losses,
                "circuit_breaker_cooldown_minutes": self.risk.circuit_breaker_cooldown_minutes,
                "min_volatility_threshold": self.risk.min_volatility_threshold,
                "max_volatility_threshold": self.risk.max_volatility_threshold,
                "max_trades_per_hour": self.risk.max_trades_per_hour,
                "max_trades_per_day": self.risk.max_trades_per_day,
            },
            "data_stream": {
                "exchange": self.data_stream.exchange,
                "symbol": self.data_stream.symbol,
                "timeframes": self.data_stream.timeframes,
                "orderbook_depth": self.data_stream.orderbook_depth,
                "use_testnet": self.data_stream.use_testnet,
            },
            "logging": {
                "log_dir": self.logging.log_dir,
                "log_level": self.logging.log_level,
                "console_output": self.logging.console_output,
                "file_output": self.logging.file_output,
                "json_format": self.logging.json_format,
            },
            "environment": self.environment,
        }
        
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def validate(self) -> list[str]:
        """
        Valida la configuración y retorna lista de errores.
        
        Returns:
            Lista de mensajes de error (vacía si todo es válido)
        """
        errors = []
        
        if self.trading.initial_capital <= 0:
            errors.append("initial_capital debe ser mayor a 0")
            
        if self.trading.base_bet_amount <= 0:
            errors.append("base_bet_amount debe ser mayor a 0")
            
        if self.trading.min_bet_amount >= self.trading.max_bet_amount:
            errors.append("min_bet_amount debe ser menor a max_bet_amount")
            
        if not 0.5 <= self.prediction.confidence_threshold <= 1.0:
            errors.append("confidence_threshold debe estar entre 0.5 y 1.0")
            
        if self.risk.max_daily_loss <= 0:
            errors.append("max_daily_loss debe ser mayor a 0")
            
        if self.risk.circuit_breaker_consecutive_losses < 1:
            errors.append("circuit_breaker_consecutive_losses debe ser al menos 1")
            
        if not 0 < self.trading.kelly_fraction <= 1.0:
            errors.append("kelly_fraction debe estar entre 0 y 1.0")
            
        return errors


def get_default_config() -> Config:
    """Retorna la configuración por defecto."""
    return Config()


def load_config(path: Optional[str] = None) -> Config:
    """
    Carga configuración desde archivo si existe, sino usa defaults.
    
    Args:
        path: Ruta opcional al archivo de configuración
        
    Returns:
        Configuración cargada
    """
    if path and Path(path).exists():
        return Config.from_json(path)
    
    default_paths = ["config.json", "config/config.json", ".config/vibesbot.json"]
    
    for default_path in default_paths:
        if Path(default_path).exists():
            return Config.from_json(default_path)
            
    return get_default_config()
