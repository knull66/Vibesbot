"""Rebuild oversized source files from .ship/*.b64 parts (GitHub MCP size limit).

GitHub main carries big files as empty stubs plus base64 parts under .ship/.
Those parts are the source of truth for every path in .ship/manifest.json.
If a local part is missing or corrupt (partial zip, old overlay), fetch it from
GitHub raw so an update can never leave web_server.py empty.
"""
from __future__ import annotations

import base64
import hashlib
import json
import py_compile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

GITHUB_RAW_MAIN = "https://raw.githubusercontent.com/knull66/Vibesbot/main"


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch(url: str, timeout: int = 30) -> Optional[bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def _load_manifest(path: Path) -> List[dict]:
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return items if isinstance(items, list) else []


def _assemble(ship: Path, item: dict, fetch: bool, base_url: str) -> Optional[bytes]:
    digest = str(item.get("sha256") or "")
    buf = bytearray()
    for name in item.get("parts") or []:
        part_path = ship / str(name)
        raw: Optional[bytes] = None
        if part_path.is_file():
            try:
                raw = part_path.read_bytes()
            except OSError:
                raw = None
        if raw is not None:
            try:
                buf.extend(base64.b64decode(raw.strip(), validate=False))
                continue
            except ValueError:
                raw = None
        if not fetch:
            return None
        remote = _fetch(f"{base_url}/.ship/{name}")
        if remote is None:
            return None
        try:
            chunk = base64.b64decode(remote.strip(), validate=False)
        except ValueError:
            return None
        ship.mkdir(parents=True, exist_ok=True)
        try:
            part_path.write_bytes(remote if remote.endswith(b"\n") else remote + b"\n")
        except OSError:
            pass
        buf.extend(chunk)
    data = bytes(buf)
    if _sha256(data) != digest:
        if not fetch:
            return None
        # Local parts were stale as a set: re-pull every part once.
        buf = bytearray()
        for name in item.get("parts") or []:
            remote = _fetch(f"{base_url}/.ship/{name}")
            if remote is None:
                return None
            try:
                buf.extend(base64.b64decode(remote.strip(), validate=False))
            except ValueError:
                return None
            try:
                (ship / str(name)).write_bytes(remote if remote.endswith(b"\n") else remote + b"\n")
            except OSError:
                pass
        data = bytes(buf)
        if _sha256(data) != digest:
            return None
    return data


def inflate_ship(
    root: Optional[Path] = None,
    fetch: bool = False,
    base_url: str = GITHUB_RAW_MAIN,
) -> List[str]:
    """Restore manifest paths that are missing, empty, or hash-mismatched.

    fetch=True downloads missing/corrupt parts (and a fresh manifest when the
    local one is unreadable) from GitHub raw main.
    """
    base = Path(root) if root else _root()
    ship = base / ".ship"
    manifest_path = ship / "manifest.json"
    items = _load_manifest(manifest_path) if manifest_path.is_file() else []
    if not items and fetch:
        remote = _fetch(f"{base_url}/.ship/manifest.json")
        if remote:
            ship.mkdir(parents=True, exist_ok=True)
            try:
                manifest_path.write_bytes(remote)
            except OSError:
                pass
            items = _load_manifest(manifest_path)
    if not items:
        return []
    restored: List[str] = []
    for item in items:
        rel = str(item.get("path") or "")
        digest = str(item.get("sha256") or "")
        if not rel or not digest or not item.get("parts"):
            continue
        target = base / rel
        if target.is_file() and target.stat().st_size > 0:
            try:
                if _sha256(target.read_bytes()) == digest:
                    continue
            except OSError:
                pass
        data = _assemble(ship, item, fetch, base_url)
        if data is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored.append(rel)
    return restored


def verify_ship(root: Optional[Path] = None) -> Dict[str, str]:
    """Return {path: problem} for manifest entries that are not healthy on disk."""
    base = Path(root) if root else _root()
    manifest_path = base / ".ship" / "manifest.json"
    problems: Dict[str, str] = {}
    if not manifest_path.is_file():
        return problems
    for item in _load_manifest(manifest_path):
        rel = str(item.get("path") or "")
        digest = str(item.get("sha256") or "")
        if not rel or not digest:
            continue
        target = base / rel
        if not target.is_file():
            problems[rel] = "missing"
            continue
        try:
            data = target.read_bytes()
        except OSError as exc:
            problems[rel] = f"unreadable: {exc}"
            continue
        if not data:
            problems[rel] = "empty"
            continue
        if _sha256(data) != digest:
            problems[rel] = "hash mismatch"
            continue
        if target.suffix == ".py":
            try:
                py_compile.compile(str(target), doraise=True)
            except py_compile.PyCompileError as exc:
                problems[rel] = f"syntax: {exc.msg}"
    return problems
