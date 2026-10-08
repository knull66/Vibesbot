import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.ship_inflate import inflate_ship


class ShipInflateTests(unittest.TestCase):
    def test_restores_missing_file_from_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ship = root / ".ship"
            ship.mkdir()
            payload = b"hello vibesbot ship inflate\n" * 20
            digest = hashlib.sha256(payload).hexdigest()
            mid = len(payload) // 2
            (ship / "demo.00.b64").write_text(base64.b64encode(payload[:mid]).decode() + "\n")
            (ship / "demo.01.b64").write_text(base64.b64encode(payload[mid:]).decode() + "\n")
            (ship / "manifest.json").write_text(json.dumps([{
                "path": "web/static/demo.js",
                "sha256": digest,
                "parts": ["demo.00.b64", "demo.01.b64"],
                "size": len(payload),
                "encoding": "base64",
            }]))
            target = root / "web" / "static" / "demo.js"
            # Existing stub must NOT be overwritten (protects Install updates)
            target.parent.mkdir(parents=True)
            target.write_text("STUB\n")
            self.assertEqual(inflate_ship(root), [])
            self.assertEqual(target.read_text(), "STUB\n")
            target.unlink()
            restored = inflate_ship(root)
            self.assertEqual(restored, ["web/static/demo.js"])
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(inflate_ship(root), [])

    def test_ui_has_binance_stake_chips(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "templates" / "index.html").read_text()
        js = (root / "web" / "static" / "app.js").read_text()
        self.assertIn('id="stake-chips"', html)
        self.assertIn('id="prefs-stake-chips"', html)
        self.assertIn('data-stake="1"', html)
        self.assertIn('data-stake="50"', html)
        self.assertIn("applyQuickStake", js)
        self.assertIn("paintStakeChips", js)


if __name__ == "__main__":
    unittest.main()
