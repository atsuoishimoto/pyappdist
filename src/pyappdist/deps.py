"""Determining the dependency list (package manager lockfile -> dependency file).

Dependencies are pinned **based on the project's lockfile**. Using the manager
the developer uses (uv / poetry / pipenv / PDM), a dependency file is exported
from the lock, and later ``pip wheel -r <file>`` is run with the target
runtime's python. The export emits production dependencies only (dev excluded),
with cross markers and hashes.

uv exports a PEP 751 ``pylock.toml``; the other managers export a
``requirements.txt``. The difference matters when the lock pins individual
packages to an alternative index (uv's ``[tool.uv.sources]`` +
``[[tool.uv.index]]`` with ``explicit = true`` — e.g. a CUDA build of PyTorch
from the PyTorch index): pip's index options are global, so requirements.txt
cannot express per-package index routing, while pylock.toml records each
package's exact artifact URLs and pip fetches them directly without consulting
any index.

Resolution:
* An explicit ``[tool.pyappdist].manager`` setting takes top priority (if
  ``requirements.txt`` is specified, the requirements.txt directly under the
  project is used as-is).
* If unset, lockfiles are searched in the order uv.lock -> poetry.lock ->
  Pipfile.lock -> pdm.lock, and the first tool found is used.
* If no manager is set and no lockfile is found, a checked-in ``requirements.txt``
  is used if present (with a warning); if that is absent too, the manager is
  undeterminable and a ``BuildError`` is raised.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import Config
from .errors import BuildError

# tool name -> lockfile name (auto-detect search order).
_LOCKFILES: tuple[tuple[str, str], ...] = (
    ("uv", "uv.lock"),
    ("poetry", "poetry.lock"),
    ("pipenv", "Pipfile.lock"),
    ("pdm", "pdm.lock"),
)

# tool name -> export command (run with cwd=project_dir, stdout becomes the dependency file).
# All emit production dependencies only (dev excluded), with hashes — the "nodev" default.
# uv exports PEP 751 pylock.toml (see the module docstring): it records each package's
# exact artifact URLs, so per-package index pins (e.g. a PyTorch CUDA index with
# ``explicit = true``) survive into the build — pip installs from the recorded URLs
# without consulting any index. requirements.txt cannot express per-package indexes.
_EXPORT_CMDS: dict[str, list[str]] = {
    "uv": ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "pylock.toml"],
    "poetry": ["poetry", "export", "-f", "requirements.txt", "--without", "dev"],
    "pipenv": ["pipenv", "requirements", "--hash"],
    "pdm": ["pdm", "export", "-f", "requirements", "--prod"],
}

# tool name -> the file name the export is written to. pip only recognizes the
# PEP 751 format under its standard name (``pylock.toml`` / ``pylock.*.toml``).
_EXPORT_FILENAMES: dict[str, str] = {"uv": "pylock.toml"}
_DEFAULT_EXPORT_FILENAME = "requirements.txt"

# tool name -> the flag that selects one optional-dependency extra (repeated per extra).
# Each manager spells its own ``[project.optional-dependencies]`` selector differently.
_EXTRA_FLAGS: dict[str, str] = {
    "uv": "--extra",
    "poetry": "--extras",
    "pipenv": "--categories",
    "pdm": "--group",
}


# An inline-table artifact entry in uv's pylock.toml output: `{ url = "..."` .
_ARTIFACT_URL = re.compile(r'(\{\s*)url = "([^"]+)"')


def _add_encoded_artifact_names(pylock: str) -> str:
    """Work around a pip/packaging pylock interop bug with percent-encoded URLs.

    uv's pylock.toml export omits the optional ``name`` field of wheel/sdist
    entries, and pip (the vendored ``packaging.pylock._url_name``) derives the
    file name from the URL's last path segment *without* percent-decoding it.
    A local version like ``2.12.1+cu130`` is encoded as ``%2B`` in the URL, so
    pip rejects the export ("Invalid wheel filename 'torch-2.12.1%2Bcu130-…'").

    Add an explicit, decoded ``name`` to every artifact entry whose URL
    basename is percent-encoded: ``name`` takes precedence over the URL-derived
    name, and the URL itself (what pip actually fetches) is left untouched.
    """

    def fix(m: re.Match[str]) -> str:
        url = m.group(2)
        basename = urlparse(url).path.rsplit("/", 1)[-1]
        decoded = unquote(basename)
        if decoded == basename:
            return m.group(0)
        return f'{m.group(1)}name = "{decoded}", url = "{url}"'

    return _ARTIFACT_URL.sub(fix, pylock)


def _export_cmd(manager: str, extras: tuple[str, ...]) -> list[str]:
    """The export command for ``manager`` with each ``extra`` appended as a selector flag."""
    cmd = list(_EXPORT_CMDS[manager])
    flag = _EXTRA_FLAGS[manager]
    for extra in extras:
        cmd += [flag, extra]
    return cmd


def _auto_detect(project_dir: Path) -> str | None:
    """Detect the manager from the presence of a lockfile (None if absent)."""
    for manager, lockfile in _LOCKFILES:
        if (project_dir / lockfile).is_file():
            return manager
    return None


def _warn(log, message: str) -> None:
    log(f"warning: {message}")


def resolve_manager(project_dir: Path, override: str | None, *, log=print) -> str:
    """Determine the manager to use (or "requirements.txt").

    With no explicit ``[tool.pyappdist].manager`` and no detectable lockfile, fall
    back to a checked-in ``requirements.txt`` if one exists; otherwise the manager is
    undeterminable and a ``BuildError`` is raised.
    """
    if override:
        return override
    detected = _auto_detect(project_dir)
    if detected:
        return detected
    if (project_dir / "requirements.txt").is_file():
        _warn(
            log,
            "no lockfile (uv.lock etc.) and no [tool.pyappdist].manager setting; "
            "using the existing requirements.txt",
        )
        return "requirements.txt"
    raise BuildError(
        "cannot determine the dependency manager: set [tool.pyappdist].manager, or "
        "provide a lockfile (uv.lock / poetry.lock / Pipfile.lock / pdm.lock) or a "
        "requirements.txt in the project directory"
    )


def resolve_requirements(config: Config, wheelhouse: Path, *, log=print) -> Path:
    """Prepare the pinned dependency file in the wheelhouse and return its path.

    The file is ``pylock.toml`` for uv (PEP 751, preserves per-package index
    pins) and ``requirements.txt`` for every other manager.
    """
    manager = resolve_manager(config.project_dir, config.manager, log=log)
    out = wheelhouse / _EXPORT_FILENAMES.get(manager, _DEFAULT_EXPORT_FILENAME)

    if manager == "requirements.txt":
        src = config.project_dir / "requirements.txt"
        if not src.is_file():
            raise BuildError(
                f"requirements.txt is missing: {src}"
                " (provide a manager lockfile or place a requirements.txt)"
            )
        if config.extras:
            _warn(
                log,
                "ignoring targets.extras because the dependency source is a checked-in "
                "requirements.txt (extras only apply to lockfile exports)",
            )
        log(f"deps: using requirements.txt ({src})")
        out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return out

    cmd = _export_cmd(manager, config.extras)
    extras_note = f" with extras {list(config.extras)}" if config.extras else ""
    log(f"deps: exporting {out.name} from {manager} lock{extras_note}")
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
            f"dependency export failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.strip()}"
        )
    text = proc.stdout
    if manager == "uv":
        text = _add_encoded_artifact_names(text)
    out.write_text(text, encoding="utf-8")
    return out
