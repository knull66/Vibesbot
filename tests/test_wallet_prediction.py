import unittest

from src.wallet_prediction import (
    is_btc_short_window,
    outcome_token,
    paper_fill,
    pick_active_btc_window,
    settle_direction,
    taker_fee,
)


class WalletMathTests(unittest.TestCase):
    def test_taker_fee_at_half(self):
        fee = taker_fee(1.0, 0.50, 200)
        self.assertAlmostEqual(fee, 0.02, places=4)

    def test_paper_fill_needs_edge(self):
        fill = paper_fill(1.0, 0.50, 200)
        self.assertAlmostEqual(fill["cost"], 1.02, places=4)
        self.assertGreater(fill["win_pnl"], 0.9)
        self.assertLess(fill["lose_pnl"], -1.0)

    def test_settle_up_down_flat(self):
        self.assertEqual(settle_direction(100.0, 100.2), "UP")
        self.assertEqual(settle_direction(100.0, 99.8), "DOWN")
        self.assertEqual(settle_direction(100.0, 100.0), "FLAT")


class WalletMarketPickerTests(unittest.TestCase):
    def test_matches_btc_5m_slug(self):
        self.assertTrue(is_btc_short_window({
            "slug": "btc-price-5m-up-or-down",
            "title": "BTC Price 5m Up or Down?",
            "symbol": "BTCUSDT",
        }))
        self.assertFalse(is_btc_short_window({
            "slug": "btc-price-1h-up-or-down",
            "title": "BTC Price 1h Up or Down?",
            "symbol": "BTCUSDT",
        }))

    def test_picks_soonest_open_window(self):
        now = 1_700_000_000_000
        topics = [
            {"slug": "btc-price-5m-up-or-down", "status": "REGISTERED", "endDate": now + 600_000, "symbol": "BTCUSDT"},
            {"slug": "btc-price-5m-up-or-down", "status": "REGISTERED", "endDate": now + 180_000, "symbol": "BTCUSDT"},
            {"slug": "eth-price-5m-up-or-down", "status": "REGISTERED", "endDate": now + 60_000, "symbol": "ETHUSDT"},
        ]
        picked = pick_active_btc_window(topics, 5, now_ms=now)
        self.assertEqual(picked["endDate"], now + 180_000)

    def test_outcome_token_yes_on_up_market(self):
        topic = {
            "markets": [{
                "title": "UP",
                "outcomes": [{"name": "YES", "tokenId": "tok-up", "price": "0.52"}],
            }, {
                "title": "DOWN",
                "outcomes": [{"name": "YES", "tokenId": "tok-down", "price": "0.48"}],
            }],
        }
        up = outcome_token(topic, "UP")
        down = outcome_token(topic, "DOWN")
        self.assertEqual(up["token_id"], "tok-up")
        self.assertEqual(down["token_id"], "tok-down")


if __name__ == "__main__":
    unittest.main()
