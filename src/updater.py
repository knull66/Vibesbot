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
