"""Round-level signal: indicators + BTC tape, skip coin-flips."""
from typing import Dict, Tuple


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
) -> Tuple[str, float, str]:
    """Only a clear majority bets. Weak/coin-flip returns WAIT."""
    total = (
        int(rsi_signal) * 2
        + int(macd_signal) * 2
        + int(bb_signal)
        + int(mom_signal)
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
