"""Loading and validation of ``[tool.pyappdist]``.

Treats pyproject.toml as the single source of truth and normalizes it into a
typed dataclass.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .targets import Target, get_target

_PYTHON_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")

_MANAGERS = ("uv", "poetry", "pipenv", "pdm", "requirements.txt")


@dataclass(frozen=True)
class LauncherConfig:
    name: str           # output exe name (without extension)
    entry: str          # "module:callable"
    gui: bool = False
    icon: str | None = None
    args: str = ""      # fixed arguments (single string)


@dataclass(frozen=True)
class WixConfig:
    manufacturer: str | None = None
    upgrade_code: str | None = None


@dataclass(frozen=True)
class Config:
    project_dir: Path
    name: str           # display name
    dist_name: str      # distribution package name ([project].name)
    version: str
    python: str         # "X.Y" or "X.Y.Z"
    target: Target
    identifier: str | None
    launchers: tuple[LauncherConfig, ...]
    wix: WixConfig
    manager: str | None  # manager used for dependency resolution (uv/poetry/pipenv/pdm/requirements.txt). None=auto-detect

    @property
    def python_minor(self) -> str:
        parts = self.python.split(".")
        return f"{parts[0]}.{parts[1]}"


def load_config(project_dir: Path, *, target_override: str | None = None) -> Config:
    project_dir = Path(project_dir).resolve()
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.is_file():
        raise ConfigError(f"pyproject.toml not found: {pyproject}")

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    tool = data.get("tool", {}).get("pyappdist")
    if tool is None:
        raise ConfigError(f"[tool.pyappdist] is missing: {pyproject}")

    dist_name = project.get("name")
    if not dist_name:
        raise ConfigError("[project].name is required")
    name = tool.get("name") or dist_name

    version = tool.get("version") or project.get("version") or "0.0.0"

    python = tool.get("python")
    if not python:
        raise ConfigError("[tool.pyappdist].python is required (e.g. \"3.12\")")
    if not _PYTHON_RE.match(str(python)):
        raise ConfigError(f"python must be in X.Y or X.Y.Z format: {python!r}")

    target_name = target_override or tool.get("target") or "windows-x86_64"
    target = get_target(target_name)

    launchers = _parse_launchers(tool.get("launchers"))
    wix = _parse_wix(tool.get("wix"))

    manager = tool.get("manager")
    if manager is not None and manager not in _MANAGERS:
        raise ConfigError(
            f"[tool.pyappdist].manager must be one of {_MANAGERS}: {manager!r}"
        )

    return Config(
        project_dir=project_dir,
        name=str(name),
        dist_name=str(dist_name),
        version=str(version),
        python=str(python),
        target=target,
        identifier=tool.get("identifier"),
        launchers=launchers,
        wix=wix,
        manager=manager,
    )


def _parse_launchers(raw: object) -> tuple[LauncherConfig, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("[tool.pyappdist].launchers must be an array")
    out: list[LauncherConfig] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConfigError(f"launchers[{i}] must be a table")
        name = item.get("name")
        entry = item.get("entry")
        if not name:
            raise ConfigError(f"launchers[{i}].name is required")
        if not entry or ":" not in str(entry):
            raise ConfigError(
                f"launchers[{i}].entry must be in \"module:callable\" format: {entry!r}"
            )
        out.append(
            LauncherConfig(
                name=str(name),
                entry=str(entry),
                gui=bool(item.get("gui", False)),
                icon=item.get("icon"),
                args=str(item.get("args", "")),
            )
        )
    return tuple(out)


def _parse_wix(raw: object) -> WixConfig:
    if raw is None:
        return WixConfig()
    if not isinstance(raw, dict):
        raise ConfigError("[tool.pyappdist.wix] must be a table")
    return WixConfig(
        manufacturer=raw.get("manufacturer"),
        upgrade_code=raw.get("upgrade_code"),
    )
