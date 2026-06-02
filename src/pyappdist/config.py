"""Loading and validation of ``[tool.pyappdist]``.

Treats pyproject.toml as the single source of truth and normalizes it into typed
dataclasses. App-level settings live under ``[tool.pyappdist]``; each output package
is one ``[[tool.pyappdist.targets]]`` entry. ``load_configs`` resolves the app-level
settings together with each selected target into a flat ``Config`` (one per target),
so the rest of the build pipeline stays single-target.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .targets import Target, get_target

_PYTHON_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")

_MANAGERS = ("uv", "poetry", "pipenv", "pdm", "requirements.txt")

# Install scope of the generated MSI (a build-time choice).
#   machine - all users, installs into Program Files (requires admin)
#   user    - current user only, installs into %LocalAppData%\Programs (no admin)
_WIX_SCOPES = ("machine", "user")

# Output package format per target.
#   msi/msix - Windows packages (see WixConfig/MsixConfig)
#   linux    - a portable .tar.gz plus a self-extracting .run installer (see LinuxConfig)
_FORMATS = ("msi", "msix", "linux")

# Each output format produces a package for exactly one OS; a target's platform must match.
_FORMAT_OS = {"msi": "windows", "msix": "windows", "linux": "linux"}


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
    scope: str = "user"  # one of _WIX_SCOPES
    license: str | None = None  # optional path (relative to project_dir) to an RTF EULA


@dataclass(frozen=True)
class MsixConfig:
    """MSIX-specific settings; defaults are resolved when the manifest is generated."""

    identity_name: str | None = None  # MSIX Identity/Name (default: dist_name)
    publisher: str | None = None      # MSIX Identity/Publisher DN (default: CN=<manufacturer>)
    display_name: str | None = None   # default: app display name
    logo: str | None = None           # path (relative to project_dir) to a source PNG


@dataclass(frozen=True)
class LinuxConfig:
    """Linux ``format = "linux"`` settings.

    The output is a portable ``.tar.gz`` (the image tree) plus a self-extracting
    ``.run`` installer that copies into a per-user prefix (``$HOME/.local`` by default),
    symlinks each launcher into ``<prefix>/bin``, and — only when a launcher has an
    ``icon`` — writes a ``.desktop`` entry. No root required; updates are the app's job.
    """

    categories: str = "Utility;"  # freedesktop .desktop Categories (icon launchers only)
    compression: str = "xz"       # payload compression: "gzip" | "bzip2" | "xz"


@dataclass(frozen=True)
class Config:
    """One fully-resolved build target (app-level settings + one target's settings)."""

    project_dir: Path
    name: str           # display name
    dist_name: str      # distribution package name ([project].name)
    version: str
    python: str         # "X.Y" or "X.Y.Z"
    target: Target
    target_name: str    # the [[tool.pyappdist.targets]].name label (defaults to the platform)
    format: str         # output package format: "msi" | "msix" | "linux"
    launchers: tuple[LauncherConfig, ...]
    wix: WixConfig
    msix: MsixConfig
    manager: str | None  # manager used for dependency resolution (uv/poetry/pipenv/pdm/requirements.txt). None=auto-detect
    linux: LinuxConfig = LinuxConfig()

    @property
    def python_minor(self) -> str:
        parts = self.python.split(".")
        return f"{parts[0]}.{parts[1]}"


def load_configs(
    project_dir: Path, *, select: Sequence[str] | None = None
) -> list[Config]:
    """Resolve the selected ``[[tool.pyappdist.targets]]`` into one ``Config`` each.

    ``select`` is a list of target names to build; an empty/``None`` selection builds
    all targets (in declaration order). Unknown names raise ``ConfigError``.
    """
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

    launchers = _parse_launchers(tool.get("launchers"))

    manager = tool.get("manager")
    if manager is not None and manager not in _MANAGERS:
        raise ConfigError(
            f"[tool.pyappdist].manager must be one of {_MANAGERS}: {manager!r}"
        )

    specs = _parse_targets(tool.get("targets"))
    available = [s[0] for s in specs]
    if select:
        unknown = [s for s in select if s not in available]
        if unknown:
            raise ConfigError(
                f"unknown target(s): {unknown} (available: {available})"
            )
        specs = [s for s in specs if s[0] in set(select)]

    return [
        Config(
            project_dir=project_dir,
            name=str(name),
            dist_name=str(dist_name),
            version=str(version),
            python=str(python),
            target=target,
            target_name=target_name,
            format=fmt,
            launchers=launchers,
            wix=wix,
            msix=msix,
            manager=manager,
            linux=linux,
        )
        for (target_name, target, fmt, wix, msix, linux) in specs
    ]


def _parse_targets(
    raw: object,
) -> list[tuple[str, Target, str, WixConfig, MsixConfig, LinuxConfig]]:
    if not raw:
        raise ConfigError(
            "at least one [[tool.pyappdist.targets]] is required"
        )
    if not isinstance(raw, list):
        raise ConfigError("[[tool.pyappdist.targets]] must be an array of tables")

    specs: list[tuple[str, Target, str, WixConfig, MsixConfig, LinuxConfig]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConfigError(f"targets[{i}] must be a table")
        platform = item.get("platform")
        if not platform:
            raise ConfigError(
                f"targets[{i}].platform is required (e.g. \"windows-x86_64\")"
            )
        target = get_target(str(platform))
        target_name = str(item.get("name") or platform)
        fmt = item.get("format")
        if fmt is None:
            raise ConfigError(f"targets[{i}].format is required (one of {_FORMATS})")
        if fmt not in _FORMATS:
            raise ConfigError(f"targets[{i}].format must be one of {_FORMATS}: {fmt!r}")
        if _FORMAT_OS[fmt] != target.os:
            raise ConfigError(
                f"targets[{i}]: format={fmt!r} is for {_FORMAT_OS[fmt]}, but platform "
                f"{target.name!r} is {target.os}"
            )
        specs.append(
            (
                target_name, target, str(fmt),
                _parse_wix(item, i), _parse_msix(item, i), _parse_linux(item, i),
            )
        )

    names = [s[0] for s in specs]
    dups = sorted({n for n in names if names.count(n) > 1})
    if dups:
        raise ConfigError(
            f"duplicate [[tool.pyappdist.targets]].name: {dups} "
            "(target names must be unique)"
        )
    return specs


def _parse_wix(raw: dict, index: int) -> WixConfig:
    where = f"targets[{index}]"
    scope = raw.get("scope", "user")
    if scope not in _WIX_SCOPES:
        raise ConfigError(f"{where}.scope must be one of {_WIX_SCOPES}: {scope!r}")
    license_ = raw.get("license")
    if license_ is not None and not str(license_).lower().endswith(".rtf"):
        raise ConfigError(f"{where}.license must be an .rtf file: {license_!r}")
    return WixConfig(
        manufacturer=raw.get("manufacturer"),
        upgrade_code=raw.get("upgrade_code"),
        scope=str(scope),
        license=str(license_) if license_ is not None else None,
    )


def _parse_msix(raw: dict, index: int) -> MsixConfig:
    logo = raw.get("logo")
    if logo is not None and not str(logo).lower().endswith(".png"):
        raise ConfigError(f"targets[{index}].logo must be a .png file: {logo!r}")
    return MsixConfig(
        identity_name=raw.get("identity_name"),
        publisher=raw.get("publisher"),
        display_name=raw.get("display_name"),
        logo=str(logo) if logo is not None else None,
    )


_LINUX_COMPRESSION = ("gzip", "bzip2", "xz")


def _parse_linux(raw: dict, index: int) -> LinuxConfig:
    categories = raw.get("categories", "Utility;")
    compression = str(raw.get("compression", "xz"))
    if compression not in _LINUX_COMPRESSION:
        raise ConfigError(
            f"targets[{index}].compression must be one of "
            f"{', '.join(_LINUX_COMPRESSION)}: {compression!r}"
        )
    return LinuxConfig(categories=str(categories), compression=compression)


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


def ensure_upgrade_code(project_dir: Path, target_name: str, *, log=print) -> str:
    """Return the WiX upgrade_code for ``target_name``, generating one if unset.

    The upgrade code identifies the product across versions for MSI MajorUpgrade, so it
    must stay stable across builds and is per target (each platform/scope needs its own).
    When missing we generate a UUID and write it back into the matching
    ``[[tool.pyappdist.targets]]`` entry, editing with tomlkit so existing formatting and
    comments are preserved.
    """
    import uuid

    import tomlkit

    from .wix.guid import is_guid

    pyproject = Path(project_dir).resolve() / "pyproject.toml"
    doc = tomlkit.parse(pyproject.read_text(encoding="utf-8"))

    targets = doc.get("tool", {}).get("pyappdist", {}).get("targets")
    entry = None
    for item in targets or []:
        if str(item.get("name") or item.get("platform")) == target_name:
            entry = item
            break
    if entry is None:
        raise ConfigError(
            f"target {target_name!r} not found in [[tool.pyappdist.targets]]"
        )

    existing = entry.get("upgrade_code")
    if existing and is_guid(str(existing)):
        return str(existing)

    code = str(uuid.uuid4()).upper()
    entry["upgrade_code"] = code
    pyproject.write_text(tomlkit.dumps(doc), encoding="utf-8")
    log(f"wix: generated upgrade_code {code} for target {target_name!r} -> {pyproject}")
    return code
