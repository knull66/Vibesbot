import unittest
from unittest.mock import patch

from src.wallet_prediction import (
    DEFAULT_PREDICTION_WALLET,
    WalletPredictionClient,
    as_probability,
    clamp_bet_amount,
    decode_wei_to_usdt,
    encode_balance_of,
    fill_from_quote,
    is_btc_short_window,
    looks_like_btc_price,
    market_book,
    match_wallet_row,
    normalize_evm_address,
    normalize_share_price,
    outcome_token,
    paper_fill,
    pick_active_btc_window,
    pick_tradable_wallet_row,
    resolve_preferred_address,
    same_address,
    settle_direction,
    settle_payout,
    short_wallet_label,
    spend_wallet_label,
    taker_fee,
    topic_start_price,
    tradable_edge,
    unwrap_prediction_payload,
    wallets_from_payload,
    api_error_text,
    mismatch_wallet_error,
)

USER_WALLET = "0x5FB045Ed0C5e906Ab4D60817bf022650f9749a0A"


class WalletMathTests(unittest.TestCase):
    def test_taker_fee_at_half(self):
        fee = taker_fee(1.0, 0.50, 200)
        self.assertAlmostEqual(fee, 0.02, places=4)

    def test_paper_fill_needs_edge(self):
        fill = paper_fill(1.0, 0.50, 200)
        self.assertAlmostEqual(fill["cost"], 1.02, places=4)
        self.assertGreater(fill["win_pnl"], 0.9)
        self.assertLess(fill["lose_pnl"], -1.0)

    def test_settings_stake_floor_is_wallet_min(self):
        self.assertEqual(clamp_bet_amount(1.0), 1.5)
        self.assertEqual(clamp_bet_amount(2.0), 2.0)
        self.assertEqual(clamp_bet_amount("nope"), 1.5)

    def test_skips_favorite_that_pays_pennies(self):
        skip = tradable_edge(0.92, 1.5)
        take = tradable_edge(0.50, 1.5)
        longshot = tradable_edge(0.03, 1.5)
        self.assertFalse(skip["ok"])
        self.assertLess(skip["win_pnl"], 0.20)
        self.assertTrue(take["ok"])
        self.assertGreater(take["win_pnl"], 1.0)
        self.assertFalse(longshot["ok"])

    def test_normalize_share_price_from_percent_or_wei(self):
        self.assertAlmostEqual(normalize_share_price(0.49), 0.49)
        self.assertAlmostEqual(normalize_share_price(49), 0.49)
        self.assertTrue(looks_like_btc_price(86047.04))
        self.assertFalse(looks_like_btc_price(0.92))

    def test_quote_fill_uses_amount_out(self):
        fill = fill_from_quote({"averagePrice": 0.50, "amountOut": str(3 * 10**18)}, 1.5, 0.9)
        self.assertAlmostEqual(fill["share_price"], 0.50, places=4)

    def test_settle_up_down_flat(self):
        self.assertEqual(settle_direction(100.0, 100.2), "UP")
        self.assertEqual(settle_direction(100.0, 99.8), "DOWN")
        self.assertEqual(settle_direction(100.0, 100.0), "FLAT")

    def test_tie_pays_half(self):
        fill = paper_fill(1.0, 0.50, 200)
        actual, result, pnl = settle_payout("UP", 100.0, 100.0, fill["shares"], fill["cost"])
        self.assertEqual(actual, "FLAT")
        self.assertEqual(result, "PUSH")
        self.assertAlmostEqual(pnl, -fill["fee"], places=4)

    def test_pins_user_binance_wallet(self):
        self.assertEqual(DEFAULT_PREDICTION_WALLET, USER_WALLET)
        self.assertEqual(resolve_preferred_address(""), USER_WALLET)
        self.assertTrue(same_address(USER_WALLET.lower(), USER_WALLET))
        self.assertEqual(short_wallet_label(USER_WALLET), "0x5FB0…9a0A")
        self.assertEqual(short_wallet_label(""), "My Wallet")

    def test_decode_bsc_usdt_wei(self):
        self.assertAlmostEqual(decode_wei_to_usdt(hex(10_025_000_000_000_000_000)), 10.025)
        self.assertEqual(decode_wei_to_usdt("0x0"), 0.0)
        data = encode_balance_of(USER_WALLET)
        self.assertTrue(data.startswith("0x70a08231"))
        self.assertEqual(len(data), 74)

    def test_normalize_evm_address(self):
        self.assertEqual(normalize_evm_address(USER_WALLET[2:]), USER_WALLET)
        self.assertEqual(normalize_evm_address("not-an-address"), "")

    def test_match_ignores_other_wallets(self):
        row = match_wallet_row([
            {"walletId": "other", "walletAddress": "0x1111111111111111111111111111111111111111"},
            {"walletId": "mine", "walletAddress": USER_WALLET.lower()},
        ], USER_WALLET)
        self.assertEqual(row["walletId"], "mine")

    def test_pick_listed_prediction_account_when_my_wallet_absent(self):
        listed = "0xf7d411111111111111111111111111111111bb3c"
        row = pick_tradable_wallet_row([
            {"walletId": "pred", "walletAddress": listed},
        ], USER_WALLET)
        self.assertEqual(row["walletId"], "pred")
        self.assertEqual(spend_wallet_label(listed, USER_WALLET), "Prediction Account")
        self.assertEqual(spend_wallet_label(USER_WALLET, USER_WALLET), "My Wallet")


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

    def test_market_book_matches_binance_odds(self):
        self.assertAlmostEqual(as_probability(49), 0.49)
        topic = {
            "title": "BTC Up or Down 5m",
            "startPrice": "81613.68",
            "markets": [{
                "title": "UP",
                "outcomes": [{"name": "YES", "tokenId": "tok-up", "price": "0.49"}],
            }, {
                "title": "DOWN",
                "outcomes": [{"name": "YES", "tokenId": "tok-down", "price": "0.50"}],
            }],
        }
        book = market_book(topic)
        self.assertAlmostEqual(book["up"], 0.49)
        self.assertAlmostEqual(book["down"], 0.50)
        self.assertAlmostEqual(book["up_odds"], 1 / 0.49, places=2)
        self.assertAlmostEqual(book["down_odds"], 2.0)
        self.assertAlmostEqual(book["price_to_beat"], 81613.68)

    def test_price_to_beat_ignores_live_tick_and_odds(self):
        self.assertEqual(topic_start_price({"startPrice": "0.92"}), 0.0)
        self.assertAlmostEqual(topic_start_price({
            "oracle": {"lockPrice": "86,047.04"},
        }), 86047.04)

    def test_wallets_from_wrapped_payload(self):
        rows = wallets_from_payload({
            "code": "000000",
            "data": {"wallets": [{
                "walletId": "mine",
                "walletAddress": USER_WALLET.lower(),
            }]},
        })
        self.assertEqual(rows[0]["walletId"], "mine")
        inner = unwrap_prediction_payload({"code": 0, "data": {"quoteId": "q1"}})
        self.assertEqual(inner["quoteId"], "q1")


class WalletBscPickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_pins_preferred_wallet_not_richest(self):
        client = WalletPredictionClient("k", "s", preferred_address=USER_WALLET)

        async def fake_list():
            return [
                {"walletId": "rich", "walletAddress": "0x1111111111111111111111111111111111111111"},
                {"walletId": "mine", "walletAddress": USER_WALLET.lower()},
            ]

        async def fake_usdt(address):
            if same_address(address, USER_WALLET):
                return 10.025
            return 99.0

        with patch.object(client, "list_wallets", fake_list), \
             patch("src.wallet_prediction.fetch_bsc_usdt", fake_usdt):
            picked = await client.fetch_prediction_wallet()

        self.assertAlmostEqual(picked["usdt"], 10.025)
        self.assertEqual(picked["wallet_id"], "mine")
        self.assertTrue(same_address(picked["wallet_address"], USER_WALLET))
        self.assertEqual(picked["label"], "My Wallet")
        self.assertTrue(picked["can_trade"])

    async def test_spends_listed_prediction_account_when_my_wallet_absent(self):
        listed = "0xf7d411111111111111111111111111111111bb3c"
        client = WalletPredictionClient("k", "s", preferred_address=USER_WALLET)

        async def fake_list():
            return [{"walletId": "pred", "walletAddress": listed}]

        async def fake_usdt(address):
            if same_address(address, listed):
                return 0.91
            if same_address(address, USER_WALLET):
                return 13.45
            return 0.0

        with patch.object(client, "list_wallets", fake_list), \
             patch("src.wallet_prediction.fetch_bsc_usdt", fake_usdt):
            picked = await client.fetch_prediction_wallet()

        self.assertEqual(picked["wallet_id"], "pred")
        self.assertTrue(same_address(picked["wallet_address"], listed))
        self.assertTrue(same_address(picked["order_address"], listed))
        self.assertAlmostEqual(picked["usdt"], 0.91)
        self.assertAlmostEqual(picked["my_wallet_usdt"], 13.45)
        self.assertTrue(same_address(picked["my_wallet_address"], USER_WALLET))
        self.assertEqual(picked["label"], "Prediction Account")
        self.assertTrue(picked["can_trade"])
        self.assertEqual(picked["error"], "")

    async def test_quote_spends_listed_prediction_account(self):
        listed = "0xf7d411111111111111111111111111111111bb3c"
        client = WalletPredictionClient("k", "s", preferred_address=USER_WALLET)
        captured = {}

        async def fake_request(method, path, extra=None):
            captured[path] = extra or {}
            if path == "trade/get-quote":
                return 200, {"quoteId": "q1", "averagePrice": 0.5}
            if path == "trade/place-order-bundle":
                return 200, {"orderId": "o1"}
            return 404, {}

        async def fake_wallet(refresh=True):
            return {
                "walletId": "pred",
                "walletAddress": listed,
                "orderAddress": listed,
                "usdt": 5.0,
                "label": "Prediction Account",
                "can_trade": True,
            }

        async def fake_usdt(address):
            return 5.0 if same_address(address, listed) else 13.45

        topic = {
            "markets": [{
                "title": "UP",
                "outcomes": [{"name": "YES", "tokenId": "tok-up", "price": "0.52"}],
            }],
            "chainId": "56",
            "title": "BTC Price 5m Up or Down?",
        }

        with patch.object(client, "_request", fake_request), \
             patch.object(client, "ensure_wallet", fake_wallet), \
             patch("src.wallet_prediction.fetch_bsc_usdt", fake_usdt):
            result = await client.quote_and_buy(topic, "UP", 1.5, 0.5)

        self.assertTrue(result["success"])
        self.assertEqual(captured["trade/get-quote"]["walletAddress"], listed)
        self.assertEqual(captured["trade/place-order-bundle"]["walletAddress"], listed)
        self.assertEqual(captured["trade/place-order-bundle"]["walletId"], "pred")
        self.assertEqual(captured["trade/place-order-bundle"]["accountType"], "SPOT")
        self.assertEqual(captured["trade/place-order-bundle"]["fundingSource"], "MPC")
        self.assertNotEqual(captured["trade/get-quote"]["walletAddress"], USER_WALLET)
        self.assertEqual(result["wallet_address"], listed)

    async def test_quote_uses_mpc_wallet_without_cex_account(self):
        client = WalletPredictionClient("k", "s", preferred_address=USER_WALLET)
        captured = {}

        async def fake_request(method, path, extra=None):
            captured[path] = extra or {}
            if path == "trade/get-quote":
                return 200, {"quoteId": "q1", "averagePrice": 0.5}
            if path == "trade/place-order-bundle":
                return 200, {"orderId": "o1"}
            return 404, {}

        async def fake_wallet(refresh=True):
            return {
                "walletId": "w",
                "walletAddress": USER_WALLET,
                "orderAddress": USER_WALLET,
                "usdt": 10.0,
                "label": "My Wallet",
                "can_trade": True,
            }

        topic = {
            "markets": [{
                "title": "UP",
                "outcomes": [{"name": "YES", "tokenId": "tok-up", "price": "0.52"}],
            }],
            "chainId": "56",
            "title": "BTC Price 5m Up or Down?",
        }

        async def fake_usdt(address):
            return 10.0

        with patch.object(client, "_request", fake_request), \
             patch.object(client, "ensure_wallet", fake_wallet), \
             patch("src.wallet_prediction.fetch_bsc_usdt", fake_usdt):
            result = await client.quote_and_buy(topic, "UP", 1.0, 0.5)

        self.assertTrue(result["success"])
        self.assertEqual(captured["trade/place-order-bundle"]["accountType"], "SPOT")
        self.assertEqual(captured["trade/place-order-bundle"]["fundingSource"], "MPC")
        self.assertNotIn("fundTransferAmount", captured["trade/place-order-bundle"])
        self.assertEqual(captured["trade/get-quote"]["walletAddress"], USER_WALLET)
        self.assertEqual(result["wallet_address"], USER_WALLET)
        self.assertNotIn("accountType", captured["trade/get-quote"])

    async def test_quote_rejects_lopsided_favorite(self):
        client = WalletPredictionClient("k", "s", preferred_address=USER_WALLET)
        captured = {}

        async def fake_request(method, path, extra=None):
            captured[path] = extra or {}
            if path == "trade/get-quote":
                return 200, {"quoteId": "q1", "averagePrice": 0.92}
            if path == "trade/place-order-bundle":
                return 200, {"orderId": "should-not-place"}
            return 404, {}

        async def fake_wallet(refresh=True):
            return {
                "walletId": "pred",
                "walletAddress": USER_WALLET,
                "orderAddress": USER_WALLET,
                "usdt": 9.0,
                "label": "Prediction Account",
                "can_trade": True,
            }

        topic = {
            "markets": [{
                "title": "UP",
                "outcomes": [{"name": "YES", "tokenId": "tok-up", "price": "0.92"}],
            }],
            "chainId": "56",
            "title": "BTC Price 5m Up or Down?",
        }

        async def fake_usdt(address):
            return 9.0

        with patch.object(client, "_request", fake_request), \
             patch.object(client, "ensure_wallet", fake_wallet), \
             patch("src.wallet_prediction.fetch_bsc_usdt", fake_usdt):
            result = await client.quote_and_buy(topic, "UP", 1.5, 0.92)

        self.assertFalse(result["success"])
        self.assertIn("92%", result["error"])
        self.assertNotIn("trade/place-order-bundle", captured)


class WalletErrorTextTests(unittest.TestCase):
    def test_api_error_text(self):
        self.assertIn("IP", api_error_text(400, {"code": -2015, "msg": "IP restriction"}))

    def test_mismatch_names_listed_account(self):
        text = mismatch_wallet_error(
            USER_WALLET,
            ["0x1111111111111111111111111111111111111111"],
        )
        self.assertIn(USER_WALLET, text)
        self.assertIn("Prediction Account", text)


if __name__ == "__main__":
    unittest.main()
