"""Generate .pyc files for the whole image runtime at build time."""

from __future__ import annotations

import subprocess

from .._hostexec import target_relpath
from ..errors import BuildError
from .layout import ImageLayout


def compile_site_packages(layout: ImageLayout, *, log=print) -> None:
    """Run compileall over the whole runtime with the runtime's python.

    The target OS's python must be run (for a Linux host -> Windows target,
    python.exe is run via WSL interop). The python dir is passed relative to the
    image dir, which is set as the cwd, so no path conversion is needed -- and
    because the path is relative, the source filename baked into each .pyc is
    relative to the image (no developer/build-machine absolute path leaks in).

    The whole runtime (stdlib + site-packages) is compiled, not just
    site-packages: python-build-standalone's install_only_stripped flavor ships
    almost no stdlib .pyc, so without this the stdlib would be recompiled lazily
    on every cold start (and not at all on a read-only/perMachine install). -f
    forces a rebuild so the few startup .pyc that *are* shipped -- which carry
    the upstream build path (/build/out/...) -- get rewritten with a clean
    relative path.

    compileall runs with -q, so only its error messages are streamed through
    (the per-file progress listing is suppressed). A non-zero exit status is
    expected for some packages (e.g. PySide6 ships .py files that fail to
    compile); the other files are still compiled, so we only warn and continue
    rather than failing the build. Raises BuildError only when python itself
    cannot be run.
    """
    target = layout.target
    log("image: compileall")
    cmd = [
        str(layout.python_exe), "-m", "compileall", "-q", "-f",
        target_relpath(target, layout.python_dir, layout.image_dir),
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
