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
from ..targets import Target

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"
_LAUNCHER_C = _RESOURCES / "launcher.c"
_LAUNCHER_MAC_C = _RESOURCES / "launcher_mac.c"

# Path to the bundled interpreter relative to a .app's Contents/MacOS/<name>.
_MACOS_PYREL = "../Resources/python/bin/python3"


def _vswhere_path() -> Path:
    """Location of vswhere.exe (supports both native Windows and WSL)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    else:
        base = Path("/mnt/c/Program Files (x86)")
    return base / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


def _to_host_path(win_path: str) -> Path:
    """Map a Windows path (e.g. from vswhere) to a path the host can stat.

    On native Windows it is unchanged; on WSL ``C:\\...`` becomes ``/mnt/c/...``
    (same drive-mount assumption as :func:`_vswhere_path`).
    """
    if sys.platform == "win32":
        return Path(win_path)
    p = win_path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        return Path(f"/mnt/{p[0].lower()}") / p[3:]
    return Path(p)


def build_launchers(config: Config, layout: ImageLayout, workdir: Path, *, log=print) -> list[Path]:
    """Compile one launcher per spec into the image dir.

    The launcher kind is chosen by the *format*, not just the OS: ``macapp``/``dmg`` need a
    Mach-O stub for the ``.app`` bundle (built here with clang), while ``macos``/``linux``
    use POSIX shell wrappers written by ``posix/build.py`` (so this returns ``[]`` for
    them). Windows is the MSVC ``launcher.exe`` path.
    """
    if not config.launchers:
        log("launcher: none defined")
        return []
    if config.format in ("macapp", "dmg"):
        return build_macos_launchers(config, layout, workdir, log=log)
    if config.target.os != "windows":
        log("launcher: skipping (shell-wrapper launchers are written by the posix builder)")
        return []
    vcvars = _find_vcvars()
    workdir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for spec in config.launchers:
        out.append(_build_one(config, spec, layout, vcvars, workdir, log))
    return out


def build_macos_launchers(
    config: Config, layout: ImageLayout, workdir: Path, *, log=print
) -> list[Path]:
    """Compile one Mach-O launcher per spec into the image dir (clang, native to the target).

    Each binary resolves the bundled python relative to its own location, so it is
    layout-independent at build time; the bundler relocates it into the ``.app``.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    return [_build_one_macos(config, spec, layout, workdir, log) for spec in config.launchers]


def _build_one_macos(
    config: Config, spec: LauncherConfig, layout: ImageLayout, workdir: Path, log
) -> Path:
    arch = macos_arch(config.target)
    log(f"launcher: build {spec.name} (macos {arch})")
    gen = workdir / spec.name
    gen.mkdir(parents=True, exist_ok=True)

    # macOS has no console/gui subsystem split, so the plain bootstrap is used for both
    # (a native error dialog for gui launchers is a later refinement).
    header = (
        f'#define PYAPPDIST_PYREL "{_c_str(_MACOS_PYREL)}"\n'
        f'#define PYAPPDIST_BOOTSTRAP "{_c_str(spec.bootstrap)}"\n'
        f"#define PYAPPDIST_FIXED_ARGS {_fixed_args_initializer(spec.args)}\n"
    )
    (gen / "pyappdist_launcher_config.h").write_text(header, encoding="utf-8")
    # Stage launcher_mac.c next to the generated header so clang runs with cwd=gen.
    shutil.copy2(_LAUNCHER_MAC_C, gen / "launcher_mac.c")

    exe = layout.image_dir / spec.name
    cmd = [
        "clang",
        "-arch", arch,
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
    exe.chmod(0o755)
    return exe


def macos_arch(target: Target) -> str:
    """clang -arch value from the target triple (aarch64-apple-darwin -> arm64)."""
    machine = target.triple.split("-", 1)[0]
    return "arm64" if machine == "aarch64" else machine


def _fixed_args_initializer(args: str) -> str:
    """POSIX-split fixed args into a NULL-terminated C array initializer."""
    import shlex

    items = "".join(f'"{_c_str(p)}", ' for p in shlex.split(args))
    return "{ " + items + "NULL }"


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

    # Use an explicit ".\" path: when Windows has NoDefaultCurrentDirectoryInExePath
    # set, cmd.exe will not search the current directory for "build.bat" and the
    # launch fails. ".\build.bat" forces resolution relative to cwd=gen.
    proc = subprocess.run(
        ["cmd.exe", "/c", r".\build.bat"],
        cwd=str(gen),
        capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0 or not exe.exists():
        raise BuildError(
            f"launcher build failed ({spec.name}):\n{proc.stdout}\n{proc.stderr}"
        )
    return exe


def _render_rc(config: Config, spec: LauncherConfig, gen: Path) -> str:
    """Generate the .rc with icon (optional) + VERSIONINFO.

    The icon is staged into ``gen`` (the rc compiler's cwd) and referenced by
    name, so the source tree's location never needs path conversion.
    """
    parts: list[str] = []
    icon_rel = spec.icon_for("windows")
    if icon_rel:
        icon = (config.project_dir / icon_rel).resolve()
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
    ``func()`` runs are the app's responsibility. The MessageBox wrapper applies
    only to the ``"module:callable"`` form; a dotted ``"module.path"`` (python -m)
    entry uses the shared bootstrap verbatim.
    """
    if not spec.gui or ":" not in spec.entry:
        return spec.bootstrap
    module, _, func = spec.entry.partition(":")

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
    # Mirror setuptools' MSVC discovery (_distutils/compilers/C/msvc.py):
    #   -products *    also matches the standalone "C++ Build Tools" SKU
    #                  (bare -latest excludes it; common on CI/build machines)
    #   -requires ...  only an install with the C++ compiler workload, so the
    #                  returned path actually has vcvars64.bat
    #   -prerelease    also matches preview / Insiders channels
    proc = subprocess.run(
        [
            str(vswhere), "-latest", "-prerelease", "-products", "*",
            "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property", "installationPath",
        ],
        capture_output=True, text=True, errors="replace",
    )
    install = proc.stdout.strip()
    if not install:
        raise BuildError(
            "Visual Studio C++ build tools not found. Install the "
            '"Desktop development with C++" workload or the standalone '
            "Build Tools (vswhere found no install with the "
            "VC.Tools.x86.x64 component)."
        )
    # Keep the native Windows path (with backslashes) for build.bat's `call`,
    # which runs under cmd.exe on the Windows side. The existence check must use
    # the host-side path, since on WSL the C:\... string is not a real Linux path.
    vcvars = install + r"\VC\Auxiliary\Build\vcvars64.bat"
    if not _to_host_path(vcvars).is_file():
        raise BuildError(f"vcvars64.bat not found under the VS install: {vcvars}")
    return vcvars
