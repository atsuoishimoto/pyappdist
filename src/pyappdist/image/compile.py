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

    compileall's output is streamed through as-is. A non-zero exit status is
    expected for some packages (e.g. PySide6 ships .py files that fail to
    compile); the other files are still compiled, so we only warn and continue
    rather than failing the build. Raises BuildError only when python itself
    cannot be run.
    """
    target = layout.target
    log("image: compileall")
    cmd = [
        str(layout.python_exe), "-m", "compileall",
        target_relpath(target, layout.site_packages, layout.image_dir),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(layout.image_dir))
    except OSError as e:
        raise BuildError(
            f"cannot run compileall (unable to run {target.name}'s python): {e}"
        ) from e
    if proc.returncode != 0:
        log(
            f"image: compileall reported errors (status {proc.returncode}); "
            "continuing (some files could not be compiled)"
        )
