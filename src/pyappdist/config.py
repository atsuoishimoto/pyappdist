"""Loading and validation of ``[tool.pyappdist]``.

Treats pyproject.toml as the single source of truth and normalizes it into typed
dataclasses. App-level settings live under ``[tool.pyappdist]``; each output package
is one ``[[tool.pyappdist.targets]]`` entry. ``load_configs`` resolves the app-level
settings together with each selected target into a flat ``Config`` (one per target),
so the rest of the build pipeline stays single-target.
"""

from __future__ import annotations

import re
import shlex
import sys
import tomllib
from collections.abc import Collection, Sequence
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
#   pkg      - a macOS .pkg installer that puts the .app bundle(s) into /Applications
#              (system scope, admin install; see MacosConfig).
#   image    - no installer: an archive of the run-in-place image tree (.zip on Windows,
#              .tar.gz on Linux/macOS). Available on every platform.
_FORMATS = ("msi", "msix", "linux", "macos", "macapp", "dmg", "pkg", "image")

# Each output format produces a package for exactly one OS; a target's platform must
# match. "image" is deliberately absent — it archives the image tree as-is, which works
# for any target OS.
_FORMAT_OS = {
    "msi": "windows",
    "msix": "windows",
    "linux": "linux",
    "macos": "macos",
    "macapp": "macos",
    "dmg": "macos",
    "pkg": "macos",
}

# Formats that build a .app bundle, so they need the app-level `identifier` (and, with
# multiple launchers, identifier-segment launcher names).
_BUNDLE_FORMATS = ("macapp", "dmg", "pkg")

# How the compiled launchers are produced (targets whose launcher is a native
# binary — Windows .exe or macOS Mach-O — rather than a shell wrapper):
#   auto     - use the bundled prebuilt stub when present, else compile (default)
#   prebuilt - require the prebuilt stub (fail rather than compile)
#   source   - always compile with MSVC / clang
_LAUNCHER_BUILDS = ("auto", "prebuilt", "source")

# reverse-DNS CFBundleIdentifier (e.g. "com.example.myapp"); required for macapp/dmg/pkg targets.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

# One segment of a bundle identifier. With multiple launchers each .app gets
# "<identifier>.<launcher name>", so the launcher name itself must be a valid segment.
_IDENTIFIER_SEGMENT_RE = re.compile(r"^[A-Za-z0-9-]+$")

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
    # Fixed arguments. Shell form (str, split with POSIX quoting rules) or exec form
    # (a tuple of pre-split arguments, from a TOML array). Read via argv.
    args: str | tuple[str, ...] = ""

    def icon_for(self, os: str) -> str | None:
        """The icon path configured for ``os`` (``Target.os``), or None."""
        for key, path in self.icons:
            if key == os:
                return path
        return None

    @property
    def argv(self) -> tuple[str, ...]:
        """``args`` as individual arguments.

        The exec form (a TOML array) already is the argument list; the shell form
        (a string) is split with POSIX shell quoting rules — ``--path 'a b'`` is two
        arguments everywhere, and nothing is glob-expanded. Either way the list is
        the single canonical reading on every OS: each launcher kind renders it in
        whatever form its own OS needs (MSVC quoting on Windows, single quotes in
        the shell wrapper, a C array in the macOS stub), rather than re-splitting a
        raw string by its own rules. ``_parse_args`` has already rejected unparsable
        values at load time.
        """
        if isinstance(self.args, str):
            return tuple(shlex.split(self.args))
        return self.args

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
    # Emit MajorUpgrade@AllowSameVersionUpgrades="yes" so reinstalling the same version
    # upgrades in place instead of erroring/coexisting (handy while iterating). Off by default.
    allow_same_version_upgrades: bool = False
    # Append the install folder (where the launcher .exes live) to PATH via the MSI
    # Environment table (off by default). Follows the package scope: per-user edits the
    # user's PATH (HKCU), per-machine the system PATH (HKLM).
    add_to_path: bool = False


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

    The remaining fields apply to ``format = "macapp"``/``"dmg"``/``"pkg"`` — assembling a
    ``.app`` bundle (and wrapping it in a disk image for ``dmg``, or in a system-scope
    installer package for ``pkg``). When ``signing-identity`` (or
    ``PYAPPDIST_MACOS_SIGNING_IDENTITY``) names a Developer ID identity the bundle is signed with
    a hardened runtime; with a ``notary-profile`` it is then notarized and stapled. With no
    identity the bundle is ad-hoc signed (runs locally, rejected by Gatekeeper elsewhere).

    ``installer-identity`` and ``license`` apply to ``pkg`` only: the former is a
    **Developer ID Installer** identity (a different certificate type from Developer ID
    Application) that signs the ``.pkg`` itself via ``productbuild --sign`` (unset = the
    package is left unsigned); the latter is a license file Installer.app shows as a
    license page with its standard agree/disagree prompt.
    """

    compression: str = "gzip"        # (.run) payload compression: "gzip" | "bzip2" | "xz"
    # --- macapp/dmg/pkg ---  (the .app icon comes from each launcher's icon["macos"], not here)
    min_macos: str = "11.0"          # LSMinimumSystemVersion / clang -mmacosx-version-min
    signing_identity: str | None = None  # "Developer ID Application: Name (TEAMID)"; None=ad-hoc
    team_id: str | None = None       # Apple Developer Team ID (informational)
    notary_profile: str | None = None    # notarytool keychain profile name
    entitlements: str | None = None      # path (relative to project_dir) to an entitlements plist
    category: str | None = None          # LSApplicationCategoryType
    # --- pkg ---
    installer_identity: str | None = None  # "Developer ID Installer: Name (TEAMID)"; None=unsigned
    license: str | None = None       # optional path (relative to project_dir) to a license file


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
    format: str         # output package: one of _FORMATS
    launchers: tuple[LauncherConfig, ...]
    wix: WixConfig
    msix: MsixConfig
    manager: str | None  # manager used for dependency resolution (uv/poetry/pipenv/pdm/requirements.txt). None=auto-detect
    # Optional-dependency extras to include when exporting requirements.txt from the lockfile
    # (e.g. uv's --extra). Empty = production deps only (dev excluded), matching the default.
    extras: tuple[str, ...] = ()
    linux: LinuxConfig = LinuxConfig()
    macos: MacosConfig = MacosConfig()
    # Code-sign the target's Windows artifacts (off by default): the launcher .exes and
    # the package for msi/msix, the launcher .exes for a Windows image target. Only
    # valid on those formats — macOS signing is the separate signing-identity codesign
    # flow. The command is resolved by sign.resolve_sign_command:
    # PYAPPDIST_WIN_SIGN_CMD (env) > code-sign-command > a built-in signtool default.
    # `pyappdist build --code-sign` / `--no-code-sign` overrides the code-sign key.
    code_sign: bool = False
    code_sign_command: str | None = None
    # How to produce the compiled launchers (one of _LAUNCHER_BUILDS); only
    # meaningful on formats with a native launcher binary.
    launcher_build: str = "auto"
    # Skip launcher generation entirely (image format only): the archive then contains
    # just the installed tree, for apps that ship their own entry mechanism.
    no_launcher: bool = False
    # No explicit [tool.pyappdist].version was given: ``version`` holds the
    # "0.0.0" placeholder until the CLI resolves the real version from the app
    # wheel built by build-wheels (and clears this flag).
    version_from_wheel: bool = False

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

    # [tool.pyappdist].version is the only version read from pyproject.toml.
    # Without it, the version comes from the app wheel that build-wheels
    # produces: the PEP 517 build runs the project's real build backend, so
    # both a static [project].version and a backend-computed dynamic one
    # (hatch-vcs, setuptools-scm, ...) end up in the wheel, and the CLI fills
    # it in from there before any stage consumes config.version. Guessing here
    # instead — reading [project].version, or a "0.0.0" fallback — could stamp
    # every artifact (MSI ProductVersion, MSIX Identity, .run/archive
    # filenames, VERSIONINFO) with a version the wheel itself does not carry.
    version = tool.get("version")
    version_from_wheel = version is None
    if version_from_wheel:
        version = "0.0.0"  # placeholder; resolution replaces it before any use
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

    available = [s[0] for s in specs]
    if select:
        unknown = [s for s in select if s not in available]
        if unknown:
            raise ConfigError(
                f"unknown target(s): {unknown} (available: {available})"
            )
        specs = [s for s in specs if s[0] in set(select)]

    # CFBundleIdentifier (reverse-DNS). Required when a *selected* target builds a .app
    # bundle — merely-declared targets must not constrain unrelated builds, so this and
    # the MSI version check below run after the select filter.
    identifier = tool.get("identifier")
    if identifier is not None:
        identifier = str(identifier)
        if not _IDENTIFIER_RE.match(identifier):
            raise ConfigError(
                "[tool.pyappdist].identifier must be reverse-DNS "
                f'(e.g. "com.example.myapp"): {identifier!r}'
            )
    if any(fmt in _BUNDLE_FORMATS for (_, _, fmt, *_rest) in specs):
        if not identifier:
            raise ConfigError(
                '[tool.pyappdist].identifier is required for macapp/dmg/pkg targets '
                '(reverse-DNS, e.g. "com.example.myapp")'
            )
        # With multiple launchers each .app's CFBundleIdentifier is
        # "<identifier>.<launcher name>", so every launcher name must be a valid
        # identifier segment (same alphabet _IDENTIFIER_RE allows per segment) —
        # otherwise the derived identifier is rejectable at notarization/upload.
        if len(launchers) > 1:
            for i, spec in enumerate(launchers):
                if not _IDENTIFIER_SEGMENT_RE.match(spec.name):
                    raise ConfigError(
                        f"launchers[{i}].name {spec.name!r} cannot be used with "
                        "multiple launchers on a macapp/dmg/pkg target: each .app's "
                        'bundle identifier is "<identifier>.<launcher name>", so '
                        "the name must contain only letters, digits, and hyphens"
                    )

    # A wheel-resolved version is unknown until build-wheels produces the app
    # wheel, so the format/version compatibility check runs post-resolution
    # instead (the CLI calls check_msi_version with the wheel's version).
    selected_formats = {fmt for (_, _, fmt, *_rest) in specs}
    if not version_from_wheel:
        check_msi_version(version, selected_formats)

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
            code_sign=code_sign,
            code_sign_command=code_sign_command,
            launcher_build=launcher_build,
            no_launcher=no_launcher,
            version_from_wheel=version_from_wheel,
        )
        for (target_name, target, fmt, wix, msix, extras, linux, macos, no_launcher,
             code_sign, code_sign_command, launcher_build) in specs
    ]


def check_msi_version(version: str, formats: Collection[str]) -> None:
    """Reject/warn about a version the msi/msix toolchain cannot handle.

    Runs at config load for an explicit [tool.pyappdist].version, and from the
    CLI once any other version has been resolved from the built app wheel.
    """
    if {"msi", "msix"} & set(formats) and not _MSI_VERSION_RE.match(version):
        raise ConfigError(
            "msi/msix targets require a dotted numeric version "
            f'(e.g. "1.2.3"; MSI ProductVersion cannot express pre-releases): {version!r}'
        )
    # Windows Installer compares only the first three fields of ProductVersion, so
    # releases differing solely in the fourth are the same version to it: MajorUpgrade
    # does not fire, and without allow-same-version-upgrades the install errors or the
    # two versions coexist. Four fields stay accepted (MSIX's Identity Version uses
    # all four legitimately), but the MSI consequence is worth saying out loud.
    if "msi" in formats and version.count(".") == 3:
        print(
            f"warning: version {version!r} has four fields, but MSI upgrade logic "
            "compares only the first three; releases differing only in the fourth "
            "field look like the same version to Windows Installer",
            file=sys.stderr,
        )


_TargetSpec = tuple[
    str, Target, str, WixConfig, MsixConfig, tuple[str, ...], LinuxConfig, MacosConfig,
    bool, bool, str | None, str,
]

# Formats whose build produces an artifact the code-sign pass can act on: the launcher
# .exes + package for msi/msix, the launcher .exes for a Windows image target.
# Everything else (the POSIX .run installers, the .app bundle and .dmg/.pkg — signed
# by their own codesign flow — and a non-Windows image of shell wrappers) has nothing
# for the pass to sign.
_CODE_SIGN_FORMATS = ("msi", "msix")


def _code_signable(fmt: str, target: Target) -> bool:
    return fmt in _CODE_SIGN_FORMATS or (fmt == "image" and target.os == "windows")


# Formats whose installer shows a license page from the target-level `license` key:
# MSI's one-page WixUI_Minimal dialog and the .pkg's Installer.app license pane
# (which requires the user to agree before installing).
_LICENSE_FORMATS = ("msi", "pkg")


def _compiled_launcher(fmt: str, target: Target) -> bool:
    """Whether the target's launchers are native binaries (vs shell wrappers).

    Only those formats compile (or patch a prebuilt stub), so only they honor
    the ``launcher-build`` key: the Windows formats plus the macOS bundle
    formats. ``linux``/``macos`` (.run) and a non-Windows ``image`` ship shell
    wrappers.
    """
    if fmt in ("msi", "msix") or fmt in _BUNDLE_FORMATS:
        return True
    return fmt == "image" and target.os == "windows"


def _parse_targets(raw: object) -> list[_TargetSpec]:
    if not raw:
        raise ConfigError(
            "at least one [[tool.pyappdist.targets]] is required"
        )
    if not isinstance(raw, list):
        raise ConfigError("[[tool.pyappdist.targets]] must be an array of tables")

    specs: list[_TargetSpec] = []
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
        if fmt in _FORMAT_OS and _FORMAT_OS[fmt] != target.os:
            raise ConfigError(
                f"targets[{i}]: format={fmt!r} is for {_FORMAT_OS[fmt]}, but platform "
                f"{target.name!r} is {target.os}"
            )
        no_launcher = item.get("no-launcher", False)
        if not isinstance(no_launcher, bool):
            raise ConfigError(
                f"targets[{i}].no-launcher must be a boolean: {no_launcher!r}"
            )
        # The installer formats all need their launchers (shortcuts, .app bundles, bin/
        # symlinks reference them), so opting out only makes sense for the bare archive.
        if no_launcher and fmt != "image":
            raise ConfigError(
                f"targets[{i}].no-launcher is only supported with format=\"image\" "
                f"(format is {fmt!r})"
            )
        code_sign = item.get("code-sign", False)
        if not isinstance(code_sign, bool):
            raise ConfigError(f"targets[{i}].code-sign must be a boolean: {code_sign!r}")
        # code-sign-command alone stays legal on any signable format (it only takes
        # effect once signing is enabled by code-sign or --code-sign), but enabling
        # signing where nothing can be signed is a config mistake worth failing on.
        if code_sign and not _code_signable(str(fmt), target):
            raise ConfigError(
                f"targets[{i}].code-sign is not supported for format={fmt!r} on "
                f"platform {target.name!r}: there is no artifact for the signing pass "
                f"(supported: {', '.join(_CODE_SIGN_FORMATS)}, and image on Windows "
                "platforms)"
            )
        launcher_build = item.get("launcher-build", "auto")
        if launcher_build not in _LAUNCHER_BUILDS:
            raise ConfigError(
                f"targets[{i}].launcher-build must be one of {_LAUNCHER_BUILDS}: "
                f"{launcher_build!r}"
            )
        if "launcher-build" in item and not _compiled_launcher(str(fmt), target):
            raise ConfigError(
                f"targets[{i}].launcher-build has no effect for format={fmt!r} on "
                f"platform {target.name!r}: its launchers are shell wrappers, not "
                "compiled binaries"
            )
        # The license key is shared by the two formats with an installer license page
        # (msi and pkg); everywhere else it would be silently dead config.
        if "license" in item and fmt not in _LICENSE_FORMATS:
            raise ConfigError(
                f"targets[{i}].license is only supported with format "
                f"{' or '.join(repr(f) for f in _LICENSE_FORMATS)} (format is {fmt!r})"
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
                _parse_wix(item, i, str(fmt)), _parse_msix(item, i),
                _parse_extras(item, i),
                _parse_linux(item, i), _parse_macos(item, i, str(fmt)), no_launcher,
                code_sign, _opt_str(item, "code-sign-command"), str(launcher_build),
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


def _parse_wix(raw: dict, index: int, fmt: str) -> WixConfig:
    from .wix.guid import is_guid

    where = f"targets[{index}]"
    upgrade_code = raw.get("upgrade-code")
    if upgrade_code is not None and not is_guid(str(upgrade_code)):
        raise ConfigError(
            f"{where}.upgrade-code must be a valid GUID: {upgrade_code!r}"
        )
    scope = raw.get("scope", "user")
    if scope not in _WIX_SCOPES:
        raise ConfigError(f"{where}.scope must be one of {_WIX_SCOPES}: {scope!r}")
    # The license key is format-dispatched: a pkg target's license belongs to
    # MacosConfig (and is not RTF-only), so only msi picks it up here.
    license_ = raw.get("license") if fmt == "msi" else None
    if license_ is not None and not str(license_).lower().endswith(".rtf"):
        raise ConfigError(f"{where}.license must be an .rtf file: {license_!r}")
    allow_same = raw.get("allow-same-version-upgrades", False)
    if not isinstance(allow_same, bool):
        raise ConfigError(
            f"{where}.allow-same-version-upgrades must be a boolean: {allow_same!r}"
        )
    add_to_path = raw.get("add-to-path", False)
    if not isinstance(add_to_path, bool):
        raise ConfigError(f"{where}.add-to-path must be a boolean: {add_to_path!r}")
    return WixConfig(
        manufacturer=raw.get("manufacturer"),
        upgrade_code=str(upgrade_code) if upgrade_code is not None else None,
        scope=str(scope),
        license=str(license_) if license_ is not None else None,
        allow_same_version_upgrades=allow_same,
        add_to_path=add_to_path,
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


# Installer.app renders the pkg license page by file type (RTFD bundles are
# directories, so they are not supported here).
_PKG_LICENSE_SUFFIXES = (".txt", ".rtf", ".html")


def _parse_macos(raw: dict, index: int, fmt: str) -> MacosConfig:
    # The license key is format-dispatched: only pkg stores it here (msi keeps
    # its RTF license in WixConfig).
    license_ = raw.get("license") if fmt == "pkg" else None
    if license_ is not None and not str(license_).lower().endswith(_PKG_LICENSE_SUFFIXES):
        raise ConfigError(
            f"targets[{index}].license must be a .txt, .rtf, or .html file: {license_!r}"
        )
    # xz is not preinstalled on macOS, so the default payload compression is gzip.
    return MacosConfig(
        compression=_compression(raw, index, "gzip"),
        min_macos=str(raw.get("min-macos", "11.0")),
        signing_identity=_opt_str(raw, "signing-identity"),
        team_id=_opt_str(raw, "team-id"),
        notary_profile=_opt_str(raw, "notary-profile"),
        entitlements=_opt_str(raw, "entitlements"),
        category=_opt_str(raw, "category"),
        installer_identity=_opt_str(raw, "installer-identity"),
        license=str(license_) if license_ is not None else None,
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


def _parse_args(raw: object, i: int) -> str | tuple[str, ...]:
    """Normalize a launcher ``args`` value.

    Shell form (a string) is kept as-is after checking that POSIX shell quoting can
    parse it; exec form (an array of strings) becomes a tuple of pre-split arguments.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        try:
            shlex.split(raw)
        except ValueError as exc:
            raise ConfigError(
                f"launchers[{i}].args cannot be parsed ({exc}); arguments are split "
                f"with POSIX shell quoting rules: {raw!r}"
            ) from None
        return raw
    if isinstance(raw, list):
        for j, arg in enumerate(raw):
            if not isinstance(arg, str):
                raise ConfigError(
                    f"launchers[{i}].args[{j}] must be a string: {arg!r}"
                )
        return tuple(raw)
    raise ConfigError(
        f"launchers[{i}].args must be a string (split with POSIX shell quoting "
        f"rules) or an array of strings: {raw!r}"
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
                args=_parse_args(item.get("args"), i),
            )
        )
    # Duplicate names clobber each other's image/<name>.exe and produce duplicate
    # WiX Shortcut ids (an opaque `wix build` error). Compare casefolded because the
    # Windows filesystem is case-insensitive, so case-only variants collide too.
    folded = [launcher.name.casefold() for launcher in out]
    dups = sorted({name for name in folded if folded.count(name) > 1})
    if dups:
        raise ConfigError(
            f"duplicate [[tool.pyappdist.launchers]].name: {dups} "
            "(launcher names must be unique, ignoring case)"
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
    if existing is not None:
        # Never replace an existing value: the upgrade code is the product's
        # identity across versions, and silently regenerating a mistyped one
        # would break MajorUpgrade of already-shipped installs.
        if not is_guid(str(existing)):
            raise ConfigError(
                f"target {target_name!r} has an invalid upgrade-code: {existing!r} "
                "(must be a valid GUID; fix it or remove the key to generate a new one)"
            )
        return str(existing)

    code = str(uuid.uuid4()).upper()
    entry["upgrade-code"] = code
    pyproject.write_text(tomlkit.dumps(doc), encoding="utf-8")
    log(f"wix: generated upgrade_code {code} for target {target_name!r} -> {pyproject}")
    return code
