"""
Orquestador principal del bot de trading.

Coordina todos los módulos del sistema en un bucle de trading continuo:
1. Recibe datos en tiempo real
2. Genera predicciones con el modelo
3. Evalúa riesgo
4. Ejecuta apuestas
5. Registra resultados
"""
import asyncio
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import argparse

from .config import Config, load_config
from .data_stream import DataStream, create_data_stream
from .predictor import Predictor, Signal, ModelType
from .risk_manager import RiskManager, RiskStatus
from .browser_execution import BrowserExecutor, create_browser_executor
from .utils.logger import setup_logger, get_logger, TradingLogger


class TradingBot:
    """
    Bot de trading automatizado para Binance Prediction.
    
    Implementa el ciclo completo de trading:
    - Sincronización con rondas de 5 minutos
    - Predicción con modelo ML
    - Gestión de riesgo
    - Ejecución de apuestas
    - Tracking de resultados
    """
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or load_config()
        
        self.logger = setup_logger(
            name="vibesbot",
            log_dir=self.config.logging.log_dir,
            console_output=self.config.logging.console_output,
            file_output=self.config.logging.file_output,
            json_format=self.config.logging.json_format
        )
        self.trading_logger = TradingLogger(self.logger)
        
        self.data_stream: Optional[DataStream] = None
        self.predictor: Optional[Predictor] = None
        self.risk_manager: Optional[RiskManager] = None
        self.browser: Optional[BrowserExecutor] = None
        
        self._running = False
        self._paused = False
        self._round_count = 0
        self._shutdown_event = asyncio.Event()
    
    async def initialize(self) -> bool:
        """
        Inicializa todos los componentes del bot.
        
        Returns:
            True si todos los componentes se inicializaron correctamente
        """
        self.logger.info("=" * 60)
        self.logger.info("VIBESBOT - Binance Prediction Trading Bot")
        self.logger.info("=" * 60)
        
        errors = self.config.validate()
        if errors:
            for error in errors:
                self.logger.error(f"Config validation error: {error}")
            return False
        
        self.logger.info("Initializing data stream...")
        try:
            self.data_stream = DataStream(self.config.data_stream)
            await self.data_stream.start()
            self.logger.info("Data stream initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize data stream: {e}")
            return False
        
        self.logger.info("Initializing predictor...")
        try:
            model_type = ModelType.LIGHTGBM
            self.predictor = Predictor(self.config.prediction, model_type)
            
            if not await self.predictor.initialize():
                self.logger.warning("No pre-trained model found. Bot will need training data.")
        except Exception as e:
            self.logger.error(f"Failed to initialize predictor: {e}")
            return False
        
        self.logger.info("Initializing risk manager...")
        self.risk_manager = RiskManager(self.config.risk, self.config.trading)
        self.logger.info("Risk manager initialized")
        
        self.logger.info("Initializing browser executor...")
        try:
            self.browser = BrowserExecutor(self.config.browser)
            if not await self.browser.initialize():
                self.logger.error("Failed to initialize browser")
                return False
            
            if not await self.browser.navigate_to_prediction():
                self.logger.warning("Could not navigate to prediction page. Manual login may be required.")
        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {e}")
            return False
        
        await asyncio.sleep(5)
        
        self.logger.info("=" * 60)
        self.logger.info("All components initialized successfully!")
        self.logger.info(f"Initial Capital: ${self.config.trading.initial_capital}")
        self.logger.info(f"Confidence Threshold: {self.config.prediction.confidence_threshold:.0%}")
        self.logger.info(f"Max Daily Loss: ${self.config.risk.max_daily_loss}")
        self.logger.info("=" * 60)
        
        return True
    
    async def run(self) -> None:
        """
        Ejecuta el bucle principal de trading.
        
        El bot opera en ciclos sincronizados con las rondas de 5 minutos
        de Binance Prediction, ejecutando apuestas justo antes del cierre.
        """
        self._running = True
        self.logger.info("Starting trading loop...")
        
        while self._running:
            try:
                if self._paused:
                    await asyncio.sleep(1)
                    continue
                
                if not self.risk_manager.is_trading_allowed:
                    self.logger.info("Trading not allowed. Waiting for conditions to change...")
                    await asyncio.sleep(60)
                    continue
                
                wait_time = await self.browser.wait_for_execution_window()
                
                if not self._running:
                    break
                
                await self._execute_round()
                
                await asyncio.sleep(5)
                
            except asyncio.CancelledError:
                self.logger.info("Trading loop cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in trading loop: {e}", exc_info=True)
                await asyncio.sleep(30)
        
        self.logger.info("Trading loop ended")
    
    async def _execute_round(self) -> None:
        """Ejecuta el ciclo de una ronda de trading."""
        self._round_count += 1
        self.logger.info(f"--- Round #{self._round_count} ---")
        
        current_price = self.data_stream.get_current_price()
        if current_price:
            self.logger.info(f"Current Price: ${current_price:,.2f}")
        
        if not self.predictor.is_ready:
            self.logger.warning("Predictor not ready (no trained model). Skipping round.")
            return
        
        prediction = await self.predictor.predict(self.data_stream)
        
        self.trading_logger.log_prediction(
            signal=prediction.signal.value,
            confidence=prediction.confidence,
            price=current_price or 0
        )
        
        if prediction.signal == Signal.WAIT:
            self.logger.info(f"Signal: WAIT (confidence {prediction.confidence:.1%} below threshold)")
            return
        
        risk_assessment = self.risk_manager.assess_risk(prediction, self.data_stream)
        
        self.logger.info(f"Risk Assessment: {risk_assessment.status.value}")
        
        if not risk_assessment.can_trade:
            self.logger.warning(f"Trade blocked: {risk_assessment.reason}")
            self.trading_logger.log_risk_event(
                risk_assessment.status.value,
                risk_assessment.reason
            )
            return
        
        direction = prediction.signal.value
        amount = risk_assessment.suggested_amount
        
        self.logger.info(f"Executing trade: {direction} ${amount:.2f}")
        
        result = await self.browser.execute_bet(direction, amount)
        
        if not result.success:
            self.logger.error(f"Trade execution failed: {result.error}")
            return
        
        trade_record = self.risk_manager.record_trade(
            direction=direction,
            amount=amount,
            entry_price=current_price or 0,
            confidence=prediction.confidence,
            round_id=result.round_id
        )
        
        self.logger.info("Waiting for round result...")
        round_result = await self.browser.wait_for_round_result(timeout_seconds=45)
        
        if round_result:
            exit_price = self.data_stream.get_current_price() or current_price or 0
            is_win = round_result == direction
            
            payout_rate = 0.95
            if is_win:
                pnl = amount * payout_rate
            else:
                pnl = -amount
            
            self.risk_manager.record_result(trade_record, exit_price, pnl)
            
            stats = self.risk_manager.get_statistics()
            self.logger.info(
                f"Round Result: {'WIN' if is_win else 'LOSS'} | "
                f"PnL: ${pnl:+.2f} | "
                f"Daily PnL: ${stats['daily_pnl']:+.2f} | "
                f"Win Rate: {stats['win_rate']:.1%}"
            )
        else:
            self.logger.warning("Could not determine round result")
    
    async def shutdown(self) -> None:
        """Cierra todos los componentes de forma ordenada."""
        self.logger.info("Shutting down bot...")
        self._running = False
        
        if self.data_stream:
            await self.data_stream.stop()
        
        if self.browser:
            await self.browser.close()
        
        stats = self.risk_manager.get_statistics() if self.risk_manager else {}
        
        self.logger.info("=" * 60)
        self.logger.info("TRADING SESSION SUMMARY")
        self.logger.info("=" * 60)
        self.logger.info(f"Total Rounds: {self._round_count}")
        self.logger.info(f"Total Trades: {stats.get('total_trades', 0)}")
        self.logger.info(f"Win Rate: {stats.get('win_rate', 0):.1%}")
        self.logger.info(f"Final Capital: ${stats.get('current_capital', 0):,.2f}")
        self.logger.info(f"Daily P&L: ${stats.get('daily_pnl', 0):+.2f}")
        self.logger.info("=" * 60)
        self.logger.info("Bot shutdown complete")
    
    def pause(self) -> None:
        """Pausa la operativa sin cerrar el bot."""
        self._paused = True
        self.logger.info("Trading paused")
    
    def resume(self) -> None:
        """Reanuda la operativa."""
        self._paused = False
        self.logger.info("Trading resumed")
    
    def stop(self) -> None:
        """Señala al bot que debe detenerse."""
        self._running = False


async def main(config_path: Optional[str] = None) -> None:
    """
    Punto de entrada principal del bot.
    
    Args:
        config_path: Ruta opcional al archivo de configuración
    """
    config = load_config(config_path)
    bot = TradingBot(config)
    
    loop = asyncio.get_event_loop()
    
    def signal_handler(sig, frame):
        print("\nShutdown signal received...")
        bot.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if not await bot.initialize():
            print("Failed to initialize bot. Check logs for details.")
            sys.exit(1)
        
        await bot.run()
        
    except Exception as e:
        print(f"Fatal error: {e}")
        raise
    finally:
        await bot.shutdown()


def run_bot():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Vibesbot - Binance Prediction Trading Bot"
    )
    parser.add_argument(
        "-c", "--config",
        type=str,
        help="Path to configuration file (JSON)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode"
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use Binance testnet"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without executing actual trades"
    )
    
    args = parser.parse_args()
    
    if args.headless:
        import os
        os.environ["VIBESBOT_HEADLESS"] = "true"
    
    if args.testnet:
        import os
        os.environ["VIBESBOT_TESTNET"] = "true"
    
    asyncio.run(main(args.config))


if __name__ == "__main__":
    run_bot()
