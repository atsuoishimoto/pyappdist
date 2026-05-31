"""Determining the dependency list (package manager lockfile -> requirements.txt).

Dependencies are pinned **based on the project's lockfile**. Using the manager
the developer uses (uv / poetry / pipenv / PDM), ``requirements.txt`` is exported
from the lock, and later ``pip wheel -r requirements.txt`` is run with the target
runtime's python. The export emits production dependencies only (dev excluded),
with cross markers and hashes.

Resolution:
* An explicit ``[tool.pyappdist].manager`` setting takes top priority (if
  ``requirements.txt`` is specified, the requirements.txt directly under the
  project is used as-is).
* If unset, lockfiles are searched in the order uv.lock -> poetry.lock ->
  Pipfile.lock -> pdm.lock, and the first tool found is used.
* If undeterminable, a warning is emitted and it operates in ``requirements.txt``
  mode (``BuildError`` if absent).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import Config
from .errors import BuildError

# tool name -> lockfile name (auto-detect search order).
_LOCKFILES: tuple[tuple[str, str], ...] = (
    ("uv", "uv.lock"),
    ("poetry", "poetry.lock"),
    ("pipenv", "Pipfile.lock"),
    ("pdm", "pdm.lock"),
)

# tool name -> export command (run with cwd=project_dir, stdout becomes requirements.txt).
# All emit production dependencies only (dev excluded), with hashes.
_EXPORT_CMDS: dict[str, list[str]] = {
    "uv": ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt"],
    "poetry": ["poetry", "export", "-f", "requirements.txt", "--without", "dev"],
    "pipenv": ["pipenv", "requirements", "--hash"],
    "pdm": ["pdm", "export", "-f", "requirements", "--prod"],
}


def _auto_detect(project_dir: Path) -> str | None:
    """Detect the manager from the presence of a lockfile (None if absent)."""
    for manager, lockfile in _LOCKFILES:
        if (project_dir / lockfile).is_file():
            return manager
    return None


def _warn(log, message: str) -> None:
    log(f"warning: {message}")


def resolve_manager(project_dir: Path, override: str | None, *, log=print) -> str:
    """Determine the manager to use (or "requirements.txt")."""
    if override:
        return override
    detected = _auto_detect(project_dir)
    if detected:
        return detected
    _warn(
        log,
        "no lockfile (uv.lock etc.) and no [tool.pyappdist].manager setting. "
        "Falling back to requirements.txt",
    )
    return "requirements.txt"


def resolve_requirements(config: Config, wheelhouse: Path, *, log=print) -> Path:
    """Prepare the pinned dependency list at ``wheelhouse/requirements.txt`` and return its path."""
    manager = resolve_manager(config.project_dir, config.manager, log=log)
    out = wheelhouse / "requirements.txt"

    if manager == "requirements.txt":
        src = config.project_dir / "requirements.txt"
        if not src.is_file():
            raise BuildError(
                f"requirements.txt is missing: {src}"
                " (provide a manager lockfile or place a requirements.txt)"
            )
        log(f"deps: using requirements.txt ({src})")
        out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return out

    cmd = _EXPORT_CMDS[manager]
    log(f"deps: exporting requirements.txt from {manager} lock")
    proc = subprocess.run(
        cmd,
        cwd=str(config.project_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise BuildError(
            f"requirements.txt export failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.strip()}"
        )
    out.write_text(proc.stdout, encoding="utf-8")
    return out
