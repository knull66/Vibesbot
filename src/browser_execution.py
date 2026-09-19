"""
Módulo de automatización del navegador con Playwright.

Proporciona:
- Cliente asíncrono con contexto persistente
- Sincronización precisa con el reloj del mercado
- Manejo de excepciones y reintentos
- Captura de errores y screenshots
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Any
import json

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout

from .config import BrowserConfig
from .utils.logger import get_logger
from .utils.helpers import calculate_time_to_next_round, sync_binance_time


logger = get_logger("browser_execution")


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
    """
    Cliente de automatización de navegador para Binance Prediction.
    
    Maneja la sesión del usuario, sincronización de tiempo y
    ejecución de apuestas con manejo robusto de errores.
    """
    
    def __init__(self, config: Optional[BrowserConfig] = None):
        self.config = config or BrowserConfig()
        
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        
        self._is_initialized = False
        self._time_offset = 0.0
        
        self._execution_count = 0
        self._error_count = 0
        
        Path(self.config.user_data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.config.screenshot_dir).mkdir(parents=True, exist_ok=True)
    
    async def initialize(self) -> bool:
        """
        Inicializa el navegador con contexto persistente.
        
        Returns:
            True si la inicialización fue exitosa
        """
        try:
            logger.info("Initializing browser...")
            
            self._playwright = await async_playwright().start()
            
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.config.user_data_dir,
                headless=self.config.headless,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
            
            self._page = await self._context.new_page()
            
            await self._page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
            })
            
            await self._sync_time()
            
            self._is_initialized = True
            logger.info("Browser initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            await self._capture_error_screenshot("init_error")
            return False
    
    async def navigate_to_prediction(self) -> bool:
        """
        Navega a la página de Binance Prediction.
        
        Returns:
            True si la navegación fue exitosa
        """
        if not self._is_initialized:
            logger.error("Browser not initialized")
            return False
        
        try:
            logger.info(f"Navigating to {self.config.binance_prediction_url}")
            
            await self._page.goto(
                self.config.binance_prediction_url,
                timeout=self.config.page_load_timeout_ms,
                wait_until="networkidle"
            )
            
            await asyncio.sleep(2)
            
            is_logged_in = await self._check_login_status()
            
            if not is_logged_in:
                logger.warning("User not logged in - manual login required")
                return False
            
            logger.info("Successfully navigated to prediction page")
            return True
            
        except PlaywrightTimeout:
            logger.error("Timeout navigating to prediction page")
            await self._capture_error_screenshot("navigation_timeout")
            return False
        except Exception as e:
            logger.error(f"Error navigating to prediction page: {e}")
            await self._capture_error_screenshot("navigation_error")
            return False
    
    async def _check_login_status(self) -> bool:
        """Verifica si el usuario está logueado."""
        try:
            login_indicators = [
                '[data-testid="user-menu"]',
                '.user-menu',
                '[class*="userCenter"]',
            ]
            
            for selector in login_indicators:
                try:
                    element = await self._page.wait_for_selector(
                        selector,
                        timeout=3000,
                        state="visible"
                    )
                    if element:
                        return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            logger.warning(f"Error checking login status: {e}")
            return False
    
    async def execute_bet(
        self,
        direction: str,
        amount: float,
        wait_for_confirmation: bool = True
    ) -> ExecutionResult:
        """
        Ejecuta una apuesta en la dirección especificada.
        
        Args:
            direction: 'UP' o 'DOWN'
            amount: Monto a apostar
            wait_for_confirmation: Si esperar confirmación de la orden
            
        Returns:
            Resultado de la ejecución
        """
        if not self._is_initialized:
            return ExecutionResult(
                success=False,
                direction=direction,
                amount=amount,
                timestamp=datetime.now(timezone.utc),
                error="Browser not initialized"
            )
        
        self._execution_count += 1
        
        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"Executing bet: {direction} ${amount} (attempt {attempt + 1})")
                
                button_selector = (
                    self.config.selectors["up_button"] 
                    if direction == "UP" 
                    else self.config.selectors["down_button"]
                )
                
                await self._click_element(button_selector)
                await asyncio.sleep(0.3)
                
                await self._enter_amount(amount)
                await asyncio.sleep(0.3)
                
                await self._click_element(self.config.selectors["confirm_button"])
                
                if wait_for_confirmation:
                    confirmed = await self._wait_for_confirmation()
                    if not confirmed:
                        raise Exception("Order confirmation not received")
                
                logger.info(f"Bet executed successfully: {direction} ${amount}")
                
                return ExecutionResult(
                    success=True,
                    direction=direction,
                    amount=amount,
                    timestamp=datetime.now(timezone.utc),
                    round_id=await self._get_current_round_id()
                )
                
            except Exception as e:
                logger.warning(f"Bet execution failed (attempt {attempt + 1}): {e}")
                
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds)
                else:
                    self._error_count += 1
                    screenshot_path = await self._capture_error_screenshot(f"bet_error_{self._execution_count}")
                    
                    return ExecutionResult(
                        success=False,
                        direction=direction,
                        amount=amount,
                        timestamp=datetime.now(timezone.utc),
                        error=str(e),
                        screenshot_path=screenshot_path
                    )
        
        return ExecutionResult(
            success=False,
            direction=direction,
            amount=amount,
            timestamp=datetime.now(timezone.utc),
            error="Max retries exceeded"
        )
    
    async def _click_element(self, selector: str) -> None:
        """Hace clic en un elemento del DOM."""
        try:
            await self._page.wait_for_selector(
                selector,
                timeout=self.config.action_timeout_ms,
                state="visible"
            )
            await self._page.click(selector, timeout=self.config.action_timeout_ms)
        except PlaywrightTimeout:
            fallback_selectors = self._get_fallback_selectors(selector)
            for fallback in fallback_selectors:
                try:
                    await self._page.click(fallback, timeout=2000)
                    return
                except:
                    continue
            raise
    
    async def _enter_amount(self, amount: float) -> None:
        """Ingresa el monto de la apuesta."""
        input_selector = self.config.selectors["amount_input"]
        
        try:
            await self._page.wait_for_selector(
                input_selector,
                timeout=self.config.action_timeout_ms,
                state="visible"
            )
            
            await self._page.click(input_selector, click_count=3)
            await self._page.keyboard.press("Backspace")
            
            await self._page.fill(input_selector, str(amount))
            
        except Exception as e:
            logger.warning(f"Error entering amount via selector, trying keyboard: {e}")
            await self._page.keyboard.type(str(amount), delay=50)
    
    async def _wait_for_confirmation(self, timeout: int = 5000) -> bool:
        """Espera confirmación de la orden."""
        try:
            confirmation_selectors = [
                '[data-testid="order-confirmed"]',
                '.order-success',
                '[class*="success"]',
                'text=Order Placed',
                'text=Confirmed',
            ]
            
            for selector in confirmation_selectors:
                try:
                    await self._page.wait_for_selector(
                        selector,
                        timeout=timeout,
                        state="visible"
                    )
                    return True
                except:
                    continue
            
            await asyncio.sleep(1)
            return True
            
        except Exception as e:
            logger.warning(f"Confirmation check error: {e}")
            return False
    
    async def _get_current_round_id(self) -> Optional[str]:
        """Obtiene el ID de la ronda actual."""
        try:
            round_selector = self.config.selectors.get("round_timer", '[data-testid="round-timer"]')
            element = await self._page.query_selector(round_selector)
            if element:
                round_id = await element.get_attribute("data-round-id")
                return round_id
        except:
            pass
        return None
    
    async def get_current_price(self) -> Optional[float]:
        """Obtiene el precio actual mostrado en la página."""
        try:
            price_selector = self.config.selectors.get("current_price", '[data-testid="current-price"]')
            
            price_selectors = [
                price_selector,
                '.price-value',
                '[class*="price"]',
                '[class*="lastPrice"]',
            ]
            
            for selector in price_selectors:
                try:
                    element = await self._page.wait_for_selector(selector, timeout=2000)
                    if element:
                        text = await element.inner_text()
                        price = float(text.replace(",", "").replace("$", ""))
                        return price
                except:
                    continue
                    
        except Exception as e:
            logger.warning(f"Error getting current price: {e}")
        
        return None
    
    async def get_round_timer(self) -> Optional[int]:
        """Obtiene los segundos restantes de la ronda actual."""
        try:
            timer_selector = self.config.selectors.get("round_timer", '[data-testid="round-timer"]')
            
            element = await self._page.query_selector(timer_selector)
            if element:
                text = await element.inner_text()
                parts = text.split(":")
                if len(parts) == 2:
                    minutes, seconds = int(parts[0]), int(parts[1])
                    return minutes * 60 + seconds
                return int(text)
                
        except Exception as e:
            logger.warning(f"Error getting round timer: {e}")
        
        return None
    
    async def wait_for_execution_window(self) -> float:
        """
        Espera hasta la ventana de ejecución óptima.
        
        Returns:
            Segundos que se esperaron
        """
        wait_time = calculate_time_to_next_round(
            interval_minutes=5,
            execution_offset_seconds=self.config.execution_offset_seconds,
            time_offset=self._time_offset
        )
        
        if wait_time > 0:
            logger.info(f"Waiting {wait_time:.1f}s for execution window...")
            await asyncio.sleep(wait_time)
        
        return wait_time
    
    async def wait_for_round_result(self, timeout_seconds: int = 60) -> Optional[str]:
        """
        Espera el resultado de la ronda actual.
        
        Args:
            timeout_seconds: Tiempo máximo de espera
            
        Returns:
            'UP', 'DOWN' o None si no se pudo determinar
        """
        try:
            result_selector = self.config.selectors.get("round_result", '[data-testid="round-result"]')
            
            result_selectors = [
                result_selector,
                '[class*="result"]',
                '[class*="outcome"]',
            ]
            
            start_time = asyncio.get_event_loop().time()
            
            while asyncio.get_event_loop().time() - start_time < timeout_seconds:
                for selector in result_selectors:
                    try:
                        element = await self._page.query_selector(selector)
                        if element:
                            text = (await element.inner_text()).upper()
                            if "UP" in text or "BULL" in text:
                                return "UP"
                            elif "DOWN" in text or "BEAR" in text:
                                return "DOWN"
                    except:
                        continue
                
                await asyncio.sleep(1)
            
        except Exception as e:
            logger.warning(f"Error waiting for round result: {e}")
        
        return None
    
    def _get_fallback_selectors(self, original: str) -> list[str]:
        """Genera selectores alternativos para un selector dado."""
        fallbacks = []
        
        if "up" in original.lower():
            fallbacks.extend([
                'button:has-text("UP")',
                'button:has-text("Bull")',
                '[class*="up"]',
                '[class*="bull"]',
            ])
        elif "down" in original.lower():
            fallbacks.extend([
                'button:has-text("DOWN")',
                'button:has-text("Bear")',
                '[class*="down"]',
                '[class*="bear"]',
            ])
        elif "confirm" in original.lower():
            fallbacks.extend([
                'button:has-text("Confirm")',
                'button:has-text("Place")',
                'button:has-text("Submit")',
                '[class*="confirm"]',
                '[class*="submit"]',
            ])
        elif "amount" in original.lower() or "input" in original.lower():
            fallbacks.extend([
                'input[type="number"]',
                'input[placeholder*="amount"]',
                'input[placeholder*="Amount"]',
                '[class*="amount"] input',
            ])
        
        return fallbacks
    
    async def _sync_time(self) -> None:
        """Sincroniza con el tiempo del servidor de Binance."""
        try:
            self._time_offset = await sync_binance_time()
            logger.info(f"Time synchronized. Offset: {self._time_offset:.3f}s")
        except Exception as e:
            logger.warning(f"Failed to sync time: {e}. Using local time.")
            self._time_offset = 0.0
    
    async def _capture_error_screenshot(self, name: str) -> Optional[str]:
        """Captura screenshot en caso de error."""
        if not self.config.screenshot_on_error or not self._page:
            return None
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{name}_{timestamp}.png"
            filepath = Path(self.config.screenshot_dir) / filename
            
            await self._page.screenshot(path=str(filepath), full_page=True)
            logger.info(f"Screenshot saved: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.warning(f"Failed to capture screenshot: {e}")
            return None
    
    async def close(self) -> None:
        """Cierra el navegador y limpia recursos."""
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
            
            self._is_initialized = False
            logger.info("Browser closed")
            
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")
    
    @property
    def is_ready(self) -> bool:
        """Verifica si el navegador está listo para ejecutar."""
        return self._is_initialized and self._page is not None
    
    @property
    def statistics(self) -> dict:
        """Retorna estadísticas de ejecución."""
        return {
            "total_executions": self._execution_count,
            "total_errors": self._error_count,
            "error_rate": self._error_count / max(1, self._execution_count),
            "is_ready": self.is_ready,
        }


async def create_browser_executor(config: Optional[BrowserConfig] = None) -> BrowserExecutor:
    """
    Factory function para crear e inicializar un BrowserExecutor.
    
    Args:
        config: Configuración opcional
        
    Returns:
        BrowserExecutor inicializado y listo para usar
    """
    executor = BrowserExecutor(config)
    await executor.initialize()
    return executor
