"""At-rest storage for the Binance API secret.

user_settings.json never stores the secret in plaintext. On macOS the secret
is written to Keychain. Everywhere else — and as a Mac fallback — it lives in
a chmod 0600 sidecar next to the settings file, encrypted with a machine-bound
HMAC-SHA256 keystream and authenticator.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

PREFIX = "vb1."
SERVICE = "com.knull66.vibesbot"
ACCOUNT = "binance_api_secret"
PEPPER = b"vibesbot-wallet-secret-v1"
KEYCHAIN_SENTINEL = "keychain"
STORED_SENTINEL = "stored"
SIDECAR_NAME = "binance_api_secret.enc"


def _machine_key() -> bytes:
    parts = [PEPPER, str(Path.home()).encode("utf-8")]
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            for line in proc.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    parts.append(line.encode("utf-8"))
                    break
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
            try:
                if candidate.exists():
                    parts.append(candidate.read_bytes().strip())
                    break
            except OSError:
                continue
    return hashlib.sha256(b"\x1f".join(parts)).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    produced = 0
    counter = 0
    while produced < length:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        blocks.append(block)
        produced += len(block)
        counter += 1
    return b"".join(blocks)[:length]


def encrypt_secret(plaintext: str, key: Optional[bytes] = None) -> str:
    raw = (plaintext or "").encode("utf-8")
    if not raw:
        return ""
    material = key if key is not None else _machine_key()
    nonce = secrets.token_bytes(16)
    cipher = bytes(a ^ b for a, b in zip(raw, _keystream(material, nonce, len(raw))))
    mac = hmac.new(material, nonce + cipher, hashlib.sha256).digest()
    return PREFIX + base64.urlsafe_b64encode(nonce + mac + cipher).decode("ascii")


def decrypt_secret(blob: str, key: Optional[bytes] = None) -> str:
    text = (blob or "").strip()
    if not text:
        return ""
    if not text.startswith(PREFIX):
        return text
    material = key if key is not None else _machine_key()
    try:
        packed = base64.urlsafe_b64decode(text[len(PREFIX):].encode("ascii"))
    except (ValueError, TypeError):
        return ""
    if len(packed) < 48:
        return ""
    nonce, mac, cipher = packed[:16], packed[16:48], packed[48:]
    expected = hmac.new(material, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        return ""
    plain = bytes(a ^ b for a, b in zip(cipher, _keystream(material, nonce, len(cipher))))
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def looks_like_sentinel(value: str) -> bool:
    text = (value or "").strip()
    return text in {KEYCHAIN_SENTINEL, STORED_SENTINEL} or text.startswith(PREFIX)


def sidecar_path(settings_path: Path) -> Path:
    return Path(settings_path).with_name(SIDECAR_NAME)


def chmod_private(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def chmod_private_dir(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass


def keychain_get() -> Optional[str]:
    if sys.platform != "darwin":
        return None
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.rstrip("\n")
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def keychain_set(secret: str) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        proc = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", secret],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def keychain_delete() -> None:
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
            capture_output=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def persist_secret(settings_path: Path, secret: str) -> str:
    """Write sidecar + optional Keychain. Returns the JSON sentinel, never the secret."""
    secret = secret or ""
    path = sidecar_path(settings_path)
    if not secret:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        keychain_delete()
        return ""
    path.write_text(encrypt_secret(secret), encoding="utf-8")
    chmod_private(path)
    if keychain_set(secret):
        return KEYCHAIN_SENTINEL
    return STORED_SENTINEL


def load_secret(settings_path: Path, json_field: str = "") -> Tuple[str, bool]:
    """Return (secret, needs_migration_off_plaintext_json)."""
    field = (json_field or "").strip()
    stored = keychain_get()
    if stored:
        return stored, bool(field) and not looks_like_sentinel(field)
    path = sidecar_path(settings_path)
    if path.exists():
        try:
            blob = path.read_text(encoding="utf-8").strip()
        except OSError:
            blob = ""
        if blob:
            secret = decrypt_secret(blob)
            if secret:
                return secret, bool(field) and not looks_like_sentinel(field)
    if not field or field in {KEYCHAIN_SENTINEL, STORED_SENTINEL}:
        return "", False
    if field.startswith(PREFIX):
        return decrypt_secret(field), True
    return field, True
