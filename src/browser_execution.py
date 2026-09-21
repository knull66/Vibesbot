"""Legacy Event Contracts clicker — DISABLED.

The Mac app / dashboard never uses this module. REAL bets go through
Binance Wallet Prediction SAPI (Enable Prediction Trading). Opening
binance.com/prediction with Playwright is not an official bet API.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .config import BrowserConfig
from .utils.logger import get_logger

logger = get_logger("browser_execution")

DISABLED = (
    "Playwright scraping of binance.com/prediction is disabled. "
    "Use the Vibesbot app in REAL mode (Wallet Prediction API)."
)


@dataclass
class ExecutionResult:
    """Resultado de una ejecución de apuesta."""

    success: bool
    direction: str
    amount: float
    timestamp: datetime
    round_id: Optional[str] = None
    error: Optional[str] = None
    screenshot_path: Optional[str] = None


class BrowserExecutor:
    """Stub. Never opens Chromium or clicks Binance Event Contracts."""

    def __init__(self, config: Optional[BrowserConfig] = None):
        self.config = config or BrowserConfig()
        self._is_initialized = False
        self._execution_count = 0
        self._error_count = 0

    async def initialize(self) -> bool:
        logger.error(DISABLED)
        self._is_initialized = False
        return False

    async def navigate_to_prediction(self) -> bool:
        logger.error(DISABLED)
        return False

    async def execute_bet(
        self,
        direction: str,
        amount: float,
        wait_for_confirmation: bool = True,
    ) -> ExecutionResult:
        logger.error(DISABLED)
        return ExecutionResult(
            success=False,
            direction=direction,
            amount=amount,
            timestamp=datetime.now(timezone.utc),
            error=DISABLED,
        )

    async def wait_for_execution_window(self) -> float:
        return 0.0

    async def wait_for_round_result(self, timeout_seconds: int = 60) -> Optional[str]:
        return None

    async def close(self) -> None:
        self._is_initialized = False

    @property
    def is_ready(self) -> bool:
        return False

    @property
    def statistics(self) -> dict:
        return {
            "total_executions": self._execution_count,
            "total_errors": self._error_count,
            "error_rate": 0.0,
            "is_ready": False,
            "disabled": True,
        }


async def create_browser_executor(config: Optional[BrowserConfig] = None) -> BrowserExecutor:
    executor = BrowserExecutor(config)
    await executor.initialize()
    return executor
