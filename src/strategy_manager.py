"""
Strategy Manager - Gestión de estrategias de trading configurables.

Permite crear, guardar y comparar diferentes estrategias.
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum

from .utils.logger import get_logger

logger = get_logger("strategy_manager")


class IndicatorWeight(Enum):
    """Pesos para indicadores."""
    OFF = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class StrategyConfig:
    """Configuración de una estrategia de trading."""
    name: str = "Default Strategy"
    description: str = ""
    
    # Pesos de indicadores (0=off, 1=low, 2=medium, 3=high)
    rsi_weight: int = 2
    macd_weight: int = 2
    bollinger_weight: int = 1
    momentum_weight: int = 1
    volume_weight: int = 0
    
    # Parámetros RSI
    rsi_period: int = 14
    rsi_oversold: int = 30
    rsi_overbought: int = 70
    
    # Parámetros MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    
    # Parámetros Bollinger
    bb_period: int = 20
    bb_std: float = 2.0
    
    # Parámetros Momentum
    momentum_period: int = 5
    
    # Umbral de confianza mínimo
    min_confidence: float = 0.52
    
    # Metadata
    created_at: str = ""
    updated_at: str = ""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.wins / self.total_trades) * 100
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "weights": {
                "rsi": self.rsi_weight,
                "macd": self.macd_weight,
                "bollinger": self.bollinger_weight,
                "momentum": self.momentum_weight,
                "volume": self.volume_weight
            },
            "rsi": {
                "period": self.rsi_period,
                "oversold": self.rsi_oversold,
                "overbought": self.rsi_overbought
            },
            "macd": {
                "fast": self.macd_fast,
                "slow": self.macd_slow,
                "signal": self.macd_signal
            },
            "bollinger": {
                "period": self.bb_period,
                "std": self.bb_std
            },
            "momentum": {
                "period": self.momentum_period
            },
            "min_confidence": self.min_confidence,
            "stats": {
                "total_trades": self.total_trades,
                "wins": self.wins,
                "losses": self.losses,
                "win_rate": self.win_rate,
                "total_pnl": self.total_pnl
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'StrategyConfig':
        weights = data.get("weights", {})
        rsi = data.get("rsi", {})
        macd = data.get("macd", {})
        bb = data.get("bollinger", {})
        mom = data.get("momentum", {})
        stats = data.get("stats", {})
        
        return cls(
            name=data.get("name", "Unnamed"),
            description=data.get("description", ""),
            rsi_weight=weights.get("rsi", 2),
            macd_weight=weights.get("macd", 2),
            bollinger_weight=weights.get("bollinger", 1),
            momentum_weight=weights.get("momentum", 1),
            volume_weight=weights.get("volume", 0),
            rsi_period=rsi.get("period", 14),
            rsi_oversold=rsi.get("oversold", 30),
            rsi_overbought=rsi.get("overbought", 70),
            macd_fast=macd.get("fast", 12),
            macd_slow=macd.get("slow", 26),
            macd_signal=macd.get("signal", 9),
            bb_period=bb.get("period", 20),
            bb_std=bb.get("std", 2.0),
            momentum_period=mom.get("period", 5),
            min_confidence=data.get("min_confidence", 0.52),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            total_trades=stats.get("total_trades", 0),
            wins=stats.get("wins", 0),
            losses=stats.get("losses", 0),
            total_pnl=stats.get("total_pnl", 0.0)
        )
    
    def record_trade(self, is_win: bool, pnl: float):
        """Registra resultado de un trade."""
        self.total_trades += 1
        if is_win:
            self.wins += 1
        else:
            self.losses += 1
        self.total_pnl += pnl
        self.updated_at = datetime.now().isoformat()


class StrategyManager:
    """Gestor de estrategias de trading."""
    
    STRATEGIES_FILE = "strategies.json"
    
    def __init__(self, app_path: Optional[Path] = None):
        self.app_path = app_path or Path(__file__).parent.parent
        self.strategies_path = self.app_path / self.STRATEGIES_FILE
        self.strategies: Dict[str, StrategyConfig] = {}
        self.active_strategy: str = "default"
        
        self._load_default_strategies()
        self.load()
    
    def _load_default_strategies(self):
        """Carga estrategias predefinidas."""
        # Estrategia conservadora
        self.strategies["conservative"] = StrategyConfig(
            name="Conservative",
            description="Low risk, high confidence threshold",
            rsi_weight=3,
            macd_weight=2,
            bollinger_weight=2,
            momentum_weight=1,
            min_confidence=0.60
        )
        
        # Estrategia agresiva
        self.strategies["aggressive"] = StrategyConfig(
            name="Aggressive",
            description="Higher risk, lower confidence threshold",
            rsi_weight=2,
            macd_weight=3,
            bollinger_weight=1,
            momentum_weight=2,
            min_confidence=0.52
        )
        
        # Estrategia RSI focused
        self.strategies["rsi_focused"] = StrategyConfig(
            name="RSI Focused",
            description="Primarily uses RSI for signals",
            rsi_weight=3,
            macd_weight=1,
            bollinger_weight=1,
            momentum_weight=0,
            rsi_oversold=25,
            rsi_overbought=75,
            min_confidence=0.55
        )
        
        # Estrategia MACD focused
        self.strategies["macd_focused"] = StrategyConfig(
            name="MACD Focused",
            description="Primarily uses MACD crossovers",
            rsi_weight=1,
            macd_weight=3,
            bollinger_weight=1,
            momentum_weight=1,
            min_confidence=0.55
        )
        
        # Estrategia por defecto (balanceada)
        self.strategies["default"] = StrategyConfig(
            name="Balanced",
            description="Equal weight to all indicators",
            rsi_weight=2,
            macd_weight=2,
            bollinger_weight=2,
            momentum_weight=2,
            min_confidence=0.55
        )
    
    def load(self):
        """Carga estrategias guardadas."""
        if not self.strategies_path.exists():
            return
        
        try:
            with open(self.strategies_path, 'r') as f:
                data = json.load(f)
            
            # Cargar estrategias custom
            for name, strategy_data in data.get("strategies", {}).items():
                self.strategies[name] = StrategyConfig.from_dict(strategy_data)
            
            self.active_strategy = data.get("active", "default")
            logger.info(f"Loaded {len(self.strategies)} strategies")
            
        except Exception as e:
            logger.error(f"Error loading strategies: {e}")
    
    def save(self):
        """Guarda estrategias."""
        try:
            data = {
                "active": self.active_strategy,
                "strategies": {
                    name: strategy.to_dict() 
                    for name, strategy in self.strategies.items()
                }
            }
            
            with open(self.strategies_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info("Strategies saved")
            
        except Exception as e:
            logger.error(f"Error saving strategies: {e}")
    
    def get_active_strategy(self) -> StrategyConfig:
        """Obtiene la estrategia activa."""
        return self.strategies.get(self.active_strategy, self.strategies["default"])
    
    def set_active_strategy(self, name: str) -> bool:
        """Establece la estrategia activa."""
        if name in self.strategies:
            self.active_strategy = name
            self.save()
            return True
        return False
    
    def create_strategy(self, name: str, config: dict) -> StrategyConfig:
        """Crea una nueva estrategia."""
        strategy_id = name.lower().replace(" ", "_")
        config["name"] = name
        strategy = StrategyConfig.from_dict(config)
        self.strategies[strategy_id] = strategy
        self.save()
        return strategy
    
    def update_strategy(self, name: str, config: dict) -> Optional[StrategyConfig]:
        """Actualiza una estrategia existente."""
        if name not in self.strategies:
            return None
        
        strategy = self.strategies[name]
        weights = config.get("weights") if isinstance(config.get("weights"), dict) else {}
        mapped = dict(config)
        if weights:
            mapped["rsi_weight"] = weights.get("rsi", mapped.get("rsi_weight", strategy.rsi_weight))
            mapped["macd_weight"] = weights.get("macd", mapped.get("macd_weight", strategy.macd_weight))
            mapped["bollinger_weight"] = weights.get("bollinger", mapped.get("bollinger_weight", strategy.bollinger_weight))
            mapped["momentum_weight"] = weights.get("momentum", mapped.get("momentum_weight", strategy.momentum_weight))
        
        for key, value in mapped.items():
            if hasattr(strategy, key):
                setattr(strategy, key, value)
        
        strategy.updated_at = datetime.now().isoformat()
        self.save()
        return strategy
    
    def delete_strategy(self, name: str) -> bool:
        """Elimina una estrategia."""
        if name in ["default", "conservative", "aggressive", "rsi_focused", "macd_focused"]:
            return False  # No eliminar predefinidas
        
        if name in self.strategies:
            del self.strategies[name]
            if self.active_strategy == name:
                self.active_strategy = "default"
            self.save()
            return True
        return False
    
    def get_all_strategies(self) -> List[dict]:
        """Obtiene todas las estrategias."""
        return [
            {"id": name, **strategy.to_dict()}
            for name, strategy in self.strategies.items()
        ]
    
    def record_trade_result(self, is_win: bool, pnl: float):
        """Registra resultado en la estrategia activa."""
        strategy = self.get_active_strategy()
        strategy.record_trade(is_win, pnl)
        self.save()
    
    def compare_strategies(self) -> List[dict]:
        """Compara rendimiento de todas las estrategias."""
        return sorted(
            [
                {
                    "id": name,
                    "name": s.name,
                    "trades": s.total_trades,
                    "win_rate": s.win_rate,
                    "pnl": s.total_pnl
                }
                for name, s in self.strategies.items()
                if s.total_trades > 0
            ],
            key=lambda x: x["win_rate"],
            reverse=True
        )


# Singleton
_strategy_manager: Optional[StrategyManager] = None

def get_strategy_manager() -> StrategyManager:
    """Obtiene el gestor de estrategias."""
    global _strategy_manager
    if _strategy_manager is None:
        _strategy_manager = StrategyManager()
    return _strategy_manager
