"""
Módulo de gestión de riesgo.

Implementa:
- Kelly Criterion y variantes para sizing de posición
- Circuit Breaker para control de pérdidas
- Filtros de volatilidad
- Límites de operaciones
"""
import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
import numpy as np

from .config import RiskConfig, TradingConfig, SizingStrategy
from .data_stream import DataStream
from .predictor import Prediction
from .utils.logger import get_logger, TradingLogger


logger = get_logger("risk_manager")


class RiskStatus(Enum):
    """Estados posibles del sistema de riesgo."""
    OK = "OK"
    VOLATILITY_HIGH = "VOLATILITY_HIGH"
    VOLATILITY_LOW = "VOLATILITY_LOW"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    DAILY_LIMIT = "DAILY_LIMIT"
    HOURLY_LIMIT = "HOURLY_LIMIT"
    COOLDOWN = "COOLDOWN"


@dataclass
class TradeRecord:
    """Registro de una operación para tracking."""
    
    timestamp: datetime
    direction: str
    amount: float
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    is_win: Optional[bool] = None
    confidence: float = 0.0
    round_id: Optional[str] = None


@dataclass
class RiskAssessment:
    """Resultado de una evaluación de riesgo."""
    
    can_trade: bool
    status: RiskStatus
    reason: str
    suggested_amount: float
    volatility: float
    consecutive_losses: int
    daily_pnl: float
    trade_count_today: int
    
    def __str__(self) -> str:
        return f"RiskAssessment(can_trade={self.can_trade}, status={self.status.value}, reason='{self.reason}')"


class PositionSizer:
    """
    Calcula el tamaño óptimo de posición basado en diferentes estrategias.
    
    Soporta:
    - Fixed Amount: Monto fijo por operación
    - Kelly Criterion: Tamaño óptimo basado en win rate y payoff
    - Half-Kelly: Kelly conservador (50%)
    - Anti-Martingala: Aumenta posición después de ganar
    - Percent of Capital: Porcentaje fijo del capital
    """
    
    def __init__(
        self,
        trading_config: TradingConfig,
        initial_capital: float
    ):
        self.config = trading_config
        self.capital = initial_capital
        self.current_capital = initial_capital
        
        self._win_count = 0
        self._loss_count = 0
        self._consecutive_wins = 0
        self._consecutive_losses = 0
        
    def calculate_bet_size(
        self,
        confidence: float = 0.6,
        custom_win_rate: Optional[float] = None
    ) -> float:
        """
        Calcula el tamaño de apuesta según la estrategia configurada.
        
        Args:
            confidence: Confianza del modelo en la predicción
            custom_win_rate: Win rate personalizado (opcional)
            
        Returns:
            Monto de la apuesta
        """
        strategy = self.config.sizing_strategy
        
        if strategy == SizingStrategy.FIXED_AMOUNT:
            amount = self.config.base_bet_amount
            
        elif strategy == SizingStrategy.KELLY_CRITERION:
            amount = self._calculate_kelly(
                confidence, 
                custom_win_rate, 
                fraction=1.0
            )
            
        elif strategy == SizingStrategy.HALF_KELLY:
            amount = self._calculate_kelly(
                confidence, 
                custom_win_rate, 
                fraction=self.config.kelly_fraction
            )
            
        elif strategy == SizingStrategy.ANTI_MARTINGALE:
            amount = self._calculate_anti_martingale()
            
        elif strategy == SizingStrategy.PERCENT_OF_CAPITAL:
            amount = self.current_capital * self.config.percent_of_capital
            
        else:
            amount = self.config.base_bet_amount
        
        amount = max(self.config.min_bet_amount, min(amount, self.config.max_bet_amount))
        
        if amount > self.current_capital * 0.5:
            amount = self.current_capital * 0.5
        
        return round(amount, 2)
    
    def _calculate_kelly(
        self,
        confidence: float,
        custom_win_rate: Optional[float],
        fraction: float = 0.5
    ) -> float:
        """
        Calcula el tamaño óptimo usando Kelly Criterion.
        
        Kelly = (p * b - q) / b
        donde:
        - p = probabilidad de ganar
        - q = probabilidad de perder (1 - p)
        - b = ratio de pago (0.95 para Binance Prediction)
        
        Args:
            confidence: Confianza del modelo
            custom_win_rate: Win rate histórico opcional
            fraction: Fracción de Kelly a usar (ej. 0.5 para Half-Kelly)
            
        Returns:
            Monto calculado
        """
        if custom_win_rate is not None:
            p = custom_win_rate
        else:
            total_trades = self._win_count + self._loss_count
            if total_trades < 20:
                p = confidence
            else:
                historical_p = self._win_count / total_trades
                p = (historical_p * 0.7) + (confidence * 0.3)
        
        q = 1 - p
        b = 0.95
        
        kelly = (p * b - q) / b
        
        kelly = max(0, kelly)
        
        kelly_fraction = kelly * fraction
        
        bet_amount = self.current_capital * kelly_fraction
        
        return bet_amount
    
    def _calculate_anti_martingale(self) -> float:
        """
        Calcula tamaño usando Anti-Martingala.
        
        Aumenta la apuesta después de ganar, resetea después de perder.
        
        Returns:
            Monto calculado
        """
        base = self.config.base_bet_amount
        multiplier = self.config.anti_martingale_multiplier
        max_streak = self.config.anti_martingale_max_streak
        
        streak = min(self._consecutive_wins, max_streak)
        
        return base * (multiplier ** streak)
    
    def record_result(self, is_win: bool, pnl: float) -> None:
        """
        Registra el resultado de una operación.
        
        Args:
            is_win: True si la operación fue ganadora
            pnl: Profit/Loss de la operación
        """
        self.current_capital += pnl
        
        if is_win:
            self._win_count += 1
            self._consecutive_wins += 1
            self._consecutive_losses = 0
        else:
            self._loss_count += 1
            self._consecutive_losses += 1
            self._consecutive_wins = 0
    
    @property
    def win_rate(self) -> float:
        """Retorna el win rate actual."""
        total = self._win_count + self._loss_count
        return self._win_count / total if total > 0 else 0.0
    
    @property
    def total_trades(self) -> int:
        """Retorna el total de operaciones."""
        return self._win_count + self._loss_count
    
    @property
    def consecutive_losses(self) -> int:
        """Retorna el número de pérdidas consecutivas."""
        return self._consecutive_losses
    
    def reset_daily(self) -> None:
        """Resetea estadísticas diarias (mantiene capital)."""
        pass


class RiskManager:
    """
    Gestor principal de riesgo del sistema.
    
    Coordina todas las verificaciones de riesgo antes de permitir una operación:
    - Volatilidad del mercado
    - Circuit breaker por pérdidas consecutivas
    - Límites diarios y por hora
    - Cooldown después de pérdidas
    """
    
    def __init__(
        self,
        risk_config: Optional[RiskConfig] = None,
        trading_config: Optional[TradingConfig] = None
    ):
        self.risk_config = risk_config or RiskConfig()
        self.trading_config = trading_config or TradingConfig()
        
        self.position_sizer = PositionSizer(
            self.trading_config,
            self.trading_config.initial_capital
        )
        
        self._trade_history: deque[TradeRecord] = deque(maxlen=1000)
        self._daily_pnl = 0.0
        self._daily_trade_count = 0
        self._hourly_trade_counts: dict[int, int] = {}
        
        self._circuit_breaker_active = False
        self._circuit_breaker_until: Optional[datetime] = None
        
        self._last_trade_time: Optional[datetime] = None
        self._current_day: Optional[int] = None
        
        self.trading_logger = TradingLogger()
    
    def assess_risk(
        self,
        prediction: Prediction,
        data_stream: DataStream
    ) -> RiskAssessment:
        """
        Evalúa si es seguro realizar una operación.
        
        Args:
            prediction: Predicción del modelo
            data_stream: Stream de datos del mercado
            
        Returns:
            Evaluación completa de riesgo
        """
        self._check_day_reset()
        
        volatility = data_stream.get_volatility("1m", 20)
        
        if self._circuit_breaker_active:
            if self._circuit_breaker_until and datetime.now(timezone.utc) < self._circuit_breaker_until:
                return RiskAssessment(
                    can_trade=False,
                    status=RiskStatus.CIRCUIT_BREAKER,
                    reason=f"Circuit breaker activo hasta {self._circuit_breaker_until}",
                    suggested_amount=0.0,
                    volatility=volatility,
                    consecutive_losses=self.position_sizer.consecutive_losses,
                    daily_pnl=self._daily_pnl,
                    trade_count_today=self._daily_trade_count
                )
            else:
                self._circuit_breaker_active = False
                self._circuit_breaker_until = None
        
        if volatility > 0 and volatility < self.risk_config.min_volatility_threshold:
            return RiskAssessment(
                can_trade=False,
                status=RiskStatus.VOLATILITY_LOW,
                reason=f"Volatilidad muy baja: {volatility:.6f}",
                suggested_amount=0.0,
                volatility=volatility,
                consecutive_losses=self.position_sizer.consecutive_losses,
                daily_pnl=self._daily_pnl,
                trade_count_today=self._daily_trade_count
            )
        
        if volatility > self.risk_config.max_volatility_threshold:
            return RiskAssessment(
                can_trade=False,
                status=RiskStatus.VOLATILITY_HIGH,
                reason=f"Volatilidad muy alta: {volatility:.6f}",
                suggested_amount=0.0,
                volatility=volatility,
                consecutive_losses=self.position_sizer.consecutive_losses,
                daily_pnl=self._daily_pnl,
                trade_count_today=self._daily_trade_count
            )
        
        if abs(self._daily_pnl) >= self.risk_config.max_daily_loss:
            return RiskAssessment(
                can_trade=False,
                status=RiskStatus.DAILY_LIMIT,
                reason=f"Límite de pérdida diaria alcanzado: ${self._daily_pnl:.2f}",
                suggested_amount=0.0,
                volatility=volatility,
                consecutive_losses=self.position_sizer.consecutive_losses,
                daily_pnl=self._daily_pnl,
                trade_count_today=self._daily_trade_count
            )
        
        if self._daily_trade_count >= self.risk_config.max_trades_per_day:
            return RiskAssessment(
                can_trade=False,
                status=RiskStatus.DAILY_LIMIT,
                reason=f"Límite diario de operaciones alcanzado: {self._daily_trade_count}",
                suggested_amount=0.0,
                volatility=volatility,
                consecutive_losses=self.position_sizer.consecutive_losses,
                daily_pnl=self._daily_pnl,
                trade_count_today=self._daily_trade_count
            )
        
        current_hour = datetime.now(timezone.utc).hour
        hourly_count = self._hourly_trade_counts.get(current_hour, 0)
        if hourly_count >= self.risk_config.max_trades_per_hour:
            return RiskAssessment(
                can_trade=False,
                status=RiskStatus.HOURLY_LIMIT,
                reason=f"Límite de operaciones por hora alcanzado: {hourly_count}",
                suggested_amount=0.0,
                volatility=volatility,
                consecutive_losses=self.position_sizer.consecutive_losses,
                daily_pnl=self._daily_pnl,
                trade_count_today=self._daily_trade_count
            )
        
        if self.position_sizer.consecutive_losses >= self.risk_config.circuit_breaker_consecutive_losses:
            self._activate_circuit_breaker()
            return RiskAssessment(
                can_trade=False,
                status=RiskStatus.CIRCUIT_BREAKER,
                reason=f"Circuit breaker: {self.position_sizer.consecutive_losses} pérdidas consecutivas",
                suggested_amount=0.0,
                volatility=volatility,
                consecutive_losses=self.position_sizer.consecutive_losses,
                daily_pnl=self._daily_pnl,
                trade_count_today=self._daily_trade_count
            )
        
        suggested_amount = self.position_sizer.calculate_bet_size(prediction.confidence)
        
        return RiskAssessment(
            can_trade=True,
            status=RiskStatus.OK,
            reason="Todas las verificaciones de riesgo pasadas",
            suggested_amount=suggested_amount,
            volatility=volatility,
            consecutive_losses=self.position_sizer.consecutive_losses,
            daily_pnl=self._daily_pnl,
            trade_count_today=self._daily_trade_count
        )
    
    def record_trade(
        self,
        direction: str,
        amount: float,
        entry_price: float,
        confidence: float,
        round_id: Optional[str] = None
    ) -> TradeRecord:
        """
        Registra una nueva operación.
        
        Args:
            direction: 'UP' o 'DOWN'
            amount: Monto apostado
            entry_price: Precio de entrada
            confidence: Confianza de la predicción
            round_id: ID de la ronda (opcional)
            
        Returns:
            Registro de la operación
        """
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc),
            direction=direction,
            amount=amount,
            entry_price=entry_price,
            confidence=confidence,
            round_id=round_id
        )
        
        self._trade_history.append(record)
        self._daily_trade_count += 1
        
        current_hour = datetime.now(timezone.utc).hour
        self._hourly_trade_counts[current_hour] = self._hourly_trade_counts.get(current_hour, 0) + 1
        
        self._last_trade_time = record.timestamp
        
        self.trading_logger.log_trade_execution(
            direction=direction,
            amount=amount,
            entry_price=entry_price,
            round_id=round_id
        )
        
        return record
    
    def record_result(
        self,
        trade_record: TradeRecord,
        exit_price: float,
        pnl: float
    ) -> None:
        """
        Registra el resultado de una operación.
        
        Args:
            trade_record: Registro de la operación
            exit_price: Precio de cierre
            pnl: Profit/Loss
        """
        trade_record.exit_price = exit_price
        trade_record.pnl = pnl
        trade_record.is_win = pnl > 0
        
        self._daily_pnl += pnl
        
        self.position_sizer.record_result(trade_record.is_win, pnl)
        
        result = "WIN" if trade_record.is_win else "LOSS"
        self.trading_logger.log_trade_result(
            result=result,
            pnl=pnl,
            cumulative_pnl=self._daily_pnl
        )
    
    def _activate_circuit_breaker(self) -> None:
        """Activa el circuit breaker."""
        self._circuit_breaker_active = True
        cooldown = timedelta(minutes=self.risk_config.circuit_breaker_cooldown_minutes)
        self._circuit_breaker_until = datetime.now(timezone.utc) + cooldown
        
        self.trading_logger.log_circuit_breaker(
            f"{self.position_sizer.consecutive_losses} pérdidas consecutivas. "
            f"Cooldown hasta {self._circuit_breaker_until}"
        )
        
        logger.warning(
            f"Circuit breaker activated! Cooldown until {self._circuit_breaker_until}"
        )
    
    def _check_day_reset(self) -> None:
        """Verifica si es un nuevo día y resetea contadores."""
        current_day = datetime.now(timezone.utc).day
        
        if self._current_day is None:
            self._current_day = current_day
        elif current_day != self._current_day:
            logger.info("New trading day - resetting daily counters")
            self._daily_pnl = 0.0
            self._daily_trade_count = 0
            self._hourly_trade_counts.clear()
            self._current_day = current_day
            self.position_sizer.reset_daily()
    
    def get_statistics(self) -> dict:
        """Retorna estadísticas de trading."""
        return {
            "total_trades": self.position_sizer.total_trades,
            "win_rate": self.position_sizer.win_rate,
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trade_count,
            "current_capital": self.position_sizer.current_capital,
            "consecutive_losses": self.position_sizer.consecutive_losses,
            "circuit_breaker_active": self._circuit_breaker_active,
        }
    
    def get_trade_history(self, limit: Optional[int] = None) -> list[TradeRecord]:
        """Retorna el historial de operaciones."""
        history = list(self._trade_history)
        if limit:
            return history[-limit:]
        return history
    
    @property
    def is_trading_allowed(self) -> bool:
        """Verifica rápidamente si se permite operar."""
        if self._circuit_breaker_active:
            if self._circuit_breaker_until and datetime.now(timezone.utc) >= self._circuit_breaker_until:
                self._circuit_breaker_active = False
                return True
            return False
        
        if self._daily_trade_count >= self.risk_config.max_trades_per_day:
            return False
        
        if abs(self._daily_pnl) >= self.risk_config.max_daily_loss:
            return False
        
        return True
