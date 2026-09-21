import json
import tempfile
import unittest
from pathlib import Path

from src.config import Config
from src.updater import RETIRED_CLICKER_FILES, Updater, purge_retired_from, purge_retired_installs

ROOT = Path(__file__).resolve().parents[1]


class PlaywrightRemovedFromRepoTests(unittest.TestCase):
    def test_clicker_files_are_gone(self):
        for rel in RETIRED_CLICKER_FILES:
            self.assertFalse((ROOT / rel).exists(), rel)
        self.assertFalse((ROOT / "src" / "browser_execution.py").exists())
        self.assertFalse((ROOT / "run_bot.py").exists())
        self.assertFalse((ROOT / "Procfile").exists())
        self.assertFalse((ROOT / "requirements-web.txt").exists())

    def test_requirements_drop_playwright(self):
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("playwright", req)
        example = (ROOT / "config.example.json").read_text(encoding="utf-8")
        self.assertNotIn('"browser"', example)

    def test_config_ignores_legacy_browser_block(self):
        cfg = Config()
        self.assertFalse(hasattr(cfg, "browser"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "trading": {"initial_capital": 50},
                        "browser": {
                            "headless": True,
                            "binance_prediction_url": "https://www.binance.com/en/prediction/BTCUSDT",
                        },
                    }
                ),
                encoding="utf-8",
            )
            loaded = Config.from_json(str(path))
            self.assertEqual(loaded.trading.initial_capital, 50)
            self.assertFalse(hasattr(loaded, "browser"))

    def test_updater_purges_leftover_clicker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "__pycache__").mkdir(parents=True)
            (root / "src" / "browser_execution.py").write_text("old clicker", encoding="utf-8")
            (root / "src" / "main.py").write_text("old main", encoding="utf-8")
            (root / "run_bot.py").write_text("old cli", encoding="utf-8")
            (root / "Procfile").write_text("web: old", encoding="utf-8")
            (root / "playwright_stub.py").write_text("pw", encoding="utf-8")
            (root / ".playwright").mkdir()
            (root / ".playwright" / "chrome").write_text("x", encoding="utf-8")
            (root / "src" / "__pycache__" / "browser_execution.cpython-312.pyc").write_bytes(b"x")
            (root / "src" / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"x")
            (root / "src" / "wallet_prediction.py").write_text("keep", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_playwright_removed.py").write_text("keep test", encoding="utf-8")
            updater = Updater(app_path=str(root))
            updater._purge_retired_clicker()
            for rel in ("src/browser_execution.py", "src/main.py", "run_bot.py", "Procfile"):
                self.assertFalse((root / rel).exists(), rel)
            self.assertFalse((root / "playwright_stub.py").exists())
            self.assertFalse((root / ".playwright").exists())
            self.assertFalse((root / "src" / "__pycache__" / "browser_execution.cpython-312.pyc").exists())
            self.assertFalse((root / "src" / "__pycache__" / "main.cpython-312.pyc").exists())
            self.assertEqual((root / "src" / "wallet_prediction.py").read_text(encoding="utf-8"), "keep")
            self.assertEqual((root / "tests" / "test_playwright_removed.py").read_text(encoding="utf-8"), "keep test")

    def test_purge_also_cleans_a_downloads_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            downloads = Path(tmp) / "Downloads" / "Vibesbot"
            for folder in (app, downloads):
                (folder / "src").mkdir(parents=True)
                (folder / "run_bot.py").write_text("clicker", encoding="utf-8")
            (app / "src" / "wallet_prediction.py").write_text("keep", encoding="utf-8")
            removed = purge_retired_installs(app, extra_roots=[downloads])
            self.assertGreaterEqual(removed, 2)
            self.assertFalse((app / "run_bot.py").exists())
            self.assertFalse((downloads / "run_bot.py").exists())
            self.assertEqual((app / "src" / "wallet_prediction.py").read_text(encoding="utf-8"), "keep")
            self.assertEqual(purge_retired_from(app), 0)


if __name__ == "__main__":
    unittest.main()
