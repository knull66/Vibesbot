from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NativePrefsTests(unittest.TestCase):
    def test_version_is_current(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertEqual(version, "1.45.0")
        app_js = (ROOT / "web" / "static" / "app.js").read_text()
        self.assertIn("const APP_VERSION = '1.45.0'", app_js)

    def test_settings_is_sidebar_prefs(self):
        html = (ROOT / "web" / "templates" / "index.html").read_text()
        self.assertIn('class="modal prefs"', html)
        self.assertIn('class="prefs-sidebar"', html)
        self.assertIn('id="prefs-title"', html)
        self.assertIn('class="pref-section"', html)
        for panel in ("binance", "trading", "signal", "account", "app"):
            self.assertIn(f'data-panel="{panel}"', html)
            self.assertIn(f'id="panel-{panel}"', html)
        for field_id in (
            "api-key", "api-secret", "use-testnet", "prediction-wallet",
            "stake-mode", "bet-percent", "bet-amount",
            "confidence-threshold", "daily-loss-pct", "daily-loss-limit",
            "strategy-select", "rsi-weight", "macd-weight", "bb-weight", "mom-weight",
            "current-password", "new-password",
            "sound-enabled", "sound-volume",
            "open-registration", "companion-enabled", "owner-account-tools",
            "modal-close", "btn-reset-sim", "btn-reset-real", "btn-clear-feed",
        ):
            self.assertIn(f'id="{field_id}"', html)

    def test_js_exposes_native_settings_hook(self):
        app_js = (ROOT / "web" / "static" / "app.js").read_text()
        self.assertIn("window.__vbOpenSettings", app_js)
        self.assertIn("openSettings(", app_js)
        self.assertIn("closeSettings(", app_js)
        self.assertIn("event.key === ','", app_js)
        self.assertIn("event.key === 'Escape'", app_js)
        self.assertIn("hideSettingsTabs(['binance', 'trading', 'signal'])", app_js)

    def test_launcher_is_native_window(self):
        launcher = (ROOT / "app_launcher.py").read_text()
        self.assertIn("NSWindowStyleMaskFullSizeContentView", launcher)
        self.assertIn("setTitlebarAppearsTransparent_", launcher)
        self.assertIn("NSWindowTitleHidden", launcher)
        self.assertIn("openSettings:", launcher)
        self.assertIn('window.__vbOpenSettings && window.__vbOpenSettings();', launcher)
        self.assertIn("vb-native", launcher)
        self.assertIn("Settings…", launcher)


if __name__ == "__main__":
    unittest.main()
