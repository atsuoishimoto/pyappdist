"""Prebuilt launcher stubs: lookup and the ``build-prebuilt`` implementation.

Released wheels bundle compiler-less launcher stubs under
``resources/prebuilt/`` — one Windows ``.exe`` per (architecture, subsystem)
and one universal macOS Mach-O. ``build-launchers`` uses them by default (see
``launcher-build``) and gives each copy its per-app config without invoking a
compiler. The stubs themselves are compiled by ``pyappdist build-prebuilt``,
run on a Windows (or WSL + Visual Studio) host and on a macOS host — locally
for development, and by the release workflow on CI runners; the directory is
not committed to git, only shipped in wheels/sdists.

Every stub is compiled with ``PYAPPDIST_REQUIRE_CONFIG``, so an unpatched copy
refuses to run instead of silently doing nothing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ..errors import BuildError, ConfigError
from ..targets import TARGETS, Target

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"
PREBUILT_DIR = _RESOURCES / "prebuilt"

# The prebuilt Mach-O is built for both architectures with this deployment
# target; a source build honors the target's min-macos instead.
MACOS_MIN = "11.0"
_MACOS_ARCHS = ("arm64", "x86_64")

_WINDOWS_TARGETS = ("windows-x86_64", "windows-arm64")

# What `build-prebuilt [targets ...]` accepts: the Windows stubs are per
# platform (each is a console + gui pair), the macOS stub is one universal
# binary, so a single "macos" selector covers both mac platforms.
SELECTORS = (*_WINDOWS_TARGETS, "macos")

# The stubs carry no app config, so REQUIRE_CONFIG makes an unpatched copy fail
# loudly (the compiled-in defaults are placeholders).
_STUB_HEADER = "#define PYAPPDIST_REQUIRE_CONFIG 1\n"


def windows_stub(target: Target, gui: bool) -> Path:
    """Path of the bundled Windows stub for ``target`` (may not exist)."""
    kind = "gui" if gui else "console"
    return PREBUILT_DIR / f"launcher-{target.name}-{kind}.exe"


def macos_stub() -> Path:
    """Path of the bundled universal macOS stub (may not exist)."""
    return PREBUILT_DIR / "launcher-macos-universal"


def build_prebuilt(
    out_dir: Path | None = None,
    select: Sequence[str] | None = None,
    *,
    build_dir: Path | None = None,
    log=print,
) -> list[Path]:
    """Compile prebuilt stubs into ``out_dir`` (default: the installed
    package's ``resources/prebuilt/``, so a subsequent build picks them up).

    ``select`` names what to build (see :data:`SELECTORS`): each Windows
    platform is a console + gui ``.exe`` pair (arm64 uses the x64-hosted cross
    compiler), ``macos`` the single universal Mach-O. A selected stub that this
    host cannot build is an error. With no selection, everything the host's
    toolchain can produce is built, and what it cannot is skipped with a
    message — not an error — so the command is safe to run on any host.

    ``build_dir`` overrides where the build intermediates go (default:
    ``<out>/.build``; the CLI also fills it from the ``PYAPPDIST_BUILD_DIR``
    environment variable). Each stub gets its own subdirectory in there, removed
    when its build finishes; the default ``.build`` directory is removed as a
    whole, while a caller-supplied ``build_dir`` itself is left in place. On
    WSL the intermediates must live on a Windows volume (the MSVC tools run
    with their cwd inside them), which is what this override is for when
    ``out_dir`` is not on one.
    """
    out = out_dir if out_dir is not None else PREBUILT_DIR
    out.mkdir(parents=True, exist_ok=True)
    workdir = build_dir if build_dir is not None else out / ".build"
    try:
        if select is None:
            return _build_auto(workdir, out, log)

        unknown = [s for s in select if s not in SELECTORS]
        if unknown:
            raise ConfigError(
                f"unknown build-prebuilt target(s): {unknown} "
                f"(supported: {', '.join(SELECTORS)})"
            )
        exes: list[Path] = []
        seen: set[str] = set()
        for sel in select:
            if sel in seen:
                continue
            seen.add(sel)
            if sel == "macos":
                if sys.platform != "darwin":
                    raise BuildError(
                        "the macos prebuilt stub can only be built on a macOS host"
                    )
                exes.append(_build_macos(workdir, out, log))
            else:
                if not _windows_capable():
                    raise BuildError(
                        f"the {sel} prebuilt stubs can only be built on Windows, "
                        "or on WSL with Visual Studio"
                    )
                exes.extend(_build_windows_pair(TARGETS[sel], workdir, out, log))
        return exes
    finally:
        if build_dir is None:
            shutil.rmtree(workdir, ignore_errors=True)


def _build_auto(workdir: Path, out: Path, log) -> list[Path]:
    """Build what this host's toolchain allows; skip the rest with a message."""
    from .build import _find_vcvars

    if sys.platform == "darwin":
        if not shutil.which("clang"):
            log("skip: macos (clang not found; install the Xcode Command Line Tools)")
            return []
        return [_build_macos(workdir, out, log)]
    if _windows_capable():
        exes: list[Path] = []
        for target_name in _WINDOWS_TARGETS:
            target = TARGETS[target_name]
            try:
                _find_vcvars(target)
            except BuildError:
                log(f"skip: {target_name} (MSVC build tools for this target not found)")
                continue
            exes.extend(_build_windows_pair(target, workdir, out, log))
        return exes
    log(
        "skip: no launcher toolchain on this host (Windows or WSL with Visual "
        "Studio builds the .exe stubs, macOS the Mach-O stub)"
    )
    return []


def _windows_capable() -> bool:
    from .build import _vswhere_path

    return sys.platform == "win32" or _vswhere_path().is_file()


def _build_windows_pair(target: Target, workdir: Path, out: Path, log) -> list[Path]:
    """The console + gui stubs for one Windows platform."""
    from .build import _find_vcvars

    vcvars = _find_vcvars(target)
    return [
        _build_windows(target, gui, vcvars, workdir, out, log)
        for gui in (False, True)
    ]


def _build_windows(
    target: Target, gui: bool, vcvars: str, workdir: Path, out: Path, log
) -> Path:
    from .build import _LAUNCHER_C, run_msvc

    dest = out / windows_stub(target, gui).name
    log(f"prebuilt: build {dest.name}")
    # Build intermediates live under workdir (not the system temp dir): on WSL
    # the tools run through interop, and cmd.exe cannot use a Linux-filesystem
    # cwd — workdir is expected to be on a Windows volume there, exactly like
    # the rest of a cross-build tree.
    gen = workdir / dest.stem
    gen.mkdir(parents=True, exist_ok=True)
    try:
        (gen / "pyappdist_launcher_config.h").write_text(_STUB_HEADER, encoding="utf-8")
        shutil.copy2(_LAUNCHER_C, gen / "launcher.c")
        built = run_msvc(
            gen, vcvars, "WINDOWS" if gui else "CONSOLE", with_rc=False, label=dest.name
        )
        shutil.move(str(built), str(dest))
        return dest
    finally:
        shutil.rmtree(gen, ignore_errors=True)


def _build_macos(workdir: Path, out: Path, log) -> Path:
    from .build import _LAUNCHER_MAC_C

    if not shutil.which("clang"):
        raise BuildError("clang not found (install the Xcode Command Line Tools)")
    dest = out / macos_stub().name
    log(f"prebuilt: build {dest.name} ({'/'.join(_MACOS_ARCHS)})")
    gen = workdir / dest.stem
    gen.mkdir(parents=True, exist_ok=True)
    try:
        (gen / "pyappdist_launcher_config.h").write_text(_STUB_HEADER, encoding="utf-8")
        shutil.copy2(_LAUNCHER_MAC_C, gen / "launcher_mac.c")
        cmd = ["clang"]
        for arch in _MACOS_ARCHS:
            cmd += ["-arch", arch]
        cmd += [
            f"-mmacosx-version-min={MACOS_MIN}",
            "-O2", "-Wall", "-Wextra",
            "-I.",
            "-o", str(dest),
            "launcher_mac.c",
        ]
        proc = subprocess.run(
            cmd, cwd=str(gen), capture_output=True, text=True, errors="replace"
        )
        if proc.returncode != 0 or not dest.exists():
            raise BuildError(
                f"prebuilt launcher build failed ({dest.name}):\n"
                f"{proc.stdout}\n{proc.stderr}"
            )
        dest.chmod(0o755)
        return dest
    finally:
        shutil.rmtree(gen, ignore_errors=True)
