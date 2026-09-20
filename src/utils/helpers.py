"""
Funciones de utilidad para el bot de trading.
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional
import aiohttp


async def get_binance_server_time() -> int:
    """
    Obtiene el tiempo del servidor de Binance.
    
    Returns:
        Timestamp en milisegundos del servidor Binance
        
    Raises:
        Exception: Si no se puede conectar al servidor
    """
    urls = [
        "https://data-api.binance.vision/api/v3/time",
        "https://api.binance.com/api/v3/time",
    ]
    
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["serverTime"]
            except Exception:
                continue
        
        from datetime import datetime, timezone
        return int(datetime.now(timezone.utc).timestamp() * 1000)


async def sync_binance_time() -> float:
    """
    Calcula el offset entre el tiempo local y el servidor de Binance.
    
    Returns:
        Offset en segundos (positivo si el servidor está adelantado)
    """
    local_time_before = datetime.now(timezone.utc).timestamp() * 1000
    server_time = await get_binance_server_time()
    local_time_after = datetime.now(timezone.utc).timestamp() * 1000
    
    local_time_avg = (local_time_before + local_time_after) / 2
    offset_ms = server_time - local_time_avg
    
    return offset_ms / 1000


def calculate_time_to_next_round(
    interval_minutes: int = 5,
    execution_offset_seconds: int = 12,
    time_offset: float = 0
) -> float:
    """
    Calcula los segundos hasta la siguiente ventana de ejecución.
    
    Las rondas de Binance Prediction se cierran cada 5 minutos.
    Queremos ejecutar la apuesta justo antes del cierre.
    
    Args:
        interval_minutes: Intervalo de las rondas en minutos
        execution_offset_seconds: Segundos antes del cierre para ejecutar
        time_offset: Offset de sincronización con Binance
        
    Returns:
        Segundos hasta la próxima ventana de ejecución
    """
    now = datetime.now(timezone.utc).timestamp() + time_offset
    interval_seconds = interval_minutes * 60
    
    current_position = now % interval_seconds
    seconds_to_round_end = interval_seconds - current_position
    
    target_seconds = seconds_to_round_end - execution_offset_seconds
    
    if target_seconds < 0:
        target_seconds += interval_seconds
        
    return target_seconds


def calculate_round_times(interval_minutes: int = 5, time_offset: float = 0) -> dict:
    """
    Calcula información detallada sobre la ronda actual y siguiente.
    
    Args:
        interval_minutes: Intervalo de las rondas en minutos
        time_offset: Offset de sincronización con Binance
        
    Returns:
        Diccionario con información de tiempos
    """
    now = datetime.now(timezone.utc).timestamp() + time_offset
    interval_seconds = interval_minutes * 60
    
    current_position = now % interval_seconds
    round_start = now - current_position
    round_end = round_start + interval_seconds
    
    # Número de ronda (basado en el inicio del día UTC)
    day_start = int(now) - (int(now) % 86400)
    round_number = int((now - day_start) // interval_seconds)
    
    return {
        "current_timestamp": now,
        "round_start": round_start,
        "round_end": round_end,
        "seconds_elapsed": current_position,
        "seconds_remaining": interval_seconds - current_position,
        "progress_percent": (current_position / interval_seconds) * 100,
        "round_number": round_number
    }


def format_price(price: float, decimals: int = 2) -> str:
    """Formatea un precio para display."""
    return f"${price:,.{decimals}f}"


def format_percentage(value: float, decimals: int = 2) -> str:
    """Formatea un porcentaje para display."""
    return f"{value * 100:.{decimals}f}%"


def calculate_pnl(
    entry_price: float,
    exit_price: float,
    direction: str,
    amount: float,
    fee_percent: float = 0.0
) -> float:
    """
    Calcula el PnL de una operación de prediction.
    
    En Binance Prediction, ganamos ~0.95x si acertamos y perdemos todo si fallamos.
    
    Args:
        entry_price: Precio de entrada (apertura de la ronda)
        exit_price: Precio de salida (cierre de la ronda)
        direction: 'UP' o 'DOWN'
        amount: Monto apostado
        fee_percent: Porcentaje de comisión
        
    Returns:
        PnL de la operación
    """
    actual_direction = "UP" if exit_price > entry_price else "DOWN"
    
    if direction == actual_direction:
        payout_multiplier = 0.95 - fee_percent
        return amount * payout_multiplier
    else:
        return -amount


async def exponential_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True
) -> None:
    """
    Implementa espera con backoff exponencial.
    
    Args:
        attempt: Número de intento (comenzando en 0)
        base_delay: Delay base en segundos
        max_delay: Delay máximo en segundos
        jitter: Si agregar variación aleatoria
    """
    import random
    
    delay = min(base_delay * (2 ** attempt), max_delay)
    
    if jitter:
        delay = delay * (0.5 + random.random())
        
    await asyncio.sleep(delay)


class RateLimiter:
    """Rate limiter simple para llamadas a APIs."""
    
    def __init__(self, calls_per_second: float = 10.0):
        self.min_interval = 1.0 / calls_per_second
        self.last_call: Optional[float] = None
        self._lock = asyncio.Lock()
        
    async def acquire(self) -> None:
        """Espera si es necesario para respetar el rate limit."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            
            if self.last_call is not None:
                elapsed = now - self.last_call
                if elapsed < self.min_interval:
                    await asyncio.sleep(self.min_interval - elapsed)
                    
            self.last_call = asyncio.get_event_loop().time()
