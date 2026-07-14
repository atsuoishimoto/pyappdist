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
import subprocess
import sys

from .errors import BuildError
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


def windows_abspath(path: os.PathLike | str, python_exe: os.PathLike | str) -> str:
    """Absolute Windows-side path of directory ``path``.

    On a Windows host this is a plain abspath. On a Linux (WSL) host, run the
    target runtime's ``python.exe`` with ``cwd=path`` and print its cwd: interop
    converts the cwd, so the result is exactly the path other target tools see
    when launched the same way (no wslpath involved).
    """
    if sys.platform == "win32":
        return os.path.abspath(os.fspath(path))
    proc = subprocess.run(
        [os.fspath(python_exe), "-c", "import os; print(os.getcwd())"],
        cwd=os.fspath(path), capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise BuildError(
            f"could not resolve the Windows path of {os.fspath(path)}:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def extended_length_path(win_path: str) -> str:
    """Extended-length (``\\\\?\\``) form of an absolute Windows path.

    The prefix lifts the MAX_PATH (260 char) limit for tools that opt in via
    plain Win32 path handling, e.g. WiX's cabinet builder.
    """
    if win_path.startswith("\\\\?\\"):
        return win_path
    if win_path.startswith("\\\\"):
        return "\\\\?\\UNC" + win_path[1:]
    return "\\\\?\\" + win_path
