"""Execution helpers that absorb host/target differences.

When handling a Windows target from WSL (a Linux host), Windows tools (uv.exe)
must be invoked and paths converted to Windows form (wslpath -w).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .targets import Target


def is_cross_windows(target: Target) -> bool:
    """Handling a Windows target from a Linux host (requires the .exe bridge)."""
    return target.os == "windows" and sys.platform != "win32"


def target_path(target: Target, path: Path | str) -> str:
    """Path string to pass to a target tool."""
    p = Path(path)
    if is_cross_windows(target):
        out = subprocess.run(
            ["wslpath", "-w", str(p)], capture_output=True, text=True,
            errors="replace", check=True,
        )
        return out.stdout.strip()
    return str(p)
