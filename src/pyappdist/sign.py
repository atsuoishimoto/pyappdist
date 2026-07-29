"""Code-signing hook (Phase 5).

Signing is opt-in and configured the same way for every format that has a signable
artifact: the target's ``code-sign`` (bool) / ``code-sign-command`` keys, overridable
from the ``pyappdist build`` command line with ``--code-sign`` / ``--no-code-sign``.
:func:`resolve_sign_command` turns that into the command to run against each artifact
(launcher ``.exe`` / ``.msi`` / ``.msix`` / ``.dmg``); ``{file}`` is replaced with the
target file path (appended at the end if absent). Certificates are assumed to be
provided to the command out of band (the Windows certificate store, a token, or CI
secrets); pyappdist does not handle certificates.

When signing is enabled, the command is resolved per target OS:

- Windows targets (``msi``/``msix``/``image``): ``PYAPPDIST_WIN_SIGN_CMD`` (env) >
  ``code-sign-command`` (config) > a built-in ``signtool`` default.
- macOS ``dmg`` (the extra pass on the disk image, on top of the ``codesign``-based
  ``signing-identity`` flow): ``PYAPPDIST_MAC_SIGN_CMD`` (env) > ``code-sign-command``
  (config); there is no built-in default, so a missing command is a ``ConfigError``.

The environment variables only supply the *command*; they never turn signing on by
themselves. The retired ``PYAPPDIST_SIGN_CMD`` variable is ignored with a warning.

The command runs through the platform's shell (cmd.exe on Windows) with the
artifact's directory as the working directory, and ``{file}`` is replaced with the
artifact's *file name* (not its full path). Running from the artifact's directory
lets WSL interop convert the cwd to the Windows side, so the relative name resolves
correctly for ``signtool.exe`` in cross-builds (the same cwd + relative-path rule as
``_hostexec.py``). Because of that, any *other* path in the command (a ``.pfx``
certificate, an entitlements file, ...) must be absolute — a Windows-side absolute
path when cross-building from WSL. When the command contains ``{file}``, quote it
like ``"{file}"`` to guard against spaces.

Example: PYAPPDIST_WIN_SIGN_CMD='signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"'
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import BuildError, ConfigError

if TYPE_CHECKING:
    from .config import Config

# The command environment variable per target OS. Split by purpose: one project can
# build Windows and macOS targets from the same pyproject.toml, and a single ambient
# command (a signtool invocation, say) must never leak onto the other OS's artifacts.
_ENV_BY_OS = {"windows": "PYAPPDIST_WIN_SIGN_CMD", "macos": "PYAPPDIST_MAC_SIGN_CMD"}

# Retired: the pre-0.11 single variable that both enabled signing and supplied the
# command for MSIX/image/dmg. Ignored now, with a one-time warning pointing at the
# replacements.
_LEGACY_ENV = "PYAPPDIST_SIGN_CMD"
_legacy_warned = False

# Used when a Windows target enables signing but provides no command (and no env
# override): sign with signtool, auto-selecting the best certificate from the store.
DEFAULT_WIN_SIGN_CMD = (
    'signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com '
    '/td SHA256 /a "{file}"'
)


def _warn_legacy_env() -> None:
    global _legacy_warned
    if _legacy_warned or not os.environ.get(_LEGACY_ENV):
        return
    _legacy_warned = True
    print(
        f"warning: {_LEGACY_ENV} is no longer used and was ignored; set "
        f"{_ENV_BY_OS['windows']} or {_ENV_BY_OS['macos']} instead, and enable "
        "signing with the target's code-sign key or --code-sign",
        file=sys.stderr,
    )


def resolve_sign_command(config: Config, cli_override: bool | None) -> str | None:
    """Resolve the signing command for ``config``'s target, or None when signing is off.

    ``cli_override`` is the tri-state ``--code-sign`` / ``--no-code-sign`` value:
    ``True`` forces signing on, ``False`` forces it off, and ``None`` follows the
    target's ``code-sign`` key. When signing is on, the command comes from the
    OS-specific environment variable, then ``code-sign-command``, then (Windows only)
    the built-in signtool default.
    """
    _warn_legacy_env()
    enabled = config.code_sign if cli_override is None else cli_override
    if not enabled:
        return None
    command = os.environ.get(_ENV_BY_OS[config.target.os]) or config.code_sign_command
    if command:
        return command
    if config.target.os == "windows":
        return DEFAULT_WIN_SIGN_CMD
    raise ConfigError(
        f"signing is enabled for target {config.target_name!r} but no command is "
        f"configured: set {_ENV_BY_OS[config.target.os]} or the target's "
        "code-sign-command (there is no built-in default on macOS)"
    )


def sign_artifact(path: Path, command: str | None, *, log=print) -> bool:
    """Sign the artifact with ``command``. If ``command`` is empty, do nothing and return False."""
    if not command:
        log(f"sign: skipped (no sign command): {path.name}")
        return False
    # Run from the artifact's directory and pass only the file name: WSL interop
    # converts the cwd to the Windows side, so the relative name resolves for
    # signtool.exe in cross-builds too (see _hostexec.py). Works natively as well.
    if "{file}" in command:
        command = command.replace("{file}", path.name)
    else:
        command = f'{command} "{path.name}"'
    log(f"sign: {path.name}")
    proc = subprocess.run(
        command, shell=True, cwd=str(path.parent),
        capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0:
        raise BuildError(f"signing failed ({path.name}):\n{proc.stdout}\n{proc.stderr}")
    return True
