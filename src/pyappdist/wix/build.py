"""Build an MSI from the generated .wxs via ``wix build`` (Phase 5).

WiX is a dotnet global tool (``dotnet tool install --global wix``).
When targeting Windows from WSL, use wix.exe and pass paths relative to the
appdist tree (run from a common ancestor; interop converts the cwd).
File@Source is relative to the image root, so pass ``-b <image>`` as the bind path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .._hostexec import is_cross_windows, target_relpath
from ..config import Config
from ..errors import BuildError
from .generate import LICENSE_STAGED_NAME


def build_msi(config: Config, image_dir: Path, wxs_path: Path, out_msi: Path, *, log=print) -> Path | None:
    """Generate an MSI via ``wix build``. Returns None for non-Windows targets."""
    target = config.target
    if target.os != "windows":
        log("msi: skipping because the target is not Windows")
        return None

    wix = _find_wix(target)
    out_msi.parent.mkdir(parents=True, exist_ok=True)
    log(f"msi: wix build -> {out_msi}")
    # All inputs/outputs live under the appdist tree; run from their common
    # ancestor and pass relative paths so no wslpath conversion is needed.
    base = Path(os.path.commonpath([str(wxs_path), str(image_dir), str(out_msi)]))

    # Any installer UI (the WixUI_Advanced scope dialogs and/or a license) lives in the
    # UI extension. perUserOrMachine always has UI; perMachine only when a license is set.
    needs_ui = config.wix.scope != "perMachine" or bool(config.wix.license)

    if config.wix.license:
        license_src = (config.project_dir / config.wix.license).resolve()
        if not license_src.is_file():
            raise BuildError(
                f"license file not found ([tool.pyappdist.wix].license): {license_src}"
            )
        # WixUILicenseRtf references this by name, resolved relative to cwd=base.
        shutil.copy2(license_src, base / LICENSE_STAGED_NAME)

    cmd = [
        wix, "build",
        "-arch", target.wix_arch,  # make it a 64-bit package so it installs into C:\Program Files
    ]
    if needs_ui:
        cmd += ["-ext", "WixToolset.UI.wixext"]
    cmd += [
        target_relpath(target, wxs_path, base),
        "-b", target_relpath(target, image_dir, base),
        "-o", target_relpath(target, out_msi, base),
    ]
    proc = subprocess.run(cmd, cwd=str(base), capture_output=True, text=True, errors="replace")
    if proc.returncode != 0 or not out_msi.exists():
        hint = ""
        if needs_ui and "WixToolset.UI" in (proc.stdout + proc.stderr):
            hint = (
                "\nhint: install the WiX UI extension once: "
                "wix extension add -g WixToolset.UI.wixext/5.0.2"
            )
        raise BuildError(
            f"wix build failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}{hint}"
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
