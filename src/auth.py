"""
Autenticación de usuarios para Vibesbot.

El primer usuario se convierte en owner. Después el registro
requiere un código de invitación (no es público por defecto).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .utils.logger import get_logger

logger = get_logger("auth")

COOKIE_NAME = "vb_session"
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
SESSION_DAYS = 30
PBKDF2_ROUNDS = 200_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    salt: str
    is_owner: bool = False
    created_at: str = ""

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "is_owner": self.is_owner,
            "created_at": self.created_at,
        }


@dataclass
class Session:
    token: str
    user_id: str
    expires: str
    created_at: str = ""


class AuthManager:
    """Usuarios, sesiones e invitaciones persistidos en JSON."""

    def __init__(self, data_file: Optional[Path] = None):
        root = Path(__file__).parent.parent / "data"
        root.mkdir(parents=True, exist_ok=True)
        self.data_file = data_file or (root / "auth.json")
        self.users: Dict[str, User] = {}
        self.username_index: Dict[str, str] = {}
        self.sessions: Dict[str, Session] = {}
        self.invites: List[str] = []
        self.allow_open_registration = False
        self._load()

    def _load(self) -> None:
        if not self.data_file.exists():
            return
        try:
            data = json.loads(self.data_file.read_text())
            for uid, raw in data.get("users", {}).items():
                user = User(
                    id=uid,
                    username=raw["username"],
                    password_hash=raw["password_hash"],
                    salt=raw["salt"],
                    is_owner=bool(raw.get("is_owner", False)),
                    created_at=raw.get("created_at", ""),
                )
                self.users[uid] = user
                self.username_index[user.username.lower()] = uid
            for token, raw in data.get("sessions", {}).items():
                self.sessions[token] = Session(
                    token=token,
                    user_id=raw["user_id"],
                    expires=raw["expires"],
                    created_at=raw.get("created_at", ""),
                )
            self.invites = list(data.get("invites", []))
            self.allow_open_registration = bool(data.get("allow_open_registration", False))
            self._purge_sessions()
        except Exception as e:
            logger.error(f"Error loading auth data: {e}")

    def _save(self) -> None:
        payload = {
            "users": {
                uid: {
                    "username": u.username,
                    "password_hash": u.password_hash,
                    "salt": u.salt,
                    "is_owner": u.is_owner,
                    "created_at": u.created_at,
                }
                for uid, u in self.users.items()
            },
            "sessions": {
                token: {
                    "user_id": s.user_id,
                    "expires": s.expires,
                    "created_at": s.created_at,
                }
                for token, s in self.sessions.items()
            },
            "invites": self.invites,
            "allow_open_registration": self.allow_open_registration,
        }
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.data_file)

    def _purge_sessions(self) -> None:
        now = _now()
        expired = []
        for token, session in self.sessions.items():
            try:
                if datetime.fromisoformat(session.expires) <= now:
                    expired.append(token)
            except Exception:
                expired.append(token)
        for token in expired:
            self.sessions.pop(token, None)
        if expired:
            self._save()

    def has_users(self) -> bool:
        return bool(self.users)

    def status(self) -> dict:
        return {
            "has_users": self.has_users(),
            "setup_required": not self.has_users(),
            "registration_open": self.can_register(),
            "invite_required": self.has_users() and not self.allow_open_registration,
        }

    def can_register(self) -> bool:
        if not self.has_users():
            return True
        if self.allow_open_registration:
            return True
        if self.invites:
            return True
        if os.getenv("VIBESBOT_INVITE_CODE"):
            return True
        return False

    def list_users(self) -> List[dict]:
        return [u.public_dict() for u in self.users.values()]

    def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)

    def get_user_by_username(self, username: str) -> Optional[User]:
        uid = self.username_index.get(username.strip().lower())
        return self.users.get(uid) if uid else None

    def hash_password(self, password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
        salt_bytes = salt or os.urandom(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_bytes,
            PBKDF2_ROUNDS,
        )
        return (
            base64.b64encode(digest).decode("ascii"),
            base64.b64encode(salt_bytes).decode("ascii"),
        )

    def verify_password(self, user: User, password: str) -> bool:
        try:
            salt = base64.b64decode(user.salt.encode("ascii"))
            hashed, _ = self.hash_password(password, salt)
            return secrets.compare_digest(hashed, user.password_hash)
        except Exception:
            return False

    def _validate_credentials(self, username: str, password: str) -> Optional[str]:
        username = username.strip()
        if not USERNAME_RE.match(username):
            return "Username must be 3-24 letters, numbers or underscore"
        if len(password) < 8:
            return "Password must be at least 8 characters"
        if len(password) > 128:
            return "Password is too long"
        return None

    def _consume_invite(self, invite_code: str) -> bool:
        env_code = (os.getenv("VIBESBOT_INVITE_CODE") or "").strip()
        code = (invite_code or "").strip().upper()
        if env_code and code == env_code.strip().upper():
            return True
        if code and code in self.invites:
            self.invites.remove(code)
            return True
        return False

    def register(self, username: str, password: str, invite_code: str = "") -> tuple[Optional[User], str]:
        error = self._validate_credentials(username, password)
        if error:
            return None, error
        if self.get_user_by_username(username):
            return None, "Username already exists"

        is_setup = not self.has_users()
        if not is_setup:
            if not self.allow_open_registration and not self._consume_invite(invite_code):
                return None, "Valid invite code required"

        user = User(
            id=secrets.token_hex(8),
            username=username.strip(),
            password_hash="",
            salt="",
            is_owner=is_setup,
            created_at=_iso(_now()),
        )
        user.password_hash, user.salt = self.hash_password(password)
        self.users[user.id] = user
        self.username_index[user.username.lower()] = user.id
        self._save()
        logger.info(f"User created: {user.username} owner={user.is_owner}")
        return user, ""

    def login(self, username: str, password: str) -> tuple[Optional[str], Optional[User], str]:
        user = self.get_user_by_username(username)
        if not user or not self.verify_password(user, password):
            return None, None, "Invalid username or password"
        token = secrets.token_urlsafe(32)
        expires = _now() + timedelta(days=SESSION_DAYS)
        self.sessions[token] = Session(
            token=token,
            user_id=user.id,
            expires=_iso(expires),
            created_at=_iso(_now()),
        )
        self._save()
        return token, user, ""

    def logout(self, token: Optional[str]) -> None:
        if token and token in self.sessions:
            self.sessions.pop(token, None)
            self._save()

    def user_from_token(self, token: Optional[str]) -> Optional[User]:
        if not token:
            return None
        session = self.sessions.get(token)
        if not session:
            return None
        try:
            if datetime.fromisoformat(session.expires) <= _now():
                self.sessions.pop(token, None)
                self._save()
                return None
        except Exception:
            return None
        return self.users.get(session.user_id)

    def user_from_cookies(self, cookies: dict) -> Optional[User]:
        return self.user_from_token(cookies.get(COOKIE_NAME))

    def create_invite(self, owner: User) -> tuple[Optional[str], str]:
        if not owner.is_owner:
            return None, "Only the owner can create invites"
        code = "VIBE-" + secrets.token_hex(2).upper() + "-" + secrets.token_hex(2).upper()
        self.invites.append(code)
        self._save()
        return code, ""

    def set_open_registration(self, owner: User, enabled: bool) -> str:
        if not owner.is_owner:
            return "Only the owner can change registration"
        self.allow_open_registration = bool(enabled)
        self._save()
        return ""

    def delete_user(self, owner: User, user_id: str) -> str:
        if not owner.is_owner:
            return "Only the owner can delete users"
        user = self.users.get(user_id)
        if not user:
            return "User not found"
        if user.is_owner:
            return "Cannot delete the owner"
        self.username_index.pop(user.username.lower(), None)
        self.users.pop(user_id, None)
        stale = [t for t, s in self.sessions.items() if s.user_id == user_id]
        for token in stale:
            self.sessions.pop(token, None)
        self._save()
        return ""

    def change_password(self, user: User, current: str, new_password: str) -> str:
        if not self.verify_password(user, current):
            return "Current password is wrong"
        if len(new_password) < 8:
            return "Password must be at least 8 characters"
        user.password_hash, user.salt = self.hash_password(new_password)
        self._save()
        return ""


_AUTH: Optional[AuthManager] = None


def get_auth() -> AuthManager:
    global _AUTH
    if _AUTH is None:
        _AUTH = AuthManager()
    return _AUTH
