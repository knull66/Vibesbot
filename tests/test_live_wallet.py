import unittest
from unittest.mock import AsyncMock, patch

from src.user_settings import BinanceConnector, BinanceCredentials, pick_live_wallet
from src.web_server import ClientSession


class LiveWalletTests(unittest.TestCase):
    def test_prefers_prediction_bsc(self):
        name, amount = pick_live_wallet({
            "Spot": 101.23,
            "Funding": 12.5,
            "Wallet CeDefi": 0.91,
            "0x1744…a0A": 10.025,
        })
        self.assertEqual(name, "0x1744…a0A")
        self.assertEqual(amount, 10.025)

    def test_ignores_cex_dump(self):
        name, amount = pick_live_wallet({"Spot": 1.0, "Funding": 20.0, "Wallet CeDefi": 0.91})
        self.assertEqual(name, "Prediction BSC")
        self.assertEqual(amount, 0.0)

    def test_ignores_spot(self):
        name, amount = pick_live_wallet({"Spot": 3.25})
        self.assertEqual(name, "Prediction BSC")
        self.assertEqual(amount, 0.0)

    def test_empty_is_prediction_bsc_zero(self):
        name, amount = pick_live_wallet({})
        self.assertEqual(name, "Prediction BSC")
        self.assertEqual(amount, 0.0)

    def test_real_stats_use_live_balance(self):
        session = ClientSession(
            session_id="test",
            simulation=False,
            live_balance=10.025,
            live_wallet="0x1744…a0A",
            live_wallet_address="0x17449a0A0000000000000000000000000000a0A1",
            live_network="BNB Smart Chain",
        )
        payload = session.stats_payload()
        self.assertTrue(payload["live"])
        self.assertFalse(payload["simulation"])
        self.assertEqual(payload["capital"], 10.025)
        self.assertEqual(payload["wallet"], "0x1744…a0A")
        self.assertEqual(payload["wallet_address"], "0x17449a0A0000000000000000000000000000a0A1")
        self.assertEqual(payload["network"], "BNB Smart Chain")
        self.assertEqual(payload["pnl"], 0.0)

    def test_sim_stats_keep_virtual_capital(self):
        session = ClientSession(session_id="test", simulation=True, initial_capital=100.0, cumulative_pnl=12.5)
        payload = session.stats_payload()
        self.assertFalse(payload["live"])
        self.assertTrue(payload["simulation"])
        self.assertEqual(payload["capital"], 112.5)


class FetchLiveBalancesTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_only_prediction_bsc(self):
        connector = BinanceConnector(BinanceCredentials(api_key="k", api_secret="s", is_testnet=False))

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def fetch_prediction_wallet(self):
                return {
                    "wallet_id": "w1",
                    "wallet_address": "0x17449a0A0000000000000000000000000000a0A1",
                    "usdt": 10.025,
                    "label": "0x1744…a0A1",
                    "network": "BNB Smart Chain",
                    "error": "",
                }

        with patch("src.wallet_prediction.WalletPredictionClient", FakeClient):
            result = await connector.fetch_live_balances()

        self.assertTrue(result["success"])
        self.assertEqual(result["display_wallet"], "0x1744…a0A1")
        self.assertEqual(result["display_balance"], 10.025)
        self.assertEqual(result["wallet_address"], "0x17449a0A0000000000000000000000000000a0A1")
        self.assertEqual(result["network"], "BNB Smart Chain")
        self.assertNotIn("Spot", result["wallets"])
        self.assertNotIn("Funding", result["wallets"])
        self.assertNotIn("Wallet CeDefi", result["wallets"])
        self.assertEqual(result["wallets"], {"0x1744…a0A1": 10.025})

    async def test_signed_cex_endpoints_are_not_called(self):
        connector = BinanceConnector(BinanceCredentials(api_key="k", api_secret="s", is_testnet=False))
        signed = AsyncMock(return_value=(200, {"balances": [{"asset": "USDT", "free": "101.23"}]}))

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def fetch_prediction_wallet(self):
                return {
                    "wallet_id": "w1",
                    "wallet_address": "0x17449a0A0000000000000000000000000000a0A1",
                    "usdt": 10.025,
                    "label": "0x1744…a0A1",
                    "error": "",
                }

        with patch.object(connector, "_signed_request", signed), \
             patch("src.wallet_prediction.WalletPredictionClient", FakeClient):
            result = await connector.fetch_live_balances()

        signed.assert_not_called()
        self.assertEqual(result["display_balance"], 10.025)


if __name__ == "__main__":
    unittest.main()
