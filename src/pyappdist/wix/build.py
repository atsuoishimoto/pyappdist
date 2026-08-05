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

from .._hostexec import extended_length_path, target_relpath, windows_abspath
from ..config import Config
from ..errors import BuildError
from ..image import ImageLayout
from .generate import ICON_STAGED_NAME, LICENSE_STAGED_NAME, product_icon


def build_msi(config: Config, image_dir: Path, wxs_path: Path, out_msi: Path, *, log=print) -> Path | None:
    """Generate an MSI via ``wix build``. Returns None for non-Windows targets.

    Config loading rejects ``format = "msi"`` on a non-Windows platform, so the skip
    is a guard for direct API use rather than something the CLI can reach.
    """
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

    # The only installer UI is the optional license dialog (WixUI_Minimal), which lives
    # in the UI extension. Scope ("user"/"machine") has no dialogs.
    needs_ui = bool(config.wix.license)

    # Inputs that live outside the build tree (the license RTF, the product icon)
    # are staged next to the .wxs — i.e. into the per-target build dir, never into
    # cwd=base, which is the user's project directory and must stay free of build
    # artifacts. The .wxs references both by bare name, so a bind path for that
    # directory (added below) is what lets WiX find them.
    staged_dir = wxs_path.parent
    staged = False

    if config.wix.license:
        license_src = (config.project_dir / config.wix.license).resolve()
        if not license_src.is_file():
            raise BuildError(
                f"license file not found ([tool.pyappdist.wix].license): {license_src}"
            )
        shutil.copy2(license_src, staged_dir / LICENSE_STAGED_NAME)
        staged = True

    icon_rel = product_icon(config)
    if icon_rel:
        icon_src = (config.project_dir / icon_rel).resolve()
        if not icon_src.is_file():
            raise BuildError(f"product icon not found (launcher icon.windows): {icon_src}")
        shutil.copy2(icon_src, staged_dir / ICON_STAGED_NAME)
        staged = True

    # The bind path is passed as an extended-length (\\?\) absolute path, not
    # relative: WiX's cabinet builder cannot open source files whose absolute
    # path exceeds MAX_PATH (wixtoolset/issues#9115) and dies with a broken-pipe
    # IOException. Deep site-packages trees (e.g. PyTorch's dist-info licenses)
    # exceed the limit even from a shallow project directory.
    layout = ImageLayout(image_dir=image_dir, target=target, minor=config.python_minor)
    bind_path = extended_length_path(windows_abspath(image_dir, layout.python_exe))

    cmd = [
        wix, "build",
        "-arch", target.wix_arch,  # make it a 64-bit package so it installs into C:\Program Files
    ]
    if needs_ui:
        cmd += ["-ext", "WixToolset.UI.wixext"]
    cmd += [
        target_relpath(target, wxs_path, base),
        "-b", bind_path,
    ]
    if staged:
        # Second bind path: where the staged license/icon were copied. Relative to
        # cwd like the other arguments — only the image tree needs the \\?\ form.
        cmd += ["-b", target_relpath(target, staged_dir, base)]
    cmd += ["-o", target_relpath(target, out_msi, base)]
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
    override = os.environ.get("PYAPPDIST_WIN_WIX")
    if override:
        return override
    found = shutil.which("wix.exe")
    if found:
        return found
    raise BuildError(
        "wix not found. Run `dotnet tool install --global wix`, or "
        "specify the absolute path to wix via PYAPPDIST_WIN_WIX."
    )
