"""Code-signing hook (Phase 5).

The MVP ships unsigned. If the environment variable ``PYAPPDIST_SIGN_CMD`` is set,
that command is run against each artifact (launcher.exe / MSI). ``{file}`` is
replaced with the target file path (appended at the end if absent). Certificates
are assumed to be passed to the command via CI secrets etc.; pyappdist does not
handle certificates.

The command runs through the platform's shell (cmd.exe on Windows). You can write
the same command line you would normally type in a terminal, and the shell
interprets Windows backslash paths and environment variables as-is. When it
contains ``{file}``, quote it like ``"{file}"`` to guard against spaces.

Example: PYAPPDIST_SIGN_CMD='signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"'
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import BuildError

_ENV = "PYAPPDIST_SIGN_CMD"


def sign_artifact(path: Path, *, log=print) -> bool:
    """Sign the artifact. If no sign command is set, do nothing and return False."""
    template = os.environ.get(_ENV)
    if not template:
        log(f"sign: skipped ({_ENV} unset): {path.name}")
        return False
    if "{file}" in template:
        command = template.replace("{file}", str(path))
    else:
        command = f'{template} "{path}"'
    log(f"sign: {path.name}")
    proc = subprocess.run(command, shell=True, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise BuildError(f"signing failed ({path.name}):\n{proc.stdout}\n{proc.stderr}")
    return True
