"""Generate .pyc files for the image's site-packages at build time."""

from __future__ import annotations

import subprocess

from .._hostexec import target_relpath
from ..errors import BuildError
from .layout import ImageLayout


def compile_site_packages(layout: ImageLayout, *, log=print) -> None:
    """Run compileall with the runtime's python.

    The target OS's python must be run (for a Linux host -> Windows target,
    python.exe is run via WSL interop). site-packages is passed relative to the
    image dir, which is set as the cwd, so no path conversion is needed.
    Raises BuildError in environments where it cannot be run.
    """
    target = layout.target
    log("image: compileall")
    cmd = [
        str(layout.python_exe), "-m", "compileall", "-q",
        target_relpath(target, layout.site_packages, layout.image_dir),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(layout.image_dir), capture_output=True, text=True, errors="replace"
        )
    except OSError as e:
        raise BuildError(
            f"cannot run compileall (unable to run {target.name}'s python): {e}"
        ) from e
    if proc.returncode != 0:
        raise BuildError(f"compileall failed ({proc.returncode}):\n{proc.stderr.strip()}")
