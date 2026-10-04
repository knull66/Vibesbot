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


def summarize_trades(trades: List[Dict[str, Any]], live: Optional[bool] = None) -> Dict[str, Any]:
    """Wins / losses / PnL from journal rows. live=True keeps REAL only."""
    wins = 0
    losses = 0
    pnl = 0.0
    streak = 0
    best = 0
    worst = 0
    for row in trades or []:
        if not isinstance(row, dict):
            continue
        if live is True and not row.get("live"):
            continue
        if live is False and row.get("live"):
            continue
        result = str(row.get("result") or "").upper()
        try:
            change = float(row.get("pnl") or 0)
        except (TypeError, ValueError):
            change = 0.0
        pnl += change
        if result == "WIN":
            wins += 1
            streak = streak + 1 if streak >= 0 else 1
        elif result == "LOSS":
            losses += 1
            streak = streak - 1 if streak <= 0 else -1
        else:
            continue
        best = max(best, streak)
        worst = min(worst, streak)
    total = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "trades": total,
        "pnl": pnl,
        "winrate": (wins / total * 100.0) if total else 0.0,
        "streak": streak,
        "best_streak": best,
        "worst_streak": worst,
    }


def clear_trades(live: Optional[bool] = None, path: Optional[Path] = None) -> int:
    """Drop journal rows. live=True clears REAL, False clears SIM, None clears all."""
    target = path or journal_path()
    rows = read_trades(0, target)
    if live is None:
        kept: List[Dict[str, Any]] = []
    elif live is True:
        kept = [row for row in rows if not row.get("live")]
    else:
        kept = [row for row in rows if row.get("live")]
    removed = len(rows) - len(kept)
    with open(target, "w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row, default=str) + "\n")
    if target.exists():
        chmod_private(target)
    return removed


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
