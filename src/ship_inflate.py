"""Rebuild oversized source files from .ship/*.b64 parts (GitHub MCP size limit)."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import List, Optional


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inflate_ship(root: Optional[Path] = None) -> List[str]:
    """Write files listed in .ship/manifest.json when missing or hash-mismatched."""
    base = Path(root) if root else _root()
    ship = base / ".ship"
    manifest_path = ship / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        items = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    restored: List[str] = []
    for item in items:
        rel = str(item.get("path") or "")
        digest = str(item.get("sha256") or "")
        parts = item.get("parts") or []
        if not rel or not digest or not parts:
            continue
        target = base / rel
        # Only fill missing files. Never overwrite a live install that already
        # has content — hash-mismatch rewrite undid GitHub Install updates when
        # .ship lagged behind VERSION / app.js.
        if target.is_file() and target.stat().st_size > 0:
            continue
        buf = bytearray()
        ok = True
        for name in parts:
            part_path = ship / str(name)
            if not part_path.is_file():
                ok = False
                break
            try:
                raw = part_path.read_text(encoding="ascii").strip()
                buf.extend(base64.b64decode(raw, validate=False))
            except (OSError, ValueError):
                ok = False
                break
        if not ok:
            continue
        data = bytes(buf)
        if _sha256(data) != digest:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored.append(rel)
    return restored
