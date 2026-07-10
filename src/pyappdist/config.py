"""Loading and validation of ``[tool.pyappdist]``.

Treats pyproject.toml as the single source of truth and normalizes it into typed
dataclasses. App-level settings live under ``[tool.pyappdist]``; each output package
is one ``[[tool.pyappdist.targets]]`` entry. ``load_configs`` resolves the app-level
settings together with each selected target into a flat ``Config`` (one per target),
so the rest of the build pipeline stays single-target.
"""

from __future__ import annotations

import re
import sys
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
#   linux    - a self-extracting .run installer (see LinuxConfig)
#   macos    - the same POSIX .run installer, for macOS (see MacosConfig)
#   macapp/dmg - a macOS .app bundle (GUI distribution); dmg additionally wraps it in a
#              disk image. Both Developer-ID-sign + notarize when configured (see MacosConfig).
_FORMATS = ("msi", "msix", "linux", "macos", "macapp", "dmg")

# Each output format produces a package for exactly one OS; a target's platform must match.
_FORMAT_OS = {
    "msi": "windows",
    "msix": "windows",
    "linux": "linux",
    "macos": "macos",
    "macapp": "macos",
    "dmg": "macos",
}

# reverse-DNS CFBundleIdentifier (e.g. "com.example.myapp"); required for macapp/dmg targets.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

# Launcher entry point. Two forms:
#   "module:callable" - import callable from module and call it (sys.exit on its return)
#   "module.path"     - run the module as `python -m module.path` (no callable)
_ENTRY_MODULE_RE = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")
_ENTRY_CALLABLE_RE = re.compile(r"^[A-Za-z_]\w*$")

# Characters a launcher or target name must not contain. Non-ASCII names are supported
# (the Windows build pipeline renames the final .exe with Python exactly for that), but
# the name becomes a filename on every OS (Windows forbids <>:"/\|?*), a symlink in
# <prefix>/bin, and a field in the .run installer's whitespace/colon-delimited
# launcher records — so path separators, those Windows-reserved characters,
# whitespace, and control characters are all rejected.
_NAME_BAD_CHARS = set('<>:"/\\|?*')

# MSI ProductVersion (and the MSIX Identity Version derived from it) must be a dotted
# numeric version; anything else (e.g. "1.0.0rc1") fails at package build time with an
# obscure toolchain error, so reject it up front for msi/msix targets only.
_MSI_VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")


@dataclass(frozen=True)
class LauncherConfig:
    name: str           # output exe name (without extension)
    entry: str          # "module:callable" or a dotted "module.path" run as `python -m`
    gui: bool = False
    # Per-OS icon paths (relative to project_dir), as (os, path) pairs — os is one of
    # "windows"/"macos"/"linux" (matching Target.os). Stored as a tuple, not a dict, so the
    # frozen dataclass stays hashable. Use icon_for() to look one up.
    icons: tuple[tuple[str, str], ...] = ()
    args: str = ""      # fixed arguments (single string)

    def icon_for(self, os: str) -> str | None:
        """The icon path configured for ``os`` (``Target.os``), or None."""
        for key, path in self.icons:
            if key == os:
                return path
        return None

    @property
    def bootstrap(self) -> str:
        """The ``-c`` program that starts the app.

        For a ``"module:callable"`` entry: import the callable and exit with its return
        code. For a dotted ``"module.path"`` entry (no colon): run it as ``python -m
        module.path`` via ``runpy`` (``__name__ == "__main__"``), so modules guarded by
        ``if __name__ == "__main__":`` (e.g. NiceGUI apps) work.

        Shared by every launcher kind (Windows console, the POSIX shell wrapper, and the
        macOS Mach-O stub). The Windows ``gui`` launcher wraps the ``"module:callable"``
        form with a MessageBox in ``launcher/build.py``; everything else uses it verbatim.
        """
        if ":" in self.entry:
            module, _, func = self.entry.partition(":")
            return f"import sys; from {module} import {func}; sys.exit({func}())"
        return (
            f"import runpy; runpy.run_module({self.entry!r}, "
            "run_name='__main__', alter_sys=True)"
        )


@dataclass(frozen=True)
class WixConfig:
    manufacturer: str | None = None
    upgrade_code: str | None = None
    scope: str = "user"  # one of _WIX_SCOPES
    license: str | None = None  # optional path (relative to project_dir) to an RTF EULA
    # Code-sign the launcher .exe and the .msi (off by default). When on, the command is
    # resolved by sign.resolve_msi_sign_command: PYAPPDIST_SIGN_CMD > code-sign-command >
    # a built-in signtool default.
    code_sign: bool = False
    code_sign_command: str | None = None
    # Emit MajorUpgrade@AllowSameVersionUpgrades="yes" so reinstalling the same version
    # upgrades in place instead of erroring/coexisting (handy while iterating). Off by default.
    allow_same_version_upgrades: bool = False


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

    The output is a self-extracting ``.run`` installer that copies the image tree into a
    per-user prefix (``$HOME/.local`` by default), symlinks each launcher into
    ``<prefix>/bin``, and — only when a launcher has an ``icon`` — writes a ``.desktop``
    entry. No root required; updates are the app's job.
    """

    categories: str = "Utility;"  # freedesktop .desktop Categories (icon launchers only)
    compression: str = "xz"       # payload compression: "gzip" | "bzip2" | "xz"


@dataclass(frozen=True)
class MacosConfig:
    """macOS target settings, shared by ``macos`` (.run) and ``app``/``dmg`` (.app bundle).

    ``compression`` applies only to ``format = "macos"``: the output mirrors Linux — a
    self-extracting ``.run`` that installs into a per-user prefix and symlinks each launcher
    into ``<prefix>/bin`` (macOS has no freedesktop equivalent, so launcher ``icon``/``gui``
    are ignored). The default is ``gzip`` (not ``xz``) because ``xz`` is not preinstalled on
    macOS.

    The remaining fields apply to ``format = "macapp"``/``"dmg"`` — assembling a ``.app``
    bundle (and, for ``dmg``, wrapping it in a disk image). When ``signing-identity`` (or
    ``PYAPPDIST_SIGNING_IDENTITY``) names a Developer ID identity the bundle is signed with
    a hardened runtime; with a ``notary-profile`` it is then notarized and stapled. With no
    identity the bundle is ad-hoc signed (runs locally, rejected by Gatekeeper elsewhere).
    """

    compression: str = "gzip"        # (.run) payload compression: "gzip" | "bzip2" | "xz"
    # --- macapp/dmg ---  (the .app icon comes from each launcher's icon["macos"], not here)
    min_macos: str = "11.0"          # LSMinimumSystemVersion / clang -mmacosx-version-min
    signing_identity: str | None = None  # "Developer ID Application: Name (TEAMID)"; None=ad-hoc
    team_id: str | None = None       # Apple Developer Team ID (informational)
    notary_profile: str | None = None    # notarytool keychain profile name
    entitlements: str | None = None      # path (relative to project_dir) to an entitlements plist
    category: str | None = None          # LSApplicationCategoryType


@dataclass(frozen=True)
class Config:
    """One fully-resolved build target (app-level settings + one target's settings)."""

    project_dir: Path
    name: str           # display name
    dist_name: str      # distribution package name ([project].name)
    version: str
    python: str         # "X.Y" or "X.Y.Z"
    identifier: str | None  # CFBundleIdentifier (reverse-DNS); required for macapp/dmg targets
    target: Target
    target_name: str    # the [[tool.pyappdist.targets]].name label (required, unique)
    format: str         # output package: "msi" | "msix" | "linux" | "macos" | "macapp" | "dmg"
    launchers: tuple[LauncherConfig, ...]
    wix: WixConfig
    msix: MsixConfig
    manager: str | None  # manager used for dependency resolution (uv/poetry/pipenv/pdm/requirements.txt). None=auto-detect
    # Optional-dependency extras to include when exporting requirements.txt from the lockfile
    # (e.g. uv's --extra). Empty = production deps only (dev excluded), matching the default.
    extras: tuple[str, ...] = ()
    linux: LinuxConfig = LinuxConfig()
    macos: MacosConfig = MacosConfig()

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
    # An unquoted TOML number silently drops trailing zeros (1.10 parses as the
    # float 1.1), so reject non-strings before they mangle the version.
    if not isinstance(version, str):
        raise ConfigError(
            f'version must be a quoted string (e.g. version = "1.10"): got {version!r}'
        )

    python = tool.get("python")
    if not python:
        raise ConfigError("[tool.pyappdist].python is required (e.g. \"3.12\")")
    # Same trap as version: python = 3.10 is the float 3.1.
    if not isinstance(python, str):
        raise ConfigError(
            "[tool.pyappdist].python must be a quoted string "
            f'(e.g. python = "3.10"): got {python!r}'
        )
    if not _PYTHON_RE.match(python):
        raise ConfigError(f"python must be in X.Y or X.Y.Z format: {python!r}")

    launchers = _parse_launchers(tool.get("launchers"))

    manager = tool.get("manager")
    if manager is not None and manager not in _MANAGERS:
        raise ConfigError(
            f"[tool.pyappdist].manager must be one of {_MANAGERS}: {manager!r}"
        )

    specs = _parse_targets(tool.get("targets"))

    # CFBundleIdentifier (reverse-DNS). Required when any target builds a .app bundle.
    identifier = tool.get("identifier")
    if identifier is not None:
        identifier = str(identifier)
        if not _IDENTIFIER_RE.match(identifier):
            raise ConfigError(
                "[tool.pyappdist].identifier must be reverse-DNS "
                f'(e.g. "com.example.myapp"): {identifier!r}'
            )
    if any(fmt in ("macapp", "dmg") for (_, _, fmt, *_rest) in specs) and not identifier:
        raise ConfigError(
            '[tool.pyappdist].identifier is required for macapp/dmg targets '
            '(reverse-DNS, e.g. "com.example.myapp")'
        )

    if any(fmt in ("msi", "msix") for (_, _, fmt, *_rest) in specs) and not _MSI_VERSION_RE.match(
        version
    ):
        raise ConfigError(
            "msi/msix targets require a dotted numeric version "
            f'(e.g. "1.2.3"; MSI ProductVersion cannot express pre-releases): {version!r}'
        )

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
            version=version,
            python=python,
            identifier=identifier,
            target=target,
            target_name=target_name,
            format=fmt,
            launchers=launchers,
            wix=wix,
            msix=msix,
            manager=manager,
            extras=extras,
            linux=linux,
            macos=macos,
        )
        for (target_name, target, fmt, wix, msix, extras, linux, macos) in specs
    ]


def _parse_targets(
    raw: object,
) -> list[
    tuple[str, Target, str, WixConfig, MsixConfig, tuple[str, ...], LinuxConfig, MacosConfig]
]:
    if not raw:
        raise ConfigError(
            "at least one [[tool.pyappdist.targets]] is required"
        )
    if not isinstance(raw, list):
        raise ConfigError("[[tool.pyappdist.targets]] must be an array of tables")

    specs: list[
        tuple[str, Target, str, WixConfig, MsixConfig, tuple[str, ...], LinuxConfig, MacosConfig]
    ] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConfigError(f"targets[{i}] must be a table")
        platform = item.get("platform")
        if not platform:
            raise ConfigError(
                f"targets[{i}].platform is required (e.g. \"windows-x86_64\")"
            )
        target = get_target(str(platform))
        name = item.get("name")
        if not name:
            raise ConfigError(f"targets[{i}].name is required")
        target_name = str(name)
        _validate_target_name(target_name, i)
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
        # allow-same-version-upgrades maps to WiX MajorUpgrade@AllowSameVersionUpgrades,
        # which is MSI-only; MSIX has no manifest equivalent, so it has no effect there.
        if fmt == "msix" and "allow-same-version-upgrades" in item:
            print(
                f"warning: targets[{i}].allow-same-version-upgrades has no effect on "
                "msix (it is MSI-only)",
                file=sys.stderr,
            )
        specs.append(
            (
                target_name, target, str(fmt),
                _parse_wix(item, i), _parse_msix(item, i), _parse_extras(item, i),
                _parse_linux(item, i), _parse_macos(item, i),
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
    code_sign = raw.get("code-sign", False)
    if not isinstance(code_sign, bool):
        raise ConfigError(f"{where}.code-sign must be a boolean: {code_sign!r}")
    allow_same = raw.get("allow-same-version-upgrades", False)
    if not isinstance(allow_same, bool):
        raise ConfigError(
            f"{where}.allow-same-version-upgrades must be a boolean: {allow_same!r}"
        )
    return WixConfig(
        manufacturer=raw.get("manufacturer"),
        upgrade_code=raw.get("upgrade-code"),
        scope=str(scope),
        license=str(license_) if license_ is not None else None,
        code_sign=code_sign,
        code_sign_command=_opt_str(raw, "code-sign-command"),
        allow_same_version_upgrades=allow_same,
    )


def _parse_msix(raw: dict, index: int) -> MsixConfig:
    logo = raw.get("logo")
    if logo is not None and not str(logo).lower().endswith(".png"):
        raise ConfigError(f"targets[{index}].logo must be a .png file: {logo!r}")
    return MsixConfig(
        identity_name=raw.get("identity-name"),
        publisher=raw.get("publisher"),
        display_name=raw.get("display-name"),
        logo=str(logo) if logo is not None else None,
    )


_COMPRESSIONS = ("gzip", "bzip2", "xz")  # shared by the linux/macos .run payload


def _compression(raw: dict, index: int, default: str) -> str:
    compression = str(raw.get("compression", default))
    if compression not in _COMPRESSIONS:
        raise ConfigError(
            f"targets[{index}].compression must be one of "
            f"{', '.join(_COMPRESSIONS)}: {compression!r}"
        )
    return compression


def _parse_linux(raw: dict, index: int) -> LinuxConfig:
    categories = raw.get("categories", "Utility;")
    return LinuxConfig(
        categories=str(categories), compression=_compression(raw, index, "xz")
    )


def _parse_macos(raw: dict, index: int) -> MacosConfig:
    # xz is not preinstalled on macOS, so the default payload compression is gzip.
    return MacosConfig(
        compression=_compression(raw, index, "gzip"),
        min_macos=str(raw.get("min-macos", "11.0")),
        signing_identity=_opt_str(raw, "signing-identity"),
        team_id=_opt_str(raw, "team-id"),
        notary_profile=_opt_str(raw, "notary-profile"),
        entitlements=_opt_str(raw, "entitlements"),
        category=_opt_str(raw, "category"),
    )


def _parse_extras(raw: dict, index: int) -> tuple[str, ...]:
    """Normalize a target's ``extras`` into a tuple of optional-dependency names.

    These are passed through to the lockfile export (e.g. uv's ``--extra``) so the
    matching ``[project.optional-dependencies]`` groups are bundled. Omitted/empty means
    production dependencies only (dev excluded) — the default.
    """
    extras = raw.get("extras")
    if extras is None:
        return ()
    if not isinstance(extras, list) or not all(isinstance(e, str) for e in extras):
        raise ConfigError(
            f"targets[{index}].extras must be an array of strings: {extras!r}"
        )
    return tuple(extras)


def _opt_str(raw: dict, key: str) -> str | None:
    value = raw.get(key)
    return str(value) if value is not None else None


def _validate_launcher_name(name: str, i: int) -> None:
    """Reject launcher names that would break filenames or the installer's records."""
    if any(
        c in _NAME_BAD_CHARS or c.isspace() or ord(c) < 32 for c in name
    ):
        raise ConfigError(
            "launchers[{}].name must not contain whitespace, control characters, "
            'or any of <>:"/\\|?* : {!r}'.format(i, name)
        )


def _validate_target_name(name: str, i: int) -> None:
    """Reject target names that would escape or break the output directory layout.

    The name becomes a path component under ``appdist/`` and ``.appdist-build/``
    (which ``pyappdist build`` deletes before rebuilding), so path separators,
    ``.``/``..``, and Windows-reserved characters must never get through.
    """
    if (
        any(c in _NAME_BAD_CHARS or c.isspace() or ord(c) < 32 for c in name)
        or name in (".", "..")
        or name.endswith(".")
    ):
        raise ConfigError(
            "targets[{}].name must not contain whitespace, control characters, "
            'or any of <>:"/\\|?*, and must not be "." or ".." or end with ".": '
            "{!r}".format(i, name)
        )


def _validate_entry(entry: str, i: int) -> None:
    """Validate a launcher ``entry`` (``"module:callable"`` or dotted ``"module.path"``)."""
    if ":" in entry:
        module, _, func = entry.partition(":")
        ok = bool(_ENTRY_MODULE_RE.match(module) and _ENTRY_CALLABLE_RE.match(func))
    else:
        ok = bool(_ENTRY_MODULE_RE.match(entry))
    if not ok:
        raise ConfigError(
            f"launchers[{i}].entry must be \"module:callable\" or a dotted "
            f"\"module.path\" (run as python -m): {entry!r}"
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
        if not entry:
            raise ConfigError(f"launchers[{i}].entry is required")
        _validate_launcher_name(str(name), i)
        _validate_entry(str(entry), i)
        out.append(
            LauncherConfig(
                name=str(name),
                entry=str(entry),
                gui=bool(item.get("gui", False)),
                icons=_parse_icon(item.get("icon"), i),
                args=str(item.get("args", "")),
            )
        )
    return tuple(out)


# Per-OS icon: keys are Target.os values; each value's format is what that OS needs.
_ICON_OSES = ("windows", "macos", "linux")
_ICON_SUFFIX = {"windows": ".ico", "macos": ".png"}  # linux: any image, not constrained


def _parse_icon(raw: object, index: int) -> tuple[tuple[str, str], ...]:
    """Normalize a launcher ``icon`` into ``((os, path), ...)``.

    ``icon`` must be a table mapping ``windows``/``macos``/``linux`` to a file path; the
    old single-string form is rejected. Each OS's value must use that OS's icon format
    (``.ico`` for windows, ``.png`` for macos).
    """
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise ConfigError(
            f"launchers[{index}].icon must be a table of per-OS paths, e.g. "
            '{ windows = "app.ico", macos = "app.png", linux = "app.png" }'
        )
    pairs: list[tuple[str, str]] = []
    for os_key, path in raw.items():
        if os_key not in _ICON_OSES:
            raise ConfigError(
                f"launchers[{index}].icon: unknown key {os_key!r} "
                f"(allowed: {', '.join(_ICON_OSES)})"
            )
        suffix = _ICON_SUFFIX.get(os_key)
        if suffix and not str(path).lower().endswith(suffix):
            raise ConfigError(
                f"launchers[{index}].icon.{os_key} must be a {suffix} file: {path!r}"
            )
        pairs.append((os_key, str(path)))
    return tuple(pairs)


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
        if str(item.get("name")) == target_name:
            entry = item
            break
    if entry is None:
        raise ConfigError(
            f"target {target_name!r} not found in [[tool.pyappdist.targets]]"
        )

    existing = entry.get("upgrade-code")
    if existing and is_guid(str(existing)):
        return str(existing)

    code = str(uuid.uuid4()).upper()
    entry["upgrade-code"] = code
    pyproject.write_text(tomlkit.dumps(doc), encoding="utf-8")
    log(f"wix: generated upgrade_code {code} for target {target_name!r} -> {pyproject}")
    return code
