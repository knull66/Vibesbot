"""
Companion LAN pairing for the native Mac app.

The Mac is the source of truth. A phone on the same Wi-Fi can only
connect after entering a pairing PIN shown on the Mac. No cloud.
"""
from __future__ import annotations

import json
import secrets
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .utils.logger import get_logger

logger = get_logger("companion")

PIN_TTL_MINUTES = 10
MAX_FAILS = 5
LOCK_SECONDS = 30
LOOPBACK = {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    return host.strip().lower().split("%")[0] in LOOPBACK


def lan_addresses() -> List[str]:
    """IPv4 addresses on this machine that a phone can reach."""
    found = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            if ip not in found:
                found.append(ip)
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127.") and ip not in found:
            found.insert(0, ip)
    except Exception:
        pass
    return found


class CompanionHub:
    """In-memory pairing PIN plus a persisted enabled flag."""

    def __init__(self, data_file: Optional[Path] = None):
        root = Path(__file__).parent.parent / "data"
        root.mkdir(parents=True, exist_ok=True)
        self.data_file = data_file or (root / "companion.json")
        self.enabled = False
        self.pin = ""
        self.pin_expires: Optional[datetime] = None
        self.fails = 0
        self.lock_until: Optional[datetime] = None
        self._load()

    def _load(self) -> None:
        if not self.data_file.exists():
            return
        try:
            data = json.loads(self.data_file.read_text())
            self.enabled = bool(data.get("enabled", False))
        except Exception as e:
            logger.error(f"Error loading companion state: {e}")

    def _save(self) -> None:
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"enabled": self.enabled}, indent=2))
        tmp.replace(self.data_file)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        if self.enabled:
            self.rotate_pin()
        else:
            self.pin = ""
            self.pin_expires = None
        self._save()

    def rotate_pin(self) -> str:
        self.pin = f"{secrets.randbelow(1_000_000):06d}"
        self.pin_expires = utcnow() + timedelta(minutes=PIN_TTL_MINUTES)
        self.fails = 0
        self.lock_until = None
        logger.info("Companion PIN rotated")
        return self.pin

    def _ensure_pin(self) -> None:
        if not self.enabled:
            return
        if not self.pin or not self.pin_expires or self.pin_expires <= utcnow():
            self.rotate_pin()

    def info(self, port: int = 8080) -> dict:
        self._ensure_pin()
        urls = [f"http://{ip}:{port}" for ip in lan_addresses()]
        remaining = 0
        if self.pin_expires:
            remaining = max(0, int((self.pin_expires - utcnow()).total_seconds()))
        return {
            "enabled": self.enabled,
            "pin": self.pin if self.enabled else "",
            "pin_seconds_left": remaining,
            "urls": urls,
        }

    def public_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "urls": [f"http://{ip}:8080" for ip in lan_addresses()] if self.enabled else [],
        }

    def verify_pin(self, pin: str) -> tuple[bool, str]:
        if not self.enabled:
            return False, "Companion is disabled on the Mac"
        if self.lock_until and utcnow() < self.lock_until:
            wait = int((self.lock_until - utcnow()).total_seconds())
            return False, f"Too many attempts. Wait {wait}s"
        self._ensure_pin()
        candidate = "".join(ch for ch in str(pin) if ch.isdigit())
        if len(candidate) != 6 or candidate != self.pin:
            self.fails += 1
            if self.fails >= MAX_FAILS:
                self.lock_until = utcnow() + timedelta(seconds=LOCK_SECONDS)
                self.fails = 0
            return False, "Invalid pairing code"
        self.fails = 0
        return True, ""


_HUB: Optional[CompanionHub] = None


def get_companion() -> CompanionHub:
    global _HUB
    if _HUB is None:
        _HUB = CompanionHub()
    return _HUB
