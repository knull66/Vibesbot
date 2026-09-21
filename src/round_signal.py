"""Round-level signal: indicators + tape, never a naked 50/50 coin flip."""
from typing import Dict, Optional, Tuple

MIN_CONFIRM_MOVE = 12.0


def tape_vote(flow_imbalance: float, book_imbalance: float = 0.0) -> int:
    """+1 buy pressure, -1 sell pressure, 0 mixed. Uses Binance spot tape/book."""
    score = 0
    if flow_imbalance >= 0.12:
        score += 1
    elif flow_imbalance <= -0.12:
        score -= 1
    if book_imbalance >= 0.15:
        score += 1
    elif book_imbalance <= -0.15:
        score -= 1
    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0


def combine_indicator_votes(
    rsi_signal: int,
    macd_signal: int,
    bb_signal: int,
    mom_signal: int,
    tape_signal: int = 0,
    weights: Optional[Dict[str, int]] = None,
) -> Tuple[str, float, str]:
    """Only a clear majority bets. Weak/coin-flip returns WAIT."""
    w = weights or {}
    rsi_w = max(0, int(w.get("rsi", 2)))
    macd_w = max(0, int(w.get("macd", 2)))
    bb_w = max(0, int(w.get("bollinger", 1)))
    mom_w = max(0, int(w.get("momentum", 1)))
    total = (
        int(rsi_signal) * rsi_w
        + int(macd_signal) * macd_w
        + int(bb_signal) * bb_w
        + int(mom_signal) * mom_w
        + int(tape_signal)
    )
    if total >= 3:
        confidence = 0.55 + min(0.15, abs(total) * 0.02)
        label = "Multi-strategy (RSI+MACD+BB+tape)" if tape_signal else "Multi-strategy (RSI+MACD+BB)"
        return "UP", min(confidence, 0.70), label
    if total <= -3:
        confidence = 0.55 + min(0.15, abs(total) * 0.02)
        label = "Multi-strategy (RSI+MACD+BB+tape)" if tape_signal else "Multi-strategy (RSI+MACD+BB)"
        return "DOWN", min(confidence, 0.70), label
    return "WAIT", 0.50, "No edge — waiting for a cleaner setup"


def crowd_agrees(signal: str, book: Dict[str, float]) -> bool:
    """True when our side is not fighting a decided Binance book."""
    side = str(signal or "").upper()
    up = float(book.get("up") or 0.5)
    down = float(book.get("down") or 0.5)
    if side == "UP":
        return up >= down
    if side == "DOWN":
        return down >= up
    return False


def price_confirms(
    signal: str,
    current: float,
    beat: float,
    min_move: float = MIN_CONFIRM_MOVE,
) -> Tuple[bool, str]:
    """50/50 with no move vs Price to Beat is a coin flip. Join a move that already started."""
    side = str(signal or "").upper()
    try:
        current_px = float(current)
        beat_px = float(beat)
    except (TypeError, ValueError):
        return False, "no Price to Beat yet"
    if current_px <= 0 or beat_px <= 0:
        return False, "no Price to Beat yet"
    delta = current_px - beat_px
    if side == "UP":
        if delta >= min_move:
            return True, f"price {delta:+.2f} vs beat"
        return False, f"UP needs BTC above beat by ${min_move:.0f}+ (now {delta:+.2f})"
    if side == "DOWN":
        if delta <= -min_move:
            return True, f"price {delta:+.2f} vs beat"
        return False, f"DOWN needs BTC below beat by ${min_move:.0f}+ (now {delta:+.2f})"
    return False, "no signal"
