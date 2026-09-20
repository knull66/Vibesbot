import unittest
from unittest.mock import AsyncMock, patch

from src.user_settings import BinanceConnector, BinanceCredentials, pick_live_wallet
from src.web_server import ClientSession


class LiveWalletTests(unittest.TestCase):
    def test_prefers_prediction(self):
        name, amount = pick_live_wallet({"Spot": 0.0, "Funding": 12.5, "Prediction": 55.91})
        self.assertEqual(name, "Prediction")
        self.assertEqual(amount, 55.91)

    def test_falls_back_to_funding(self):
        name, amount = pick_live_wallet({"Spot": 1.0, "Funding": 20.0})
        self.assertEqual(name, "Funding")
        self.assertEqual(amount, 20.0)

    def test_falls_back_to_spot(self):
        name, amount = pick_live_wallet({"Spot": 3.25})
        self.assertEqual(name, "Spot")
        self.assertEqual(amount, 3.25)

    def test_empty_is_spot_zero(self):
        name, amount = pick_live_wallet({})
        self.assertEqual(name, "Spot")
        self.assertEqual(amount, 0.0)

    def test_event_contract_name(self):
        name, amount = pick_live_wallet({"Spot": 0.0, "Event Contracts": 55.91})
        self.assertEqual(name, "Event Contracts")
        self.assertEqual(amount, 55.91)

    def test_real_stats_use_live_balance(self):
        session = ClientSession(session_id="test", simulation=False, live_balance=55.91, live_wallet="Prediction")
        payload = session.stats_payload()
        self.assertTrue(payload["live"])
        self.assertFalse(payload["simulation"])
        self.assertEqual(payload["capital"], 55.91)
        self.assertEqual(payload["wallet"], "Prediction")
        self.assertEqual(payload["pnl"], 0.0)

    def test_sim_stats_keep_virtual_capital(self):
        session = ClientSession(session_id="test", simulation=True, initial_capital=100.0, cumulative_pnl=12.5)
        payload = session.stats_payload()
        self.assertFalse(payload["live"])
        self.assertTrue(payload["simulation"])
        self.assertEqual(payload["capital"], 112.5)


class FetchLiveBalancesTests(unittest.IsolatedAsyncioTestCase):
    async def test_merges_spot_funding_and_prefers_prediction(self):
        connector = BinanceConnector(BinanceCredentials(api_key="k", api_secret="s", is_testnet=False))

        async def fake_request(method, path, extra=None):
            if path == "/api/v3/account":
                return 200, {"balances": [{"asset": "USDT", "free": "0", "locked": "0"}]}
            if path == "/sapi/v1/asset/wallet/balance":
                return 200, [
                    {"walletName": "Spot", "balance": "0"},
                    {"walletName": "Funding", "balance": "12.5"},
                    {"walletName": "Prediction", "balance": "55.91"},
                ]
            if path == "/sapi/v1/asset/get-funding-asset":
                return 200, [{"asset": "USDT", "free": "12.5", "locked": "0"}]
            return 404, {"msg": "missing"}

        with patch.object(connector, "_signed_request", new=AsyncMock(side_effect=fake_request)):
            result = await connector.fetch_live_balances()

        self.assertTrue(result["success"])
        self.assertEqual(result["display_wallet"], "Prediction")
        self.assertEqual(result["display_balance"], 55.91)
        self.assertEqual(result["wallets"]["Funding"], 12.5)


if __name__ == "__main__":
    unittest.main()
