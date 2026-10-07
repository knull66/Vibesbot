import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.updater import (
    UpdateCandidate,
    Updater,
    parse_version,
    pick_newest,
    redact_git_url,
    source_label,
)


class PickNewestTests(unittest.TestCase):
    def test_origin_beats_stale_github_release(self):
        best = pick_newest([
            UpdateCandidate("1.49.0", "https://github/zip/v1.49.0", "github-release"),
            UpdateCandidate("1.49.0", "https://github/zip/main", "github-main"),
            UpdateCandidate("1.50.0", "vibesbot-git:origin:cursor/anti-bleed-892d", "origin-main"),
        ])
        self.assertEqual(best.version, "1.50.0")
        self.assertTrue(best.source.startswith("origin"))

    def test_github_main_beats_old_release(self):
        best = pick_newest([
            UpdateCandidate("1.49.0", "rel", "github-release"),
            UpdateCandidate("1.50.0", "main", "github-main"),
        ])
        self.assertEqual(best.version, "1.50.0")
        self.assertEqual(best.source, "github-main")

    def test_empty_list(self):
        self.assertIsNone(pick_newest([]))

    def test_parse_and_label(self):
        self.assertGreater(parse_version("1.50.0"), parse_version("1.49.0"))
        self.assertEqual(source_label("github-release"), "GitHub")
        self.assertEqual(source_label("origin-cursor/anti-bleed-892d"), "Origin")
        self.assertIn("origin.cursor.com", redact_git_url(
            "https://x-access-token:secret@origin.cursor.com/git/knullproject/Vibesbot.git"
        ))
        self.assertNotIn("secret", redact_git_url(
            "https://x-access-token:secret@origin.cursor.com/git/knullproject/Vibesbot.git"
        ))


class DualSourceCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_picks_origin_when_ahead(self):
        http = [
            UpdateCandidate("1.49.0", "https://github/rel", "github-release", "rel"),
        ]
        git = [
            UpdateCandidate("1.50.0", "vibesbot-git:origin:cursor/anti-bleed-892d", "origin-cursor/anti-bleed-892d"),
        ]
        updater = Updater(app_path=".")
        updater.current_version = "1.49.0"
        with patch.object(updater, "_http_candidates", AsyncMock(return_value=http)), \
             patch.object(updater, "_git_candidates", return_value=git):
            info = await updater.check_for_updates()
        self.assertTrue(info.available)
        self.assertEqual(info.latest_version, "1.50.0")
        self.assertTrue(info.source.startswith("origin"))
        self.assertIn("vibesbot-git:", info.download_url)


class FlatZipApplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_reads_flat_zip_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            app.mkdir()
            (app / "VERSION").write_text("1.49.0\n")
            src = root / "pack"
            src.mkdir()
            (src / "VERSION").write_text("1.50.0\n")
            (src / "src").mkdir()
            (src / "src" / "ok.py").write_text("x=1\n")
            dl = root / "dl"
            dl.mkdir()
            zip_path = dl / "update.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(src / "VERSION", "VERSION")
                zf.write(src / "src" / "ok.py", "src/ok.py")
            updater = Updater(app_path=str(app))
            ok = await updater.apply_update(zip_path, "1.50.0")
            self.assertTrue(ok)
            self.assertEqual((app / "VERSION").read_text().strip(), "1.50.0")


if __name__ == "__main__":
    unittest.main()
