import unittest
from unittest.mock import AsyncMock, patch

from src.user_settings import BinanceConnector, BinanceCredentials, pick_live_wallet
from src.wallet_prediction import DEFAULT_PREDICTION_WALLET
from src.web_server import ClientSession

USER_WALLET = "0x5FB045Ed0C5e906Ab4D60817bf022650f9749a0A"


class LiveWalletTests(unittest.TestCase):
    def test_prefers_my_wallet(self):
        name, amount = pick_live_wallet({
            "Spot": 101.23,
            "Funding": 12.5,
            "Wallet CeDefi": 0.91,
            "My Wallet": 10.025,
        })
        self.assertEqual(name, "My Wallet")
        self.assertEqual(amount, 10.025)

    def test_ignores_cex_dump(self):
        name, amount = pick_live_wallet({"Spot": 1.0, "Funding": 20.0, "Wallet CeDefi": 0.91})
        self.assertEqual(name, "My Wallet")
        self.assertEqual(amount, 0.0)

    def test_ignores_spot(self):
        name, amount = pick_live_wallet({"Spot": 3.25})
        self.assertEqual(name, "My Wallet")
        self.assertEqual(amount, 0.0)

    def test_empty_is_my_wallet_zero(self):
        name, amount = pick_live_wallet({})
        self.assertEqual(name, "My Wallet")
        self.assertEqual(amount, 0.0)

    def test_real_stats_use_live_balance(self):
        session = ClientSession(
            session_id="test",
            simulation=False,
            live_balance=10.025,
            live_wallet="My Wallet",
            live_wallet_address=USER_WALLET,
            live_network="BNB Smart Chain",
        )
        payload = session.stats_payload()
        self.assertTrue(payload["live"])
        self.assertFalse(payload["simulation"])
        self.assertEqual(payload["capital"], 10.025)
        self.assertEqual(payload["wallet"], "My Wallet")
        self.assertEqual(payload["wallet_address"], USER_WALLET)
        self.assertEqual(payload["network"], "BNB Smart Chain")
        self.assertEqual(payload["pnl"], 0.0)

    def test_sim_stats_keep_virtual_capital(self):
        session = ClientSession(session_id="test", simulation=True, initial_capital=100.0, cumulative_pnl=12.5)
        payload = session.stats_payload()
        self.assertFalse(payload["live"])
        self.assertTrue(payload["simulation"])
        self.assertEqual(payload["capital"], 112.5)


class FetchLiveBalancesTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_only_pinned_my_wallet(self):
        connector = BinanceConnector(BinanceCredentials(
            api_key="k",
            api_secret="s",
            is_testnet=False,
            prediction_wallet=USER_WALLET,
        ))

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.preferred_address = kwargs.get("preferred_address") or args[2] if len(args) > 2 else ""

            async def fetch_prediction_wallet(self):
                return {
                    "wallet_id": "w1",
                    "wallet_address": USER_WALLET,
                    "order_address": USER_WALLET,
                    "usdt": 10.025,
                    "label": "My Wallet",
                    "network": "BNB Smart Chain",
                    "can_trade": True,
                    "error": "",
                    "my_wallet_address": USER_WALLET,
                    "my_wallet_usdt": 10.025,
                }

        with patch("src.wallet_prediction.WalletPredictionClient", FakeClient):
            result = await connector.fetch_live_balances()

        self.assertTrue(result["success"])
        self.assertEqual(result["display_wallet"], "My Wallet")
        self.assertEqual(result["display_balance"], 10.025)
        self.assertEqual(result["wallet_address"], USER_WALLET)
        self.assertEqual(DEFAULT_PREDICTION_WALLET, USER_WALLET)
        self.assertNotIn("Spot", result["wallets"])
        self.assertNotIn("Funding", result["wallets"])
        self.assertEqual(result["wallets"], {"My Wallet": 10.025})
        self.assertTrue(result["can_trade"])

    async def test_unlisted_address_still_shows_my_wallet_usdt(self):
        listed = "0xf7d411111111111111111111111111111111bb3c"
        connector = BinanceConnector(BinanceCredentials(
            api_key="k",
            api_secret="s",
            is_testnet=False,
            prediction_wallet=USER_WALLET,
        ))

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def fetch_prediction_wallet(self):
                return {
                    "wallet_id": "pred",
                    "wallet_address": listed,
                    "order_address": listed,
                    "usdt": 0.91,
                    "label": "Prediction Account",
                    "network": "BNB Smart Chain",
                    "can_trade": True,
                    "error": "",
                    "my_wallet_address": USER_WALLET,
                    "my_wallet_usdt": 13.45,
                }

        with patch("src.wallet_prediction.WalletPredictionClient", FakeClient):
            result = await connector.fetch_live_balances()

        self.assertTrue(result["success"])
        self.assertEqual(result["display_wallet"], "Prediction Account")
        self.assertEqual(result["display_balance"], 0.91)
        self.assertEqual(result["wallet_address"], listed)
        self.assertNotEqual(result["wallet_address"], USER_WALLET)
        self.assertEqual(result["error"], "")
        self.assertTrue(result["can_trade"])
        self.assertEqual(result["my_wallet_usdt"], 13.45)
        self.assertEqual(result["wallets"]["Prediction Account"], 0.91)
        self.assertEqual(result["wallets"]["My Wallet"], 13.45)

    async def test_signed_cex_endpoints_are_not_called(self):
        connector = BinanceConnector(BinanceCredentials(api_key="k", api_secret="s", is_testnet=False))
        signed = AsyncMock(return_value=(200, {"balances": [{"asset": "USDT", "free": "101.23"}]}))

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def fetch_prediction_wallet(self):
                return {
                    "wallet_id": "w1",
                    "wallet_address": USER_WALLET,
                    "order_address": USER_WALLET,
                    "usdt": 10.025,
                    "label": "My Wallet",
                    "can_trade": True,
                    "error": "",
                    "my_wallet_address": USER_WALLET,
                    "my_wallet_usdt": 10.025,
                }

        with patch.object(connector, "_signed_request", signed), \
             patch("src.wallet_prediction.WalletPredictionClient", FakeClient):
            result = await connector.fetch_live_balances()

        signed.assert_not_called()
        self.assertEqual(result["display_balance"], 10.025)
        self.assertEqual(result["wallet_address"], USER_WALLET)


if __name__ == "__main__":
    unittest.main()
