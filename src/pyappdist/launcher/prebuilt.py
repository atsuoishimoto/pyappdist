"""Prebuilt launcher stubs: lookup and the ``build-prebuilt`` implementation.

Released wheels bundle compiler-less launcher stubs under
``resources/prebuilt/`` — one Windows ``.exe`` per (architecture, subsystem)
and one universal macOS Mach-O. ``build-launchers`` prefers them (see
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
from pathlib import Path

from ..errors import BuildError
from ..targets import TARGETS, Target

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"
PREBUILT_DIR = _RESOURCES / "prebuilt"

# The prebuilt Mach-O is built for both architectures with this deployment
# target; a source build honors the target's min-macos instead.
MACOS_MIN = "11.0"
_MACOS_ARCHS = ("arm64", "x86_64")

_WINDOWS_TARGETS = ("windows-x86_64", "windows-arm64")

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


def build_prebuilt(out_dir: Path | None = None, *, log=print) -> list[Path]:
    """Compile every prebuilt stub this host can produce into ``out_dir``.

    Windows (native, or WSL with Visual Studio): the four ``.exe`` stubs
    ({x86_64, arm64} x {console, gui}; arm64 uses the x64-hosted cross
    compiler). macOS: the single universal Mach-O. Defaults to the installed
    package's ``resources/prebuilt/`` so a subsequent build picks the stubs up.
    """
    from .build import _find_vcvars, _vswhere_path

    out = out_dir if out_dir is not None else PREBUILT_DIR
    out.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        return [_build_macos(out, log)]
    if sys.platform == "win32" or _vswhere_path().is_file():
        # Build intermediates live under the output dir (not the system temp
        # dir): on WSL the tools run through interop, and cmd.exe cannot use a
        # Linux-filesystem cwd — the output dir is expected to be on a Windows
        # volume there, exactly like the rest of a cross-build tree.
        workdir = out / ".build"
        try:
            exes = []
            for target_name in _WINDOWS_TARGETS:
                target = TARGETS[target_name]
                vcvars = _find_vcvars(target)
                for gui in (False, True):
                    exes.append(
                        _build_windows(target, gui, vcvars, workdir, out, log)
                    )
            return exes
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    raise BuildError(
        "build-prebuilt must run on a host with a launcher toolchain: Windows "
        "(or WSL with Visual Studio) for the .exe stubs, macOS for the Mach-O stub"
    )


def _build_windows(
    target: Target, gui: bool, vcvars: str, workdir: Path, out: Path, log
) -> Path:
    from .build import _LAUNCHER_C, run_msvc

    dest = out / windows_stub(target, gui).name
    log(f"prebuilt: build {dest.name}")
    gen = workdir / dest.stem
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "pyappdist_launcher_config.h").write_text(_STUB_HEADER, encoding="utf-8")
    shutil.copy2(_LAUNCHER_C, gen / "launcher.c")
    built = run_msvc(
        gen, vcvars, "WINDOWS" if gui else "CONSOLE", with_rc=False, label=dest.name
    )
    shutil.move(str(built), str(dest))
    return dest


def _build_macos(out: Path, log) -> Path:
    from .build import _LAUNCHER_MAC_C

    dest = out / macos_stub().name
    log(f"prebuilt: build {dest.name} ({'/'.join(_MACOS_ARCHS)})")
    gen = out / ".build"
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
