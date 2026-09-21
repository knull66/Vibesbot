import tempfile
import unittest
from pathlib import Path

from src.user_settings import (
    SettingsManager,
    binance_testnet_from_payload,
    describe_binance_error,
    is_kept_secret,
)


class BinanceFlagTests(unittest.TestCase):
    def test_js_testnet_false(self):
        self.assertFalse(binance_testnet_from_payload({"testnet": False}))

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


if __name__ == "__main__":
    unittest.main()
