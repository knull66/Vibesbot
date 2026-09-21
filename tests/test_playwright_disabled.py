import ast
import pathlib
import subprocess
import sys
import unittest

from src.browser_execution import DISABLED, BrowserExecutor
from src.main import TradingBot

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PlaywrightDisabledTests(unittest.IsolatedAsyncioTestCase):
    async def test_never_opens_chromium(self):
        executor = BrowserExecutor()
        self.assertFalse(await executor.initialize())
        self.assertFalse(await executor.navigate_to_prediction())
        result = await executor.execute_bet("UP", 1.5)
        self.assertFalse(result.success)
        self.assertIn("disabled", result.error.lower())
        self.assertIn("Wallet Prediction", DISABLED)
        self.assertFalse(executor.is_ready)
        self.assertIsNone(await executor.wait_for_round_result())

    async def test_trading_bot_initialize_refuses(self):
        bot = TradingBot()
        self.assertFalse(await bot.initialize())
        self.assertIsNone(bot.browser)


class PlaywrightRemovedFromRepoTests(unittest.TestCase):
    def test_module_has_no_playwright_import(self):
        src = (ROOT / "src" / "browser_execution.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(alias.name.startswith("playwright"))
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith("playwright"))
        self.assertNotIn("async_playwright", src)
        self.assertNotIn("from playwright", src)
        self.assertNotIn("_click_element", src)
        self.assertNotIn("binance.com/en/prediction", src)

    def test_requirements_drop_playwright(self):
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("playwright", req)

    def test_run_bot_cli_exits(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "run_bot.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        combined = (proc.stdout + proc.stderr).lower()
        self.assertIn("disabled", combined)
        self.assertIn("playwright", combined)


if __name__ == "__main__":
    unittest.main()
