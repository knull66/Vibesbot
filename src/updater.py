"""
Sistema de auto-actualización para Vibesbot.

Checks GitHub (release + main VERSION) and Origin git remotes, then
overlays the newest zip.
"""
import asyncio
import aiohttp
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .utils.logger import get_logger

logger = get_logger("updater")

# Configuración
GITHUB_REPO = "knull66/Vibesbot"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
GITHUB_RAW_VERSION = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/VERSION"
GITHUB_MAIN_ZIP = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip"
ORIGIN_GIT = "https://origin.cursor.com/git/knullproject/Vibesbot.git"
GIT_SCHEME = "vibesbot-git:"
VERSION_FILE = "VERSION"
CURRENT_VERSION = "1.0.0"

# Overlay zip copies on top and cannot rmtree. These leftovers stay on disk
# until we delete them: Playwright Event Contracts clicker + unused deploy files.
RETIRED_CLICKER_FILES = (
    "src/browser_execution.py",
    "src/main.py",
    "run_bot.py",
    "tests/test_playwright_disabled.py",
    "Procfile",
    "render.yaml",
    "runtime.txt",
    "requirements-web.txt",
)
RETIRED_CLICKER_PYC_PREFIXES = ("browser_execution", "main", "run_bot")
RETIRED_DIR_NAMES = (
    ".playwright",
    "playwright-browsers",
    "ms-playwright",
)
_SKIP_WALK_DIRS = {".git", "venv", ".venv", "node_modules", "dist", "build"}
_KEEP_PLAYWRIGHT_NAMES = {"test_playwright_removed.py"}


def _remove_path(path: Path) -> bool:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
            logger.info(f"Removed leftover {path}")
            return True
        if path.is_dir():
            shutil.rmtree(path)
            logger.info(f"Removed leftover dir {path}")
            return True
    except OSError as exc:
        logger.warning(f"Could not remove {path}: {exc}")
    return False


def known_install_roots(primary: Optional[Path] = None) -> List[Path]:
    """Running copy, Mac .app, and ~/Downloads/Vibesbot (zip leftovers)."""
    candidates = [
        primary,
        Path(__file__).resolve().parent.parent,
        Path.home() / "Downloads" / "Vibesbot",
        Path("/Applications/Vibesbot.app/Contents/Resources/vibesbot"),
        Path.home() / "Downloads" / "Vibesbot.app" / "Contents" / "Resources" / "vibesbot",
        Path.home() / "Applications" / "Vibesbot.app" / "Contents" / "Resources" / "vibesbot",
    ]
    roots: List[Path] = []
    seen = set()
    for raw in candidates:
        if raw is None:
            continue
        try:
            path = Path(raw).expanduser().resolve()
        except OSError:
            continue
        key = str(path).lower()
        if key in seen or not path.is_dir():
            continue
        if not (path / "src").is_dir() and not (path / "run_bot.py").