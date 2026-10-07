import time
import unittest
from pathlib import Path

from src.web_server import ClientSession


ROOT = Path(__file__).resolve().parents[1]


class SessionClockTests(unittest.TestCase):
    def test_elapsed_ticks_only_while_running(self):
        session = ClientSession(session_id="clock")
        session.running = True
        session.paused = False
        session.session_elapsed = 10.0
        session.session_tick_at = time.time() - 5
        elapsed = session.session_elapsed_seconds()
        self.assertGreaterEqual(elapsed, 14.9)
        payload = session.session_clock_payload()
        self.assertTrue(payload["session_running"])
        self.assertGreaterEqual(payload["session_elapsed"], 14.9)

    def test_pause_freezes_elapsed(self):
        session = ClientSession(session_id="paused")
        session.running = True
        session.paused = True
        session.simulation = False
        session.session_elapsed = 42.0
        session.session_tick_at = time.time() - 100
        session.wallet_start = 43.0
        self.assertAlmostEqual(session.session_elapsed_seconds(), 42.0, places=1)
        payload = session.session_clock_payload()
        self.assertFalse(payload["session_running"])
        self.assertAlmostEqual(payload["wallet_start"], 43.0)

    def test_sim_clock_hides_wallet_start(self):
        session = ClientSession(session_id="sim")
        session.simulation = True
        session.wallet_start = 43.0
        self.assertEqual(session.session_clock_payload()["wallet_start"], 0.0)

    def test_start_reanchors_wallet_and_resets_clock(self):
        server = (ROOT / "src" / "web_server.py").read_text()
        self.assertIn("session.session_elapsed = 0.0", server)
        self.assertIn("if fresh and session.live_balance:", server)
        self.assertIn("session.wallet_start = float(session.live_balance)", server)
        self.assertIn("if start <= 1:", server)
        self.assertNotIn("start >= 90", server)

    def test_bleed_stops_pause_the_session(self):
        server = (ROOT / "src" / "web_server.py").read_text()
        self.assertIn("peak_drawdown_hit", server)
        self.assertIn("_halt_if_peak_drawdown", server)
        self.assertIn("clear_circuit", server)
        self.assertIn("wallet_day_peak", server)
        self.assertIn("this is a bleed stop, not a profit lock", server)

    def test_ui_has_session_timer(self):
        html = (ROOT / "web" / "templates" / "index.html").read_text()
        js = (ROOT / "web" / "static" / "app.js").read_text()
        self.assertIn('id="session-timer"', html)
        self.assertIn('id="stat-pnl-start"', html)
        self.assertIn("paintSessionClock", js)
        self.assertIn("from $", js)
        self.assertIn("this.paintSessionClock()", js)


if __name__ == "__main__":
    unittest.main()
