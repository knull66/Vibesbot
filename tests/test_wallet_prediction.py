import unittest
from unittest.mock import patch

from src.wallet_prediction import (
    PendingWalletTrade,
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
    pick_matching_position,
    pick_tradable_wallet_row,
    resolve_preferred_address,
    same_address,
    settle_direction,
    settle_payout,
    settlement_from_position,
    short_wallet_label,
    spend_wallet_label,
    taker_fee,
    topic_duration_minutes,
    topic_live_price,
    topic_start_price,
    cut_loss_ready,
    live_equity_baseline,
    take_profit_ready,
    tradable_edge,
    unwrap_prediction_payload,
    wallets_from_payload,
    api_error_text,
    mismatch_wallet_error,
    quote_id_of,
    sell_amount_candidates,
    shares_from_position_row,
)

USER_WALLET = "0xaaaabbbbccccddddeeeeffff0000111122223333"


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
        lean = tradable_edge(0.65, 1.5)
        crowded = tradable_edge(0.76, 1.5)
        longshot = tradable_edge(0.03, 1.5)
        self.assertFalse(skip["ok"])
        self.assertLess(skip["win_pnl"], 0.20)
        self.assertTrue(take["ok"])
        self.assertTrue(lean["ok"])
        self.assertTrue(crowded["ok"])
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

    def test_empty_preferred_does_not_pin_an_address(self):
        self.assertEqual(resolve_preferred_address(""), "")
        self.assertEqual(resolve_preferred_address(None), "")
        self.assertEqual(resolve_preferred_address(USER_WALLET), USER_WALLET)
        self.assertTrue(same_address(USER_WALLET.lower(), USER_WALLET))
        self.assertEqual(short_wallet_label(USER_WALLET), "0xaaaa…3333")
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
        self.assertIsNone(match_wallet_row([
            {"walletId": "mine", "walletAddress": USER_WALLET},
        ], ""))

    def test_pick_listed_prediction_account_when_my_wallet_absent(self):
        listed = "0xbbbbccccddddeeeeffff00001111222233334444"
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

    def test_rejects_two_hour_window_even_if_btc(self):
        now = 1_700_000_000_000
        self.assertFalse(is_btc_short_window({
            "slug": "bitcoin-up-or-down",
            "title": "Bitcoin Up or Down - September 21, 3PM-5:05PM ET",
            "symbol": "BTCUSDT",
            "startDate": now,
            "endDate": now + 125 * 60_000,
        }))
        self.assertAlmostEqual(topic_duration_minutes({
            "startDate": now,
            "endDate": now + 5 * 60_000,
        }), 5.0)

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
        mixed = {
            "oraclePrice": "99999.00",
            "currentPrice": "99999.00",
            "oracle": {"lockPrice": "86,047.04"},
        }
        self.assertAlmostEqual(topic_start_price(mixed), 86047.04)
        self.assertAlmostEqual(topic_live_price(mixed), 99999.00)
        self.assertEqual(topic_start_price({"oraclePrice": "86000.00"}), 0.0)

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

    def test_binance_loss_is_not_a_local_candle_win(self):
        row = {
            "tokenId": "tok-up",
            "marketTopicId": "4229500",
            "isWinner": False,
            "realizedPnl": "-1.50",
            "positionStatus": "SETTLED",
            "marketTopicTitle": "Bitcoin Up or Down - September 21, 3PM-3:05PM ET",
            "marketTitle": "UP",
            "finalOutcome": "NO",
        }
        parsed = settlement_from_position(row, "UP", shares=2.54, cost=1.52)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["ready"])
        self.assertEqual(parsed["result"], "LOSS")
        self.assertAlmostEqual(parsed["pnl"], -1.50, places=2)
        self.assertEqual(parsed["source"], "binance")
        local_win = settle_payout("UP", 86037.85, 86051.75, 2.54, 1.52)
        self.assertEqual(local_win[1], "WIN")
        match = pick_matching_position([row], topic_id="4229500", token_id="tok-up")
        self.assertEqual(match["tokenId"], "tok-up")

    def test_binance_win_uses_realized_pnl(self):
        parsed = settlement_from_position({
            "tokenId": "tok-up",
            "isWinner": True,
            "realizedPnl": "1.03",
            "positionStatus": "CLAIMED",
            "marketTitle": "UP",
        }, "UP", shares=2.54, cost=1.52)
        self.assertEqual(parsed["result"], "WIN")
        self.assertAlmostEqual(parsed["pnl"], 1.03, places=2)

    def test_ongoing_position_is_not_settled(self):
        self.assertIsNone(settlement_from_position({
            "tokenId": "tok-up",
            "positionStatus": "ONGOING",
            "isWinner": None,
        }, "UP", 2.54, 1.52))


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
        listed = "0xbbbbccccddddeeeeffff00001111222233334444"
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
        listed = "0xbbbbccccddddeeeeffff00001111222233334444"
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

    async def test_resolve_live_result_uses_binance_loss(self):
        client = WalletPredictionClient("k", "s")
        client._wallet = {
            "walletId": "pred",
            "walletAddress": USER_WALLET,
            "orderAddress": USER_WALLET,
        }
        pending = PendingWalletTrade(
            session_id="s1",
            round_number=1,
            signal="UP",
            stake=1.5,
            open_price=86037.85,
            share_price=0.59,
            shares=2.54,
            fee=0.021,
            cost=1.52,
            live=True,
            order_id="26092100001905644974",
            market_title="BTC 5m",
            topic_id="4229500",
            token_id="tok-up",
            end_date_ms=1,
        )

        async def fake_settled(limit=20):
            return [{
                "tokenId": "tok-up",
                "marketTopicId": "4229500",
                "isWinner": False,
                "realizedPnl": "-1.50",
                "positionStatus": "SETTLED",
                "marketTopicTitle": "Bitcoin Up or Down",
            }]

        async def fake_list(tab="ONGOING", limit=20):
            return []

        async def fake_token(token_id):
            return {}

        with patch.object(client, "settled_history", fake_settled), \
             patch.object(client, "list_positions", fake_list), \
             patch.object(client, "position_by_token", fake_token):
            resolved = await client.resolve_live_result(pending)

        self.assertTrue(resolved["ready"])
        self.assertEqual(resolved["result"], "LOSS")
        self.assertAlmostEqual(resolved["pnl"], -1.50, places=2)
        local = settle_payout("UP", 86037.85, 86051.75, 2.54, 1.52)
        self.assertEqual(local[1], "WIN")


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


class TakeProfitTests(unittest.TestCase):
    def test_same_mark_does_not_sell(self):
        ok, _, _ = take_profit_ready(0.50, 0.50, 3, 1.53, 90)
        self.assertFalse(ok)

    def test_sells_after_a_real_markup(self):
        ok, reason, pnl = take_profit_ready(0.50, 0.70, 3, 1.53, 90)
        self.assertTrue(ok)
        self.assertGreater(pnl, 0.20)
        self.assertIn("TAKE PROFIT", reason)

    def test_too_close_to_close(self):
        ok, _, _ = take_profit_ready(0.50, 0.80, 3, 1.53, 10)
        self.assertFalse(ok)

    def test_cuts_a_hard_fade(self):
        ok, reason, pnl = cut_loss_ready(0.60, 0.40, 2.5, 1.53, 90)
        self.assertTrue(ok)
        self.assertIn("CUT LOSS", reason)
        self.assertGreater(pnl, -1.53)

    def test_small_dip_is_not_a_cut(self):
        ok, _, _ = cut_loss_ready(0.60, 0.55, 2.5, 1.53, 90)
        self.assertFalse(ok)

    def test_paper_peak_is_not_a_92_percent_crash(self):
        healed = live_equity_baseline(7.92, -1.50, 100.0)
        self.assertIsNotNone(healed)
        peak, drawdown = healed
        self.assertAlmostEqual(peak, 9.42, places=2)
        self.assertLess(drawdown, 20)


class WalletSellPathTests(unittest.IsolatedAsyncioTestCase):
    def test_sell_amount_is_human_shares_first(self):
        amounts = sell_amount_candidates(3)
        self.assertEqual(amounts[0], "3")
        self.assertNotEqual(amounts[0], str(int(3 * 10**18)))
        self.assertIn(str(int(3 * 10**18)), amounts)

    def test_quote_id_nested(self):
        self.assertEqual(quote_id_of({"data": {"quoteId": "q-9"}}), "q-9")

    def test_shares_from_position_row(self):
        self.assertAlmostEqual(
            shares_from_position_row({"availableAmount": "2.54"}, 3),
            2.54,
        )
        self.assertAlmostEqual(shares_from_position_row({}, 3), 3)

    def test_wallet_query_keeps_address(self):
        client = WalletPredictionClient("k", "s")
        client._wallet = {"orderAddress": USER_WALLET, "walletId": "pred"}
        params = client._wallet_query({"tokenId": "tok-up"})
        self.assertEqual(params["walletAddress"], USER_WALLET)
        self.assertEqual(params["tokenId"], "tok-up")

    async def test_quote_and_sell(self):
        client = WalletPredictionClient("k", "s")
        captured = {}

        async def fake_request(method, path, extra=None):
            captured[path] = extra or {}
            if path == "trade/get-quote":
                return 200, {"quoteId": "qs", "averagePrice": 0.70, "amountOut": str(int(2.1 * 10**18))}
            if path == "trade/place-order-bundle":
                return 200, {"orderId": "sell-1"}
            return 404, {}

        async def fake_wallet(refresh=True):
            return {
                "walletId": "pred",
                "walletAddress": USER_WALLET,
                "orderAddress": USER_WALLET,
                "usdt": 10.0,
                "can_trade": True,
            }

        async def fake_held(token_id, fallback):
            return fallback

        with patch.object(client, "_request", fake_request), \
             patch.object(client, "ensure_wallet", fake_wallet), \
             patch.object(client, "_held_shares", fake_held):
            sold = await client.quote_and_sell({"marketTopicId": "t1", "chainId": "56"}, "tok-up", 3)

        self.assertTrue(sold["success"])
        self.assertEqual(sold["order_id"], "sell-1")
        self.assertEqual(captured["trade/get-quote"]["side"], "SELL")
        self.assertEqual(captured["trade/get-quote"]["amountIn"], "3")
        self.assertGreater(int(captured["trade/get-quote"]["slippageBps"]), 500)
        self.assertGreater(sold["proceeds"], 1.5)

    async def test_quote_and_sell_retries_human_after_wei_style_error(self):
        client = WalletPredictionClient("k", "s")
        attempts = []

        async def fake_request(method, path, extra=None):
            extra = extra or {}
            if path == "trade/get-quote":
                attempts.append(extra.get("amountIn"))
                if extra.get("amountIn") == "3":
                    return 200, {"code": -1, "msg": "SYSTEM_ERROR"}
                if extra.get("amountIn") == "2.985":
                    return 200, {"quoteId": "qs2", "averagePrice": 0.40, "amountOut": "1.1"}
                return 200, {"code": -1, "msg": "SYSTEM_ERROR"}
            if path == "trade/place-order-bundle":
                return 200, {"orderId": "sell-2"}
            return 404, {}

        async def fake_wallet(refresh=True):
            return {
                "walletId": "pred",
                "walletAddress": USER_WALLET,
                "orderAddress": USER_WALLET,
                "usdt": 10.0,
                "can_trade": True,
            }

        async def fake_held(token_id, fallback):
            return fallback

        with patch.object(client, "_request", fake_request), \
             patch.object(client, "ensure_wallet", fake_wallet), \
             patch.object(client, "_held_shares", fake_held):
            sold = await client.quote_and_sell({"marketTopicId": "t1"}, "tok-up", 3)

        self.assertTrue(sold["success"])
        self.assertEqual(attempts[0], "3")
        self.assertIn("2.985", attempts)
        self.assertEqual(sold["order_id"], "sell-2")


if __name__ == "__main__":
    unittest.main()
