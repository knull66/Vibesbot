"""Inflated from src/_srv parts (GitHub MCP size limit)."""
from pathlib import Path


def _inflate_from_parts(prefix: str) -> None:
    root = Path(__file__).resolve().parent / "_srv"
    parts = sorted(root.glob(f"{prefix}_*.txt"), key=lambda p: p.name)
    if not parts:
        raise RuntimeError(f"missing _srv parts for {prefix}")
    src = "".join(p.read_text(encoding="utf-8") for p in parts)
    exec(compile(src, f"<{prefix}>", "exec"), globals())


_inflate_from_parts("web_server")
