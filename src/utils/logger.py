"""
Sistema de Logging centralizado para el bot de trading.
Proporciona logging a consola y archivo con formato estructurado.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import json


class JsonFormatter(logging.Formatter):
    """Formatter que produce logs en formato JSON para análisis posterior."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
            
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_entry)


class ColoredFormatter(logging.Formatter):
    """Formatter con colores para la consola."""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


_loggers: dict[str, logging.Logger] = {}


def setup_logger(
    name: str = "vibesbot",
    log_dir: str = "logs",
    level: int = logging.INFO,
    console_output: bool = True,
    file_output: bool = True,
    json_format: bool = False
) -> logging.Logger:
    """
    Configura y retorna un logger con handlers para consola y archivo.
    
    Args:
        name: Nombre del logger
        log_dir: Directorio para archivos de log
        level: Nivel mínimo de logging
        console_output: Si se debe mostrar en consola
        file_output: Si se debe guardar en archivo
        json_format: Si usar formato JSON para archivo
        
    Returns:
        Logger configurado
    """
    if name in _loggers:
        return _loggers[name]
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers = []
    
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_format = ColoredFormatter(
            "%(asctime)s | %(levelname)s | %(module)s:%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)
    
    if file_output:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = log_path / f"{name}_{date_str}.log"
        
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        
        if json_format:
            file_handler.setFormatter(JsonFormatter())
        else:
            file_format = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(module)s:%(funcName)s:%(lineno)d | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_format)
        
        logger.addHandler(file_handler)
    
    _loggers[name] = logger
    return logger


def get_logger(name: str = "vibesbot") -> logging.Logger:
    """
    Obtiene un logger existente o crea uno nuevo con configuración por defecto.
    
    Args:
        name: Nombre del logger
        
    Returns:
        Logger solicitado
    """
    if name not in _loggers:
        return setup_logger(name)
    return _loggers[name]


class TradingLogger:
    """Logger especializado para operaciones de trading con métricas estructuradas."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or get_logger("trading")
        self.trade_count = 0
        self.win_count = 0
        
    def log_prediction(
        self,
        signal: str,
        confidence: float,
        price: float,
        features: Optional[dict] = None
    ) -> None:
        """Registra una predicción del modelo."""
        msg = f"PREDICTION | Signal: {signal} | Confidence: {confidence:.2%} | Price: {price:.2f}"
        self.logger.info(msg)
        
    def log_trade_execution(
        self,
        direction: str,
        amount: float,
        entry_price: float,
        round_id: Optional[str] = None
    ) -> None:
        """Registra la ejecución de una operación."""
        self.trade_count += 1
        msg = f"TRADE #{self.trade_count} | Direction: {direction} | Amount: ${amount:.2f} | Entry: {entry_price:.2f}"
        if round_id:
            msg += f" | Round: {round_id}"
        self.logger.info(msg)
        
    def log_trade_result(
        self,
        result: str,
        pnl: float,
        cumulative_pnl: float
    ) -> None:
        """Registra el resultado de una operación."""
        if result == "WIN":
            self.win_count += 1
            
        win_rate = (self.win_count / self.trade_count * 100) if self.trade_count > 0 else 0
        msg = f"RESULT | {result} | PnL: ${pnl:+.2f} | Cumulative: ${cumulative_pnl:+.2f} | WinRate: {win_rate:.1f}%"
        
        if result == "WIN":
            self.logger.info(msg)
        else:
            self.logger.warning(msg)
            
    def log_risk_event(self, event_type: str, details: str) -> None:
        """Registra eventos de gestión de riesgo."""
        msg = f"RISK | {event_type} | {details}"
        self.logger.warning(msg)
        
    def log_circuit_breaker(self, reason: str) -> None:
        """Registra activación del circuit breaker."""
        msg = f"CIRCUIT BREAKER ACTIVATED | Reason: {reason}"
        self.logger.critical(msg)
