import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from src.secret_box import (
    PREFIX,
    STORED_SENTINEL,
    decrypt_secret,
    encrypt_secret,
    sidecar_path,
)
from src.user_settings import SettingsManager


class SecretBoxTests(unittest.TestCase):
    def test_roundtrip_and_tamper(self):
        key = b"x" * 32
        blob = encrypt_secret("super-secret", key)
        self.assertTrue(blob.startswith(PREFIX))
        self.assertEqual(decrypt_secret(blob, key), "super-secret")
        self.assertEqual(decrypt_secret(blob[:-1] + ("A" if blob[-1] != "A" else "B"), key), "")
        self.assertEqual(encrypt_secret(""), "")

    def test_settings_never_write_plaintext_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SettingsManager(Path(tmp))
            manager.update_binance_credentials("live-key", "live-secret-value", False)
            raw = (Path(tmp) / "user_settings.json").read_text(encoding="utf-8")
            self.assertNotIn("live-secret-value", raw)
            payload = json.loads(raw)
            self.assertEqual(payload["binance"]["api_secret_encrypted"], STORED_SENTINEL)
            mode = stat.S_IMODE(os.stat(Path(tmp) / "user_settings.json").st_mode)
            self.assertEqual(mode, 0o600)
            sidecar = sidecar_path(Path(tmp) / "user_settings.json")
            self.assertTrue(sidecar.exists())
            self.assertNotIn("live-secret-value", sidecar.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(os.stat(sidecar).st_mode), 0o600)
            again = SettingsManager(Path(tmp))
            self.assertEqual(again.settings.binance.api_secret, "live-secret-value")
            self.assertEqual(again.settings.binance.prediction_wallet, "")

    def test_migrates_legacy_plaintext_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_settings.json"
            path.write_text(json.dumps({
                "binance": {
                    "api_key": "old-key",
                    "api_secret_encrypted": "plain-legacy-secret",
                    "is_testnet": False,
                    "prediction_wallet": "",
                }
            }), encoding="utf-8")
            manager = SettingsManager(Path(tmp))
            self.assertEqual(manager.settings.binance.api_secret, "plain-legacy-secret")
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("plain-legacy-secret", raw)
            self.assertEqual(json.loads(raw)["binance"]["api_secret_encrypted"], STORED_SENTINEL)
            again = SettingsManager(Path(tmp))
            self.assertEqual(again.settings.binance.api_secret, "plain-legacy-secret")


if __name__ == "__main__":
    unittest.main()
