import unittest

from src.user_settings import binance_testnet_from_payload, describe_binance_error


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


if __name__ == "__main__":
    unittest.main()
