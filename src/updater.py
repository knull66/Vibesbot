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
        if not (path / "src").is_dir() and not (path / "run_bot.py").is_file():
            continue
        seen.add(key)
        roots.append(path)
    return roots


def purge_retired_from(root: Path) -> int:
    """Delete Playwright clicker leftovers and unused deploy files under root."""
    root = Path(root)
    if not root.is_dir():
        return 0
    removed = 0
    for rel in RETIRED_CLICKER_FILES:
        path = root / rel
        if path.exists() and _remove_path(path):
            removed += 1
    for dir_name in RETIRED_DIR_NAMES:
        path = root / dir_name
        if path.exists() and _remove_path(path):
            removed += 1
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_WALK_DIRS]
        here = Path(dirpath)
        if here.name == "__pycache__":
            for name in filenames:
                if name.split(".")[0] in RETIRED_CLICKER_PYC_PREFIXES:
                    if _remove_path(here / name):
                        removed += 1
            continue
        for name in list(dirnames):
            if "playwright" in name.lower():
                if _remove_path(here / name):
                    removed += 1
                dirnames.remove(name)
        for name in filenames:
            lowered = name.lower()
            if name in _KEEP_PLAYWRIGHT_NAMES:
                continue
            if name in ("run_bot.py", "browser_execution.py") or "playwright" in lowered:
                if _remove_path(here / name):
                    removed += 1
    return removed


def purge_retired_installs(app_path: Optional[Path] = None, extra_roots: Optional[Iterable[Path]] = None) -> int:
    """Clean every known Vibesbot folder, including Downloads leftovers."""
    roots = known_install_roots(app_path)
    if extra_roots:
        for item in extra_roots:
            path = Path(item)
            if path.is_dir() and path not in roots:
                roots.append(path)
    removed = 0
    for root in roots:
        removed += purge_retired_from(root)
    if removed:
        logger.info(f"Purged {removed} leftover Playwright/clicker files")
    return removed


@dataclass
class UpdateCandidate:
    version: str
    download_url: str
    source: str
    notes: str = ""


@dataclass
class UpdateInfo:
    """Información sobre una actualización disponible."""
    available: bool
    current_version: str
    latest_version: str
    download_url: Optional[str] = None
    release_notes: Optional[str] = None
    published_at: Optional[str] = None
    source: str = ""


def parse_version(value: str) -> Tuple[int, int, int]:
    raw = (value or "").strip().lstrip("vV")
    parts = []
    for chunk in raw.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def source_label(source: str) -> str:
    kind = str(source or "").lower()
    if kind.startswith("origin") or "cursor.com" in kind:
        return "Origin"
    if kind.startswith("github"):
        return "GitHub"
    return (source or "update").strip() or "update"


def pick_newest(candidates: Iterable[UpdateCandidate]) -> Optional[UpdateCandidate]:
    best: Optional[UpdateCandidate] = None
    for item in candidates:
        if not item or not str(item.version or "").strip():
            continue
        if best is None or parse_version(item.version) > parse_version(best.version):
            best = item
    return best


def redact_git_url(url: str) -> str:
    text = str(url or "")
    if "@" in text and "://" in text:
        scheme, rest = text.split("://", 1)
        rest = rest.split("@", 1)[-1]
        return f"{scheme}://{rest}"
    return text


def _git_env() -> dict:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    ask = env.get("GIT_ASKPASS") or ""
    if ask and not Path(ask).exists():
        env.pop("GIT_ASKPASS", None)
    return env


class Updater:
    """
    Gestor de actualizaciones automáticas.
    
    Verifica y aplica actualizaciones desde GitHub.
    """
    
    def __init__(self, app_path: Optional[str] = None):
        self.app_path = Path(app_path) if app_path else self._find_app_path()
        self.version_file = self.app_path / VERSION_FILE
        self.current_version = self._get_current_version()
        self.last_error = ""
    
    def _find_app_path(self) -> Path:
        """Siempre la copia que está ejecutándose, no Downloads."""
        running = Path(__file__).resolve().parent.parent
        if (running / "src").exists() and (running / "web").exists():
            return running
        possible_paths = [
            running,
            Path("/Applications/Vibesbot.app/Contents/Resources/vibesbot"),
            Path.home() / "Downloads" / "Vibesbot",
        ]
        for path in possible_paths:
            if path.exists() and (path / "src").exists():
                return path
        return running

    def _read_version_file(self) -> str:
        if self.version_file.exists():
            return self.version_file.read_text().strip().lstrip("vV")
        return CURRENT_VERSION

    def _read_js_app_version(self) -> Optional[str]:
        """APP_VERSION in web/static/app.js — can lag VERSION after partial updates."""
        app_js = self.app_path / "web" / "static" / "app.js"
        if not app_js.is_file():
            return None
        try:
            text = app_js.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        match = re.search(
            r"const\s+APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]",
            text,
        )
        if not match:
            return None
        return match.group(1).strip().lstrip("vV")

    def _get_current_version(self) -> str:
        """Effective install version: older of VERSION file and APP_VERSION in JS."""
        file_v = self._read_version_file()
        js_v = self._read_js_app_version()
 