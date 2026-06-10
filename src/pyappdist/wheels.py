"""Preparing wheels (building the app wheel + collecting dependency wheels).

* App itself: built into a wheel via ``pip wheel --no-deps`` using the project's
  build backend (PEP 517 = backend-agnostic). This runs with the **target runtime's
  python**, not the host python: even for a pure-Python app the build can be
  version-sensitive (``requires-python``, build-backend / build-dependency version
  constraints, version-conditional build logic), so building with a host python of a
  different version than the target may fail or produce a wrong wheel.
* Dependencies: pinned **based on the project's lockfile**. Using the manager
  (uv/poetry/pipenv/PDM), ``requirements.txt`` is exported from the lock
  (:mod:`pyappdist.deps`) and passed to the **target runtime's python** to run
  ``pip wheel -r requirements.txt``. For dependencies with published wheels that
  wheel is fetched; dependencies with only an sdist are built into a wheel with the
  target python (so packages without wheels are handled too). As a result, the
  wheelhouse ends up containing only wheels, so the later offline install just needs
  the wheels. Because resolution uses the target machine's interpretation, both
  environment markers like ``sys_platform`` and the wheel tags are natively correct
  (e.g. pandas's ``tzdata; sys_platform=="win32"`` is included). No cross specifier
  is needed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ._hostexec import target_relpath
from .config import Config
from .deps import resolve_requirements
from .errors import BuildError
from .runtime import RuntimeInfo


def build_wheelhouse(config: Config, runtime: RuntimeInfo, wheelhouse: Path, *, log=print) -> list[Path]:
    """Prepare the app + dependency wheels in the wheelhouse and return the list."""
    wheelhouse.mkdir(parents=True, exist_ok=True)
    # Start from an empty wheelhouse: the later install passes *every* wheel in it to
    # pip, so a stale wheel from a previous app/dependency version would make pip see
    # two conflicting versions of the same project. pip's own cache keeps this cheap.
    for stale in wheelhouse.glob("*.whl"):
        stale.unlink()
    build_app_wheel(config, runtime, wheelhouse, log=log)
    requirements = resolve_requirements(config, wheelhouse, log=log)
    collect_dependencies(runtime, requirements, wheelhouse, log=log)
    return sorted(wheelhouse.glob("*.whl"))


def build_app_wheel(config: Config, runtime: RuntimeInfo, wheelhouse: Path, *, log=print) -> Path:
    project_dir = config.project_dir
    log(f"wheels: building app wheel ({project_dir.name})")
    before = set(wheelhouse.glob("*.whl"))
    # PEP 517 build with the target runtime's python (backend-agnostic). cwd=wheelhouse so
    # --wheel-dir is "." and the project is passed relative to it (WSL interop converts the
    # cwd to the Windows side, so no wslpath is needed even for a Linux host -> Windows target).
    cmd = [
        str(runtime.python_exe), "-m", "pip", "wheel", "--no-deps",
        "--wheel-dir", ".", target_relpath(config.target, project_dir, wheelhouse),
    ]
    proc = subprocess.run(
        cmd, cwd=str(wheelhouse), capture_output=True, text=True, errors="replace"
    )
    if proc.returncode != 0:
        raise BuildError(
            f"app wheel build failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
    after = set(wheelhouse.glob("*.whl"))
    new = sorted(after - before)
    if not new:
        # If there is no diff (e.g. overwritten by a rebuild), return the newest one
        all_wheels = sorted(after, key=lambda p: p.stat().st_mtime)
        if not all_wheels:
            raise BuildError("pip wheel did not produce a wheel")
        return all_wheels[-1]
    return new[-1]


def collect_dependencies(runtime: RuntimeInfo, requirements_file: Path, wheelhouse: Path, *, log=print) -> list[Path]:
    """Collect the ``requirements.txt`` dependencies as wheels using the target runtime's python.

    Since it uses ``pip wheel -r``, dependencies with a wheel have that wheel
    fetched, while dependencies with only an sdist are built into a wheel with the
    target python (so packages without wheels are handled too). Markers are
    evaluated with the target python, so only the applicable dependencies are
    included.
    """
    log("wheels: collecting dependency wheels (pip wheel -r with the target runtime's python)")
    before = set(wheelhouse.glob("*.whl"))
    cmd = [
        str(runtime.python_exe), "-m", "pip", "wheel", "-r", requirements_file.name,
        "--wheel-dir", ".",
    ]
    proc = subprocess.run(
        cmd, cwd=str(wheelhouse), capture_output=True, text=True, errors="replace"
    )
    if proc.returncode != 0:
        raise BuildError(
            f"dependency wheel collection failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
    return sorted(set(wheelhouse.glob("*.whl")) - before)
