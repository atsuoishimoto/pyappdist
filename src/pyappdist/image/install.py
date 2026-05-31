"""Install all wheels in the wheelhouse into the runtime's site-packages.

No venv is used; the image's runtime python is used directly to run
``python -m pip install`` (uv is not used: to avoid uv's cache/index behavior and
ensure the built wheels are the ones actually used).

Since the wheelhouse holds only the app + its dependencies, dist_name is not
resolved and **all wheels are passed straight to pip**. ``--no-index`` prevents
external lookups. The cwd is set to the wheelhouse so relative specs (wheel names
only) suffice, which means wslpath is not needed even for WSL->Windows (interop
converts the cwd to the Windows side). ``--target`` is also not used; wheels are
installed normally into the runtime's own site-packages.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..errors import BuildError
from .layout import ImageLayout


def install_app(layout: ImageLayout, wheelhouse: Path, *, log=print) -> None:
    wheels = sorted(p.name for p in wheelhouse.glob("*.whl"))
    if not wheels:
        raise BuildError(f"no wheels in wheelhouse: {wheelhouse}")
    log(f"image: installing {len(wheels)} wheels -> {layout.site_packages}")
    cmd = [str(layout.python_exe), "-m", "pip", "install", "--no-index", *wheels]
    # cwd=wheelhouse, so wheel names alone suffice (WSL interop converts cwd to the Windows side).
    proc = subprocess.run(
        cmd, cwd=str(wheelhouse), capture_output=True, text=True, errors="replace"
    )
    if proc.returncode != 0:
        raise BuildError(
            f"install failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
