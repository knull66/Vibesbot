import unittest

from src.round_signal import combine_indicator_votes, crowd_agrees, tape_vote


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
        self.assertFalse(crowd_agrees("DOWN", {"up": 0.96, "down": 0.04}))


if __name__ == "__main__":
    unittest.main()
