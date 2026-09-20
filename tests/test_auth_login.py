"""Account login must reject unknown users and wrong passwords."""
import tempfile
import unittest
from pathlib import Path

from src.auth import AuthManager


class AuthLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = AuthManager(Path(self.tmp.name) / "auth.json")
        user, error = self.auth.register("owner", "correct-password-1", "")
        self.assertEqual(error, "")
        self.assertIsNotNone(user)

    def tearDown(self):
        self.tmp.cleanup()

    def test_wrong_password_is_rejected(self):
        token, user, error = self.auth.login("owner", "wrong-password-1")
        self.assertIsNone(token)
        self.assertIsNone(user)
        self.assertEqual(error, "Invalid username or password")

    def test_random_user_is_rejected(self):
        token, user, error = self.auth.login("randomuser", "randompass")
        self.assertIsNone(token)
        self.assertIsNone(user)
        self.assertEqual(error, "Invalid username or password")

    def test_correct_password_works(self):
        token, user, error = self.auth.login("owner", "correct-password-1")
        self.assertTrue(token)
        self.assertEqual(user.username, "owner")
        self.assertEqual(error, "")

    def test_register_without_invite_is_blocked_after_owner_exists(self):
        user, error = self.auth.register("intruder", "password12", "")
        self.assertIsNone(user)
        self.assertEqual(error, "Valid invite code required")


if __name__ == "__main__":
    unittest.main()
