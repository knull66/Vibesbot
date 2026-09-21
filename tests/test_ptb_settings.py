import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.strategy_manager import StrategyManager
from src.updater import snooze_update, update_is_snoozed
from src.wallet_prediction import parse_btc_price, topic_start_price


class PriceToBeatParseTests(unittest.TestCase):
    def test_human_and_wei(self):
        self.assertAlmostEqual(parse_btc_price("86,047.04"), 86047.04)
        self.assertAlmostEqual(parse_btc_price(8604704000000), 86047.04)
        self.assertEqual(parse_btc_price("0.52"), 0.0)

    def test_nested_lock_key(self):
        topic = {"event": {"oracle": {"priceToBeat": "86047.04"}}}
        self.assertAlmostEqual(topic_start_price(topic), 86047.04)

    def test_does_not_use_live_tick(self):
        topic = {"currentPrice": "99999.00", "oracle": {"lockPrice": "86047.04"}}
        self.assertAlmostEqual(topic_start_price(topic), 86047.04)


class StrategyWeightSaveTests(unittest.TestCase):
    def test_nested_weights_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = StrategyManager(Path(tmp))
            updated = manager.update_strategy("default", {"weights": {"rsi": 3, "macd": 0}})
            self.assertIsNotNone(updated)
            self.assertEqual(updated.rsi_weight, 3)
            self.assertEqual(updated.macd_weight, 0)


class UpdateSnoozeTests(unittest.TestCase):
    def test_later_hides_same_version(self):
        class Settings:
            update_snooze_until = None
            update_snooze_version = None

        class Manager:
            settings = Settings()
            saved = False

            def save(self):
                self.saved = True

        hub = Manager()
        with patch("src.user_settings.get_settings_manager", return_value=hub):
            snooze_update("1.31.0", hours=12)
            self.assertTrue(hub.saved)
            self.assertTrue(update_is_snoozed("1.31.0"))
            self.assertFalse(update_is_snoozed("1.32.0"))


if __name__ == "__main__":
    unittest.main()
