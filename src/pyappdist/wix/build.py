"""Build an MSI from the generated .wxs via ``wix build`` (Phase 5).

WiX is a dotnet global tool (``dotnet tool install --global wix``).
When targeting Windows from WSL, use wix.exe plus Windows paths.
File@Source is relative to the image root, so pass ``-b <image>`` as the bind path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .._hostexec import is_cross_windows, target_path
from ..config import Config
from ..errors import BuildError


def build_msi(config: Config, image_dir: Path, wxs_path: Path, out_msi: Path, *, log=print) -> Path | None:
    """Generate an MSI via ``wix build``. Returns None for non-Windows targets."""
    target = config.target
    if target.os != "windows":
        log("msi: skipping because the target is not Windows")
        return None

    wix = _find_wix(target)
    out_msi.parent.mkdir(parents=True, exist_ok=True)
    log(f"msi: wix build -> {out_msi}")
    cmd = [
        wix, "build",
        "-arch", target.wix_arch,  # make it a 64-bit package so it installs into C:\Program Files
        target_path(target, wxs_path),
        "-b", target_path(target, image_dir),
        "-o", target_path(target, out_msi),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0 or not out_msi.exists():
        raise BuildError(
            f"wix build failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
    return out_msi


def _find_wix(target) -> str:
    override = os.environ.get("PYAPPDIST_WIX")
    if override:
        return override
    name = "wix.exe" if is_cross_windows(target) else "wix"
    found = shutil.which(name)
    if found:
        return found
    raise BuildError(
        "wix not found. Run `dotnet tool install --global wix`, or "
        "specify the absolute path to wix via PYAPPDIST_WIX."
    )
