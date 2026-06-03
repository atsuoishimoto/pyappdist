"""Execution helpers that absorb host/target differences.

When handling a Windows target from WSL (a Linux host), Windows tools (uv.exe,
cl.exe, wix.exe, ...) are invoked through the WSL/Windows interop bridge. Paths
are passed *relative* to the working directory: interop converts the cwd to the
Windows side, so a relative argument resolves correctly even cross-OS, and no
explicit ``wslpath`` conversion is needed. Inputs that live outside the working
tree (e.g. bundled ``launcher.c`` or the user's icon) are staged into the build
directory by the caller before the tool runs.
"""

from __future__ import annotations

import os
import sys

from .targets import Target


def target_relpath(target: Target, path: os.PathLike | str, start: os.PathLike | str) -> str:
    """Path (relative to ``start``) to pass to a target tool run with ``cwd=start``.

    The tool is launched with ``cwd=start``; WSL interop converts that cwd to the
    Windows side, so a relative path resolves correctly even for a Linux host ->
    Windows target. Separators are normalized to the target OS.
    """
    rel = os.path.relpath(os.fspath(path), os.fspath(start))
    if target.os == "windows":
        return rel.replace("/", "\\")
    return rel
