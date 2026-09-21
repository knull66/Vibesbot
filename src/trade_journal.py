"""Append-only local journal of SIM/REAL Wallet trades."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .secret_box import chmod_private
from .user_settings import default_settings_path


def journal_path(settings_file: Optional[Path] = None) -> Path:
    folder = (settings_file or default_settings_path()).parent
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "trade_journal.jsonl"


def append_trade(entry: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    row = dict(entry or {})
    row.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    target = path or journal_path()
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")
    chmod_private(target)
    return row


def read_trades(limit: int = 100, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    target = path or journal_path()
    if not target.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    except OSError:
        return []
    if limit and limit > 0:
        return rows[-limit:]
    return rows
