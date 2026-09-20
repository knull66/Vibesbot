"""Mac process helpers: free port 8080 and relaunch the .app."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional


def pids_on_port(port: int) -> List[int]:
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []
    pids = []
    for line in out.split():
        if line.isdigit():
            pids.append(int(line))
    return pids


def free_listen_port(port: int = 8080, wait: float = 0.45) -> List[int]:
    """Kill leftover listeners so a new engine can bind the port."""
    me = os.getpid()
    killed: List[int] = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids_on_port(port):
            if pid in (0, 1, me):
                continue
            try:
                os.kill(pid, sig)
                killed.append(pid)
            except ProcessLookupError:
                continue
            except PermissionError:
                subprocess.call(
                    ["kill", "-9", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                killed.append(pid)
        time.sleep(wait if sig == signal.SIGTERM else 0.2)
    return killed


def find_app_bundle() -> Optional[Path]:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name.endswith(".app"):
            return parent
    for candidate in (
        Path("/Applications/Vibesbot.app"),
        Path.home() / "Applications" / "Vibesbot.app",
        Path.home() / "Downloads" / "Vibesbot.app",
        Path.home() / "Downloads" / "Vibesbot" / "dist" / "Vibesbot.app",
    ):
        if candidate.exists():
            return candidate
    return None


def relaunch_app(delay: float = 1.2) -> None:
    """Return from the HTTP handler first, then replace this process with a new app."""

    def _go():
        time.sleep(delay)
        app = find_app_bundle()
        free_listen_port(8080)
        if app:
            subprocess.Popen(["open", "-n", str(app)])
        os._exit(0)

    threading.Thread(target=_go, daemon=True).start()
