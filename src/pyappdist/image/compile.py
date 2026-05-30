"""Generate .pyc files for the image's site-packages at build time."""

from __future__ import annotations

import subprocess

from .._hostexec import target_path
from ..errors import BuildError
from .layout import ImageLayout


def compile_site_packages(layout: ImageLayout, *, log=print) -> None:
    """Run compileall with the runtime's python.

    The target OS's python must be run (for a Linux host -> Windows target,
    python.exe is run via WSL interop and paths are converted to Windows form).
    Raises BuildError in environments where it cannot be run.
    """
    target = layout.target
    log("image: compileall")
    cmd = [
        str(layout.python_exe), "-m", "compileall", "-q",
        target_path(target, layout.site_packages),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as e:
        raise BuildError(
            f"cannot run compileall (unable to run {target.name}'s python): {e}"
        ) from e
    if proc.returncode != 0:
        raise BuildError(f"compileall failed ({proc.returncode}):\n{proc.stderr.strip()}")
