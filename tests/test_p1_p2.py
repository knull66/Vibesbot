import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.companion import dashboard_bind_host
from src.config import RiskConfig
from src.risk_manager import RiskManager
from src.round_signal import combine_indicator_votes, crowd_agrees
from src.trade_journal import append_trade, read_trades
from src.wallet_prediction import WalletPredictionClient, same_address


USER_WALLET = "0xaaaabbbbccccddddeeeeffff0000111122223333"


class CircuitBreakerTests(unittest.TestCase):
    def test_trips_after_consecutive_losses(self):
        risk = RiskManager(RiskConfig(circuit_breaker_consecutive_losses=3, circuit_breaker_cooldown_minutes=30))
        ok, _ = risk.circuit_status()
        self.assertTrue(ok)
        for _ in range(3):
            risk.record_settled("LOSS", -1.5)
        ok, reason = risk.circuit_status()
        self.assertFalse(ok)
        self.assertIn("circuit breaker", reason.lower())

    def test_push_does_not_count(self):
        risk = RiskManager(RiskConfig(circuit_breaker_consecutive_losses=2))
        risk.record_settled("PUSH", -0.02)
        risk.record_settled("PUSH", 0.0)
        ok, _ = risk.circuit_status()
        self.assertTrue(ok)


class JournalTests(unittest.TestCase):
    def test_append_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trade_journal.jsonl"
            append_trade({"direction": "UP", "result": "WIN", "pnl": 1.1, "live": True}, path)
            append_trade({"direction": "DOWN", "result": "LOSS", "pnl": -1.5, "live": False}, path)
            rows = read_trades(10, path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["direction"], "UP")
            self.assertEqual(rows[1]["result"], "LOSS")


class BindHostTests(unittest.TestCase):
    def test_explicit_and_env(self):
        self.assertEqual(dashboard_bind_host("10.0.0.5"), "10.0.0.5")
        with patch.dict("os.environ", {"VIBESBOT_HOST": "0.0.0.0"}):
            self.assertEqual(dashboard_bind_host(), "0.0.0.0")

    def test_loopback_unless_companion(self):
        with patch.dict("os.environ", {"VIBESBOT_HOST": ""}, clear=False):
            with patch("src.companion.get_companion") as mock:
                mock.return_value.enabled = False
                self.assertEqual(dashboard_bind_host(), "127.0.0.1")
                mock.return_value.enabled = True
                self.assertEqual(dashboard_bind_host(), "0.0.0.0")


class WeightedSignalTests(unittest.TestCase):
    def test_zero_weights_wait(self):
        signal, _, _ = combine_indicator_votes(1, 1, 1, 1, 0, {"rsi": 0, "macd": 0, "bollinger": 0, "momentum": 0})
        self.assertEqual(signal, "WAIT")

    def test_crowd_blocks_against_book(self):
        self.assertFalse(crowd_agrees("UP", {"up": 0.04, "down": 0.96}))


class WalletRetryAndRealPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_429_then_succeeds(self):
        client = WalletPredictionClient("k", "s")
        calls = {"n": 0}

        async def fake_once(method, path, extra=None):
            calls["n"] += 1
            if calls["n"] < 3:
                return 429, {"msg": "too many requests"}
            return 200, {"ok": True}

        with patch.object(client, "_request_once", fake_once), \
             patch("src.wallet_prediction.asyncio.sleep", AsyncMock()):
            status, payload = await client._request("GET", "wallet/list")
        self.assertEqual(status, 200)
        self.assertEqual(payload["ok"], True)
        self.assertEqual(calls["n"], 3)

    async def test_quote_buy_then_binance_settle(self):
        client = WalletPredictionClient("k", "s", preferred_address=USER_WALLET)
        listed = "0xbbbbccccddddeeeeffff00001111222233334444"
        captured = {}

        async def fake_request(method, path, extra=None):
            captured[path] = extra or {}
            if path == "trade/get-quote":
                return 200, {"quoteId": "q1", "averagePrice": 0.50, "amountOut": str(3 * 10**18)}
            if path == "trade/place-order-bundle":
                return 200, {"orderId": "ord-1"}
            return 404, {}

        async def fake_wallet(refresh=True):
            return {
                "walletId": "pred",
                "walletAddress": listed,
                "orderAddress": listed,
                "usdt": 10.0,
                "label": "Prediction Account",
                "can_trade": True,
            }

        topic = {
            "markets": [{"title": "UP", "outcomes": [{"name": "YES", "tokenId": "tok-up", "price": "0.50"}]}],
            "chainId": "56",
            "marketTopicId": "topic-1",
            "title": "BTC Price 5m Up or Down?",
        }

        with patch.object(client, "_request", fake_request), \
             patch.object(client, "ensure_wallet", fake_wallet), \
             patch("src.wallet_prediction.fetch_bsc_usdt", AsyncMock(return_value=10.0)):
            placed = await client.quote_and_buy(topic, "UP", 1.5, 0.5)

        self.assertTrue(placed["success"])
        self.assertEqual(placed["order_id"], "ord-1")
        self.assertTrue(same_address(placed["wallet_address"], listed))
        self.assertEqual(captured["trade/get-quote"]["side"], "BUY")

        from src.wallet_prediction import PendingWalletTrade
        pending = PendingWalletTrade(
            session_id="s", round_number=1, signal="UP", stake=1.5,
            open_price=86000, share_price=0.5, shares=3, fee=0.03, cost=1.53,
            live=True, order_id="ord-1", topic_id="topic-1", token_id="tok-up",
        )

        async def fake_settled(limit=20):
            return [{
                "tokenId": "tok-up",
                "isWinner": False,
                "realizedPnl": "-1.50",
                "positionStatus": "SETTLED",
            }]

        with patch.object(client, "settled_history", fake_settled), \
             patch.object(client, "list_positions", AsyncMock(return_value=[])), \
             patch.object(client, "position_by_token", AsyncMock(return_value={})):
            resolved = await client.resolve_live_result(pending)
        self.assertTrue(resolved["ready"])
        self.assertEqual(resolved["result"], "LOSS")


class DailyUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_auto_update_off(self):
        from src.updater import maybe_daily_update

        class Settings:
            auto_update = False
            last_update_check = None

        class Manager:
            settings = Settings()

        with patch("src.user_settings.get_settings_manager", return_value=Manager()):
            result = await maybe_daily_update(apply=False)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "auto_update off")


if __name__ == "__main__":
    unittest.main()
