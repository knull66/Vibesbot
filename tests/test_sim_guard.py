import tempfile
import unittest
from pathlib import Path

from src.trade_journal import append_trade, clear_trades, read_trades, summarize_trades
from src.wallet_prediction import market_book


class JournalResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "trade_journal.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _row(self, live, result="WIN", pnl=1.5):
        return append_trade({
            "live": live,
            "result": result,
            "pnl": pnl,
            "direction": "UP",
        }, path=self.path)

    def test_clear_real_keeps_sim(self):
        self._row(True, "LOSS", -1.5)
        self._row(False, "WIN", 2.0)
        removed = clear_trades(live=True, path=self.path)
        self.assertEqual(removed, 1)
        rows = read_trades(0, self.path)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["live"])
        real = summarize_trades(rows, live=True)
        sim = summarize_trades(rows, live=False)
        self.assertEqual(real["trades"], 0)
        self.assertEqual(sim["trades"], 1)
        self.assertAlmostEqual(sim["pnl"], 2.0)

    def test_clear_sim_keeps_real(self):
        self._row(True, "WIN", 3.0)
        self._row(False, "LOSS", -1.0)
        clear_trades(live=False, path=self.path)
        real = summarize_trades(read_trades(0, self.path), live=True)
        self.assertEqual(real["trades"], 1)
        self.assertAlmostEqual(real["pnl"], 3.0)


class PriceToBeatSourceTests(unittest.TestCase):
    def test_market_book_lock_is_wallet_not_spot(self):
        book = market_book({
            "title": "BTC Up or Down 5m",
            "startPrice": "84111.25",
            "currentPrice": "84200.00",
        })
        self.assertAlmostEqual(book["price_to_beat"], 84111.25)
        self.assertEqual(book["price_to_beat_source"], "wallet")
        self.assertAlmostEqual(book["live_price"], 84200.00)

    def test_no_lock_means_empty_not_live_tick(self):
        book = market_book({"currentPrice": "84200.00", "oraclePrice": "84200.00"})
        self.assertEqual(book["price_to_beat"], 0)
        self.assertEqual(book["price_to_beat_source"], "")


class SimStartPayloadTests(unittest.TestCase):
    def test_start_sends_simulation_flag(self):
        js = Path(__file__).resolve().parents[1].joinpath("web/static/app.js").read_text()
        self.assertIn("action: 'start', simulation: !!this.isSimulation", js)
        self.assertIn("SIM blocked a live order", Path(__file__).resolve().parents[1].joinpath("src/web_server.py").read_text())
        self.assertIn("Reset REAL stats", Path(__file__).resolve().parents[1].joinpath("web/templates/index.html").read_text())


class PriceToBeatUiTests(unittest.TestCase):
    def test_js_keeps_last_lock_on_empty_tick(self):
        js = Path(__file__).resolve().parents[1].joinpath("web/static/app.js").read_text()
        self.assertIn("const topicChanged = topicId && this.priceToBeatTopic && topicId !== this.priceToBeatTopic", js)
        self.assertIn("if (this.priceToBeat)", js)
        self.assertIn("Keep Binance lock on screen", js)
        self.assertNotIn("Clear price to beat after trade closes", js)
        server = Path(__file__).resolve().parents[1].joinpath("src/web_server.py").read_text()
        self.assertIn("resolve_cached_lock", server)
        self.assertIn("new_window = remaining >= 297 or remaining <= 3", server)


if __name__ == "__main__":
    unittest.main()
