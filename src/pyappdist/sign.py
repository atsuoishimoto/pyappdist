"""Code-signing hook (Phase 5).

Signing is opt-in. The command to run against each artifact (launcher.exe / MSI) is
resolved by the caller and passed to :func:`sign_artifact`; ``{file}`` is replaced with
the target file path (appended at the end if absent). Certificates are assumed to be
provided to the command out of band (the Windows certificate store, a token, or CI
secrets); pyappdist does not handle certificates.

For MSI the command is resolved by :func:`resolve_msi_sign_command` from the target's
``code-sign`` / ``code-sign-command`` config, with the environment variable
``PYAPPDIST_SIGN_CMD`` taking precedence and a built-in ``signtool`` default as the
fallback. MSIX and the macOS ``.dmg`` keep the legacy behaviour: signed only when
``PYAPPDIST_SIGN_CMD`` is set (:func:`env_sign_command`).

The command runs through the platform's shell (cmd.exe on Windows). You can write the
same command line you would normally type in a terminal, and the shell interprets
Windows backslash paths and environment variables as-is. When it contains ``{file}``,
quote it like ``"{file}"`` to guard against spaces.

Example: PYAPPDIST_SIGN_CMD='signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"'
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import WixConfig
from .errors import BuildError

_ENV = "PYAPPDIST_SIGN_CMD"

# Used when an MSI target sets ``code-sign = true`` but provides no command (and no env
# override): sign with signtool, auto-selecting the best certificate from the store.
DEFAULT_MSI_SIGN_CMD = (
    'signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com '
    '/td SHA256 /a "{file}"'
)


def env_sign_command() -> str | None:
    """The legacy command from ``PYAPPDIST_SIGN_CMD`` (None if unset).

    Used for MSIX and the macOS ``.dmg`` extra signing, which sign only when the
    environment variable is set.
    """
    return os.environ.get(_ENV)


def resolve_msi_sign_command(wix: WixConfig) -> str | None:
    """Resolve the MSI signing command, or None when signing is off.

    Returns None unless ``code-sign`` is set. When on, precedence is
    ``PYAPPDIST_SIGN_CMD`` (env) > ``code-sign-command`` (config) > the signtool default.
    """
    if not wix.code_sign:
        return None
    return os.environ.get(_ENV) or wix.code_sign_command or DEFAULT_MSI_SIGN_CMD


def sign_artifact(path: Path, command: str | None, *, log=print) -> bool:
    """Sign the artifact with ``command``. If ``command`` is empty, do nothing and return False."""
    if not command:
        log(f"sign: skipped (no sign command): {path.name}")
        return False
    if "{file}" in command:
        command = command.replace("{file}", str(path))
    else:
        command = f'{command} "{path}"'
    log(f"sign: {path.name}")
    proc = subprocess.run(command, shell=True, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise BuildError(f"signing failed ({path.name}):\n{proc.stdout}\n{proc.stderr}")
    return True
