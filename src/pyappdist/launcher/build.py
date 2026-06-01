"""Build launcher.exe with MSVC (Windows target).

vcvars64.bat + cl.exe are invoked from WSL via cmd.exe. A config header is
generated per launcher, and the same launcher.c is compiled with different
subsystems.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .._hostexec import target_relpath
from ..config import Config, LauncherConfig
from ..errors import BuildError
from ..image.layout import ImageLayout

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"
_LAUNCHER_C = _RESOURCES / "launcher.c"
_LAUNCHER_MAC_C = _RESOURCES / "launcher_mac.c"


def _vswhere_path() -> Path:
    """Location of vswhere.exe (supports both native Windows and WSL)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    else:
        base = Path("/mnt/c/Program Files (x86)")
    return base / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


def build_launchers(config: Config, layout: ImageLayout, workdir: Path, *, log=print) -> list[Path]:
    if not config.launchers:
        log("launcher: none defined")
        return []
    if config.target.os == "macos":
        return build_macos_launchers(config, layout, workdir, log=log)
    if config.target.os != "windows":
        log("launcher: skipping (non-Windows target)")
        return []
    vcvars = _find_vcvars()
    workdir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for spec in config.launchers:
        out.append(_build_one(config, spec, layout, vcvars, workdir, log))
    return out


def _build_one(
    config: Config, spec: LauncherConfig, layout: ImageLayout,
    vcvars: str, workdir: Path, log,
) -> Path:
    log(f"launcher: build {spec.name}.exe ({'gui' if spec.gui else 'console'})")
    gen = workdir / spec.name
    gen.mkdir(parents=True, exist_ok=True)

    pyexe = "python\\pythonw.exe" if spec.gui else "python\\python.exe"
    header = (
        f"#define PYAPPDIST_PYEXE L\"{_c_str(pyexe)}\"\n"
        f"#define PYAPPDIST_BOOTSTRAP L\"{_c_str(_bootstrap(spec, config))}\"\n"
        f"#define PYAPPDIST_FIXED_ARGS L\"{_c_str(spec.args)}\"\n"
    )
    # Write as UTF-8. With cl's /utf-8, non-ASCII in the source is read correctly,
    # and L"..." compiles to wide (UTF-16) literals.
    (gen / "pyappdist_launcher_config.h").write_text(header, encoding="utf-8")

    # Stage the bundled launcher.c into the build dir so every cl/rc input lives
    # alongside the generated files; the tools then run with cwd=gen and need only
    # relative paths (no wslpath conversion across the Linux/Windows boundary).
    shutil.copy2(_LAUNCHER_C, gen / "launcher.c")

    rc = gen / f"{spec.name}.rc"
    rc.write_text(_render_rc(config, spec, gen), encoding="ascii")

    exe = layout.image_dir / f"{spec.name}.exe"
    subsystem = "WINDOWS" if spec.gui else "CONSOLE"

    bat = gen / "build.bat"
    lines = [
        "@echo off",
        f'call "{vcvars}" >nul',
        f'rc /nologo /fo "{spec.name}.res" "{spec.name}.rc"',
        (
            f'cl /nologo /O2 /W3 /utf-8 /I"." '
            f'"launcher.c" '
            f'"{spec.name}.res" '
            f'/Fe:"{target_relpath(config.target, exe, gen)}" '
            f'/Fo:"{spec.name}.obj" '
            f"/link /SUBSYSTEM:{subsystem} Shell32.lib"
        ),
    ]
    bat.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")

    proc = subprocess.run(
        ["cmd.exe", "/c", "build.bat"],
        cwd=str(gen),
        capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0 or not exe.exists():
        raise BuildError(
            f"launcher build failed ({spec.name}):\n{proc.stdout}\n{proc.stderr}"
        )
    return exe


# --- macOS (clang) ---------------------------------------------------------

# The bundled python relative to Contents/MacOS/<name>; the bundler (macos/bundle.py)
# places the launcher there and the runtime under Contents/Resources/python.
_MACOS_PYREL = "../Resources/python/bin/python3"


def build_macos_launchers(
    config: Config, layout: ImageLayout, workdir: Path, *, log=print
) -> list[Path]:
    """Compile one Mach-O launcher per spec into the image dir (native arm64, clang).

    The binaries resolve the bundled python relative to their own location, so they
    are layout-independent at build time; the bundler relocates them into the .app.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    return [_build_one_macos(config, spec, layout, workdir, log) for spec in config.launchers]


def _build_one_macos(
    config: Config, spec: LauncherConfig, layout: ImageLayout, workdir: Path, log
) -> Path:
    log(f"launcher: build {spec.name} (macos)")
    gen = workdir / spec.name
    gen.mkdir(parents=True, exist_ok=True)

    # macOS has no console/gui subsystem split, so the plain bootstrap is used for
    # both (a native error dialog for gui launchers is a later refinement).
    module, _, func = spec.entry.partition(":")
    bootstrap = f"import sys; from {module} import {func}; sys.exit({func}())"
    header = (
        f'#define PYAPPDIST_PYREL "{_c_str(_MACOS_PYREL)}"\n'
        f'#define PYAPPDIST_BOOTSTRAP "{_c_str(bootstrap)}"\n'
        f"#define PYAPPDIST_FIXED_ARGS {_fixed_args_initializer(spec.args)}\n"
    )
    (gen / "pyappdist_launcher_config.h").write_text(header, encoding="utf-8")
    shutil.copy2(_LAUNCHER_MAC_C, gen / "launcher_mac.c")

    exe = layout.image_dir / spec.name
    cmd = [
        "clang",
        "-arch", "arm64",
        f"-mmacosx-version-min={config.macos.min_macos}",
        "-O2", "-Wall", "-Wextra",
        "-I.",
        "-o", str(exe),
        "launcher_mac.c",
    ]
    proc = subprocess.run(
        cmd, cwd=str(gen), capture_output=True, text=True, errors="replace"
    )
    if proc.returncode != 0 or not exe.exists():
        raise BuildError(
            f"launcher build failed ({spec.name}):\n{proc.stdout}\n{proc.stderr}"
        )
    return exe


def _fixed_args_initializer(args: str) -> str:
    """POSIX-split fixed args into a NULL-terminated C array initializer."""
    import shlex

    parts = shlex.split(args)
    items = "".join(f'"{_c_str(p)}", ' for p in parts)
    return "{ " + items + "NULL }"


def _render_rc(config: Config, spec: LauncherConfig, gen: Path) -> str:
    """Generate the .rc with icon (optional) + VERSIONINFO.

    The icon is staged into ``gen`` (the rc compiler's cwd) and referenced by
    name, so the source tree's location never needs path conversion.
    """
    parts: list[str] = []
    if spec.icon:
        icon = (config.project_dir / spec.icon).resolve()
        if not icon.is_file():
            raise BuildError(f"launcher icon not found ({spec.name}): {icon}")
        shutil.copy2(icon, gen / icon.name)
        parts.append(f'1 ICON "{_c_str(icon.name)}"')

    quad = _version_quad(config.version)
    company = config.wix.manufacturer or config.name
    parts.append(
        "\n".join(
            [
                "1 VERSIONINFO",
                f"FILEVERSION {quad}",
                f"PRODUCTVERSION {quad}",
                "FILEFLAGSMASK 0x3fL",
                "FILEFLAGS 0x0L",
                "FILEOS 0x40004L",
                "FILETYPE 0x1L",
                "FILESUBTYPE 0x0L",
                "BEGIN",
                '  BLOCK "StringFileInfo"',
                "  BEGIN",
                '    BLOCK "040904b0"',
                "    BEGIN",
                f'      VALUE "CompanyName", "{_rc_str(company)}"',
                f'      VALUE "FileDescription", "{_rc_str(config.name)}"',
                f'      VALUE "FileVersion", "{_rc_str(config.version)}"',
                f'      VALUE "ProductName", "{_rc_str(config.name)}"',
                f'      VALUE "ProductVersion", "{_rc_str(config.version)}"',
                f'      VALUE "OriginalFilename", "{_rc_str(spec.name)}.exe"',
                "    END",
                "  END",
                '  BLOCK "VarFileInfo"',
                "  BEGIN",
                "    VALUE \"Translation\", 0x409, 1200",
                "  END",
                "END",
            ]
        )
    )
    return "\n".join(parts) + "\n"


def _version_quad(version: str) -> str:
    """"1.2.3" -> "1,2,3,0" (ignore non-digits, pad to 4 elements)."""
    nums: list[int] = []
    for token in version.split("."):
        digits = "".join(c for c in token if c.isdigit())
        nums.append(int(digits) if digits else 0)
    nums = (nums + [0, 0, 0, 0])[:4]
    return ",".join(str(n) for n in nums)


def _rc_str(s: str) -> str:
    """Escape for .rc string literals (backslashes and quotes)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _bootstrap(spec: LauncherConfig, config: Config) -> str:
    """Generate the ``-c`` program passed to python.

    console: simply import and call (exceptions surface on the console).
    gui: only the retrieval (import) of the entry function is wrapped in
    try/except; on failure a MessageBox shows a concise cause. Exceptions after
    ``func()`` runs are the app's responsibility.
    """
    module, _, func = spec.entry.partition(":")
    if not spec.gui:
        return f"import sys; from {module} import {func}; sys.exit({func}())"

    title = f'"{config.name}"'  # embed Unicode as-is (the header is UTF-8)
    return "\n".join(
        [
            "import sys",
            "try:",
            f"    from {module} import {func}",
            "except Exception as e:",
            "    import ctypes, traceback",
            "    ctypes.windll.user32.MessageBoxW(None, "
            f'"".join(traceback.format_exception_only(type(e), e)), {title}, 0x10)',
            "    sys.exit(1)",
            f"sys.exit({func}())",
        ]
    )


def _c_str(s: str) -> str:
    # Backslash first. Also escape newlines etc. to fit a multi-line bootstrap into a single-line L"...".
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _find_vcvars() -> str:
    vswhere = _vswhere_path()
    if not vswhere.is_file():
        raise BuildError(f"vswhere not found: {vswhere}")
    proc = subprocess.run(
        [str(vswhere), "-latest", "-property", "installationPath"],
        capture_output=True, text=True, errors="replace",
    )
    install = proc.stdout.strip()
    if not install:
        raise BuildError("Visual Studio (C++ tools) not found")
    return install + r"\VC\Auxiliary\Build\vcvars64.bat"
