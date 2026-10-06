import tempfile
import unittest
from pathlib import Path

from src.user_settings import (
    SettingsManager,
    binance_testnet_from_payload,
    describe_binance_error,
    effective_confidence_threshold,
    is_kept_secret,
)


class BinanceFlagTests(unittest.TestCase):
    def test_js_testnet_false(self):
        self.assertFalse(binance_testnet_from_payload({"testnet": False}))

    def test_legacy_62_threshold_allows_61_signal(self):
        self.assertEqual(effective_confidence_threshold(0.62), 0.50)
        self.assertEqual(effective_confidence_threshold(None), 0.50)
        self.assertEqual(effective_confidence_threshold(0.70), 0.70)
        self.assertGreaterEqual(0.61, effective_confidence_threshold(0.62))

    def test_js_testnet_true(self):
        self.assertTrue(binance_testnet_from_payload({"testnet": True}))

    def test_missing_defaults_to_live(self):
        self.assertFalse(binance_testnet_from_payload({}))

    def test_live_key_on_testnet_gets_hint(self):
        text = describe_binance_error(
            401,
            {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."},
            True,
        )
        self.assertIn("Uncheck Use Testnet", text)

    def test_placeholder_secret_is_kept(self):
        self.assertTrue(is_kept_secret(""))
        self.assertTrue(is_kept_secret("********"))
        self.assertTrue(is_kept_secret("Saved on this Mac — leave blank to keep"))
        self.assertFalse(is_kept_secret("real-secret-value"))

    def test_reload_keeps_secret_when_form_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SettingsManager(Path(tmp))
            manager.update_binance_credentials("live-key", "live-secret", False)
            manager.update_binance_credentials("", "", False)
            self.assertEqual(manager.settings.binance.api_key, "live-key")
            self.assertEqual(manager.settings.binance.api_secret, "live-secret")
            again = SettingsManager(Path(tmp))
            self.assertTrue(again.settings.binance.is_configured)
            self.assertEqual(again.settings.binance.api_secret, "live-secret")
            self.assertEqual(again.settings.binance.prediction_wallet, "")

    def test_trading_settings_apply_to_sim_and_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SettingsManager(Path(tmp))
            manager.update_trading_settings(bet_amount=1.0, daily_loss_limit=12, confidence_threshold=0.55)
            self.assertEqual(manager.settings.trading.bet_amount, 1.5)
            self.assertEqual(manager.settings.trading.max_daily_loss, 12.0)
            payload = manager.settings.trading.to_dict()
            self.assertEqual(payload["daily_loss_limit"], 12.0)
            again = SettingsManager(Path(tmp))
            self.assertEqual(again.settings.trading.bet_amount, 1.5)
            self.assertEqual(again.settings.trading.max_daily_loss, 12.0)

    def test_percent_stake_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SettingsManager(Path(tmp))
            manager.update_trading_settings(stake_mode="percent", bet_percent=2, daily_loss_pct=15)
            self.assertEqual(manager.settings.trading.stake_mode, "percent")
            self.assertEqual(manager.settings.trading.bet_percent, 2.0)
            self.assertEqual(manager.settings.trading.daily_loss_pct, 15.0)
            again = SettingsManager(Path(tmp))
            self.assertEqual(again.settings.trading.bet_percent, 2.0)
            self.assertEqual(again.settings.trading.daily_loss_pct, 15.0)

    def test_session_lock_settings_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SettingsManager(Path(tmp))
            manager.update_trading_settings(session_lock_usd=10, session_trail_pct=40)
            self.assertEqual(manager.settings.trading.session_lock_usd, 10.0)
            self.assertEqual(manager.settings.trading.session_trail_pct, 40.0)
            again = SettingsManager(Path(tmp))
            self.assertEqual(again.settings.trading.session_lock_usd, 10.0)
            self.assertEqual(again.settings.trading.session_trail_pct, 40.0)

    def test_journal_stats_count_real_only(self):
        from src.trade_journal import summarize_trades
        rows = [
            {"live": False, "result": "WIN", "pnl": 3.0},
            {"live": True, "result": "LOSS", "pnl": -1.5},
            {"live": True, "result": "WIN", "pnl": 1.4},
        ]
        all_rows = summarize_trades(rows)
        real = summarize_trades(rows, live=True)
        self.assertEqual(all_rows["trades"], 3)
        self.assertAlmostEqual(all_rows["pnl"], 2.9, places=2)
        self.assertEqual(real["trades"], 2)
        self.assertEqual(real["wins"], 1)
        self.assertEqual(real["losses"], 1)
        self.assertAlmostEqual(real["pnl"], -0.1, places=2)


if __name__ == "__main__":
    unittest.main()
