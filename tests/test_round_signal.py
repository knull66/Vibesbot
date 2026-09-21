import unittest

from src.round_signal import combine_indicator_votes, crowd_agrees, price_confirms, tape_vote


class RoundSignalTests(unittest.TestCase):
    def test_majority_up_bets(self):
        signal, confidence, label = combine_indicator_votes(1, 1, 1, 1, 0)
        self.assertEqual(signal, "UP")
        self.assertGreaterEqual(confidence, 0.55)
        self.assertIn("Multi-strategy", label)

    def test_weak_mix_waits(self):
        signal, confidence, label = combine_indicator_votes(0, 1, 0, -1, 0)
        self.assertEqual(signal, "WAIT")
        self.assertEqual(confidence, 0.50)
        self.assertIn("waiting", label.lower())

    def test_tape_can_confirm_down(self):
        signal, _, _ = combine_indicator_votes(-1, -1, 0, 0, -1)
        self.assertEqual(signal, "DOWN")

    def test_tape_vote_from_sell_flow(self):
        self.assertEqual(tape_vote(-0.4, -0.2), -1)
        self.assertEqual(tape_vote(0.4, 0.2), 1)
        self.assertEqual(tape_vote(0.0, 0.0), 0)

    def test_crowd_agrees_with_our_side(self):
        self.assertTrue(crowd_agrees("DOWN", {"up": 0.44, "down": 0.56}))
        self.assertTrue(crowd_agrees("UP", {"up": 0.39, "down": 0.61}))
        self.assertFalse(crowd_agrees("DOWN", {"up": 0.96, "down": 0.04}))
        self.assertFalse(crowd_agrees("UP", {"up": 0.04, "down": 0.96}))

    def test_fifty_fifty_without_a_move_is_not_confirmed(self):
        ok, reason = price_confirms("UP", 86000.0, 86000.0)
        self.assertFalse(ok)
        self.assertIn("above beat", reason)

    def test_joins_a_move_already_underway(self):
        ok, _ = price_confirms("UP", 86040.0, 86000.0)
        self.assertTrue(ok)
        down_ok, _ = price_confirms("DOWN", 85970.0, 86000.0)
        self.assertTrue(down_ok)
        near, _ = price_confirms("DOWN", 86323.06, 86334.91)
        self.assertTrue(near)
        fighting, _ = price_confirms("DOWN", 86040.0, 86000.0)
        self.assertFalse(fighting)


if __name__ == "__main__":
    unittest.main()
