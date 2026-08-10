"""Build the launchers into the image (Windows .exe / macOS Mach-O).

Two paths produce the same result:

* **prebuilt** (the default): copy the compiler-less
  prebuilt stub and give it its per-app config — patched in as Windows
  resources (config blob, icon, VERSIONINFO; applied by ``patch_resources.py``
  run with the image's ``python.exe``) or written as a sidecar JSON next to
  the macOS stub. No MSVC / clang needed.
* **source**: compile ``launcher.c`` with MSVC (a vcvars script picked for the
  target architecture + cl.exe, invoked from WSL via cmd.exe, with a generated
  config header) or ``launcher_mac.c`` with clang.

The ``launcher-build`` target key ("prebuilt"/"source") picks between them.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import Config, LauncherConfig
from ..errors import BuildError
from ..image.layout import ImageLayout
from ..targets import Target
from . import winres
from .prebuilt import macos_stub, windows_stub

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"
_LAUNCHER_C = _RESOURCES / "launcher.c"
_LAUNCHER_MAC_C = _RESOURCES / "launcher_mac.c"
_PATCH_SCRIPT = _RESOURCES / "patch_resources.py"

# The bundled interpreter a launcher starts, relative to the launcher itself.
# A launcher with an icon gets its own copy instead (see _stage_app_python).
_PYEXE_GUI = "pythonw.exe"
_PYEXE_CONSOLE = "python.exe"

# Basename of the macOS sidecar config, written next to a prebuilt stub in the
# image dir as "<launcher>.launcher.json" and staged into each bundle as
# Contents/Resources/pyappdist-launcher.json (see CONFIG_REL in launcher_mac.c).
MAC_SIDECAR_NAME = "pyappdist-launcher.json"

# Path to the bundled interpreter relative to a .app's Contents/MacOS/<name>.
_MACOS_PYREL = "../Resources/python/bin/python3"

# build.bat's exit code when vcvars itself fails, distinct from the codes rc and cl
# produce (cl exits 2 on compile errors), so the failing step is unambiguous.
_VCVARS_EXIT = 97


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

    The launcher kind is chosen by the *format*, not just the OS: ``macapp``/``dmg``/``pkg``
    need a Mach-O stub for the ``.app`` bundle (built here with clang), while
    ``macos``/``linux`` (and ``image`` on a non-Windows target) use POSIX shell wrappers
    written by ``posix/build.py`` (so this returns ``[]`` for them). Windows — including
    ``image`` on a Windows target — is the MSVC ``launcher.exe`` path. ``no-launcher``
    (image format) skips launcher generation entirely.
    """
    if not config.launchers:
        log("launcher: none defined")
        return []
    if config.no_launcher:
        log("launcher: skipped (no-launcher)")
        return []
    if config.format in ("macapp", "dmg", "pkg"):
        return build_macos_launchers(config, layout, workdir, log=log)
    if config.target.os != "windows":
        log("launcher: skipping (shell-wrapper launchers are written by the posix builder)")
        return []
    workdir.mkdir(parents=True, exist_ok=True)
    # vcvars (i.e. a Visual Studio install) is only required when some launcher
    # actually compiles from source — a prebuilt build must work without MSVC.
    vcvars: str | None = None
    out: list[Path] = []
    for spec in config.launchers:
        stub = windows_stub(config.target, spec.gui)
        if _use_prebuilt(config, stub):
            out.append(_patch_prebuilt_windows(config, spec, layout, stub, workdir, log))
            continue
        if vcvars is None:
            vcvars = _find_vcvars(config.target)
        out.append(_build_one(config, spec, layout, vcvars, workdir, log))
    return out


def build_macos_launchers(
    config: Config, layout: ImageLayout, workdir: Path, *, log=print
) -> list[Path]:
    """One Mach-O launcher per spec into the image dir.

    Either the bundled prebuilt (universal) stub plus its sidecar config, or a
    clang compile native to the target. Each binary resolves the bundled python
    relative to its own location, so it is layout-independent at build time;
    the bundler relocates it (and the sidecar) into the ``.app``.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    stub = macos_stub()
    out: list[Path] = []
    for spec in config.launchers:
        if _use_prebuilt(config, stub):
            out.append(_prebuilt_one_macos(config, spec, layout, log))
        else:
            out.append(_build_one_macos(config, spec, layout, workdir, log))
    return out


def _use_prebuilt(config: Config, stub: Path) -> bool:
    """Whether to use the prebuilt stub, per the target's ``launcher-build`` key.

    "prebuilt" (the default) requires the bundled stub; "source" always
    compiles.
    """
    if config.launcher_build == "source":
        return False
    if stub.is_file():
        return True
    raise BuildError(
        f"this pyappdist installation does not bundle a prebuilt launcher for "
        f"the target ({stub.name}); install a released wheel, run "
        '`pyappdist build-prebuilt`, or use launcher-build = "source"'
    )


def _patch_prebuilt_windows(
    config: Config, spec: LauncherConfig, layout: ImageLayout,
    stub: Path, workdir: Path, log,
) -> Path:
    """Turn the prebuilt Windows stub into ``image/<name>.exe`` — no compiler.

    The stub is copied into the build dir and its per-app resources (config
    blob, optional icon, VERSIONINFO) are patched in by ``patch_resources.py``
    run with the image runtime's ``python.exe`` (already fetched by earlier
    stages), following the cwd + relative-path interop rule.
    """
    log(f"launcher: prebuilt {spec.name}.exe ({'gui' if spec.gui else 'console'})")
    gen = workdir / spec.name
    gen.mkdir(parents=True, exist_ok=True)
    built = gen / "launcher_out.exe"
    shutil.copy2(stub, built)

    pyexe = _stage_app_python(config, spec, layout, workdir, log)
    resources = [
        winres.config_resource(pyexe, _bootstrap(spec, config), _windows_fixed_args(spec))
    ]
    icon = _launcher_icon(config, spec)
    if icon:
        resources.extend(winres.icon_resources(icon.read_bytes()))
    resources.append(
        winres.version_resource(_version_quad_ints(config.version),
                                _version_strings(config, spec))
    )
    _patch_windows_resources(built, resources, gen, layout, spec.name)

    exe = layout.image_dir / f"{spec.name}.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(built), str(exe))
    return exe


def _launcher_icon(config: Config, spec: LauncherConfig) -> Path | None:
    """The launcher's Windows ``.ico``, or None when it declares no icon."""
    icon_rel = spec.icon_for("windows")
    if not icon_rel:
        return None
    icon = (config.project_dir / icon_rel).resolve()
    if not icon.is_file():
        raise BuildError(f"launcher icon not found ({spec.name}): {icon}")
    return icon


def _patch_windows_resources(
    exe: Path, resources: list[winres.Resource], gen: Path, layout: ImageLayout, label: str
) -> None:
    """Apply ``resources`` to ``exe`` with ``patch_resources.py``.

    The script, the payload files, and the manifest are staged next to ``exe``
    in ``gen`` and the image runtime's ``python.exe`` runs there, so every path
    stays relative (the WSL interop cwd rule). ``exe`` is always a copy inside
    ``gen`` — never the interpreter running the script, which Windows keeps
    locked while it executes.
    """
    entries = []
    for i, res in enumerate(resources):
        payload = f"res{i}.bin"
        (gen / payload).write_bytes(res.data)
        entries.append(
            {"type": res.type, "name": res.name, "lang": res.lang, "file": payload}
        )
    (gen / "patch_manifest.json").write_text(
        json.dumps({"exe": exe.name, "resources": entries}), encoding="utf-8"
    )
    shutil.copy2(_PATCH_SCRIPT, gen / "patch_resources.py")

    proc = subprocess.run(
        [str(layout.python_exe), "patch_resources.py", "patch_manifest.json"],
        cwd=str(gen), capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0:
        raise BuildError(
            f"launcher resource patching failed ({label}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def _stage_app_python(
    config: Config, spec: LauncherConfig, layout: ImageLayout, workdir: Path, log
) -> str:
    """Give the launcher its own copy of the interpreter, carrying its icon.

    The launcher only starts python and waits, so the process that owns the
    app's windows is that python — and Windows falls back to *its* executable
    icon for any window whose toolkit sets none. Shared ``python.exe`` /
    ``pythonw.exe`` therefore means every pyappdist app looks alike while
    running. Copying the interpreter per launcher and patching the launcher's
    icon (plus VERSIONINFO, so Task Manager names the app) into the copy fixes
    that; the copy is a byte-for-byte interpreter otherwise, so ``sys.executable``
    stays a real python and ``multiprocessing`` children inherit the icon too.

    Toolkits that install their own window-class icon (Tk's feather) are
    unaffected — those apps must set the icon themselves.

    Returns the interpreter path relative to the launcher. Without an icon
    there is nothing to patch, so the shared interpreter is used as before.
    """
    base = _PYEXE_GUI if spec.gui else _PYEXE_CONSOLE
    icon = _launcher_icon(config, spec)
    if icon is None:
        return f"python\\{base}"

    name = f"{spec.name}.exe"
    if name.lower() in (_PYEXE_GUI, _PYEXE_CONSOLE):
        # A launcher literally named "python"/"pythonw" would overwrite the
        # interpreter it was copied from.
        name = f"{spec.name}_app.exe"
    rel = f"python\\{name}"
    log(f"launcher: {rel} (interpreter copy carrying the {spec.name} icon)")

    gen = workdir / spec.name / "pyexe"
    gen.mkdir(parents=True, exist_ok=True)
    built = gen / "pyexe_out.exe"
    shutil.copy2(layout.python_dir / base, built)

    # Group id 1 is what Explorer and the "window with no icon" fallback use;
    # the Qt alias reaches Qt/PySide windows. Both name the same RT_ICON ids,
    # which overwrite the interpreter's own — any icon image it had beyond ours
    # stays behind unreferenced, since only the group directory is consulted.
    resources = winres.icon_resources(
        icon.read_bytes(), group_names=(1, winres.QT_ICON_NAME)
    )
    strings = _version_strings(config, spec)
    strings["OriginalFilename"] = name
    resources.append(
        winres.version_resource(_version_quad_ints(config.version), strings)
    )
    _patch_windows_resources(built, resources, gen, layout, f"{spec.name} interpreter")

    shutil.move(str(built), str(layout.python_dir / name))
    return rel


def _mac_sidecar(image_dir: Path, name: str) -> Path:
    return image_dir / f"{name}.launcher.json"


def _prebuilt_one_macos(
    config: Config, spec: LauncherConfig, layout: ImageLayout, log
) -> Path:
    """Copy the prebuilt universal stub and write its sidecar config.

    The stub itself stays byte-identical for every app (it is re-signed later
    with the rest of the bundle); the per-app values go into a JSON the bundler
    stages as ``Contents/Resources/pyappdist-launcher.json``, sealed by the
    bundle's code signature. The prebuilt stub targets macOS 11.0+ regardless
    of ``min-macos`` (which still sets LSMinimumSystemVersion).
    """
    log(f"launcher: prebuilt {spec.name} (macos universal)")
    exe = layout.image_dir / spec.name
    exe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(macos_stub(), exe)
    exe.chmod(0o755)
    sidecar = {
        "pyrel": _MACOS_PYREL,
        "bootstrap": spec.bootstrap,
        "args": list(spec.argv),
    }
    _mac_sidecar(layout.image_dir, spec.name).write_text(
        json.dumps(sidecar, ensure_ascii=True), encoding="utf-8"
    )
    return exe


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
        f"#define PYAPPDIST_FIXED_ARGS {_fixed_args_initializer(spec)}\n"
    )
    (gen / "pyappdist_launcher_config.h").write_text(header, encoding="utf-8")
    # Stage launcher_mac.c next to the generated header so clang runs with cwd=gen.
    shutil.copy2(_LAUNCHER_MAC_C, gen / "launcher_mac.c")

    # A stale sidecar from an earlier prebuilt build would override the
    # compiled-in config (the launcher prefers the sidecar when present).
    _mac_sidecar(layout.image_dir, spec.name).unlink(missing_ok=True)

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


def _fixed_args_initializer(spec: LauncherConfig) -> str:
    """The launcher's fixed args as a NULL-terminated C array initializer."""
    items = "".join(f'"{_c_str(arg)}", ' for arg in spec.argv)
    return "{ " + items + "NULL }"


def _windows_fixed_args(spec: LauncherConfig) -> str:
    """The launcher's fixed args as one MSVC-quoted command-line fragment.

    launcher.c appends this verbatim, so it must already be quoted the way the child's
    argv parsing will read it back — otherwise the raw ``args`` string would be
    re-split by MSVC rules and mean something different than it does for the shell
    wrapper and the macOS stub.
    """
    return " ".join(msvc_quote(arg) for arg in spec.argv)


def msvc_quote(arg: str) -> str:
    """Quote one argument the way ``CommandLineToArgvW`` will parse it back.

    Mirrors ``append_quoted`` in launcher.c: only backslashes immediately before a
    quote are doubled, and the run before the closing quote is doubled too.
    """
    if arg and not any(c in ' \t"' for c in arg):
        return arg
    out = ['"']
    backslashes = 0
    for ch in arg:
        if ch == "\\":
            backslashes += 1
            continue
        if ch == '"':
            out.append("\\" * (backslashes * 2 + 1) + '"')
        else:
            out.append("\\" * backslashes + ch)
        backslashes = 0
    out.append("\\" * (backslashes * 2) + '"')
    return "".join(out)


def _build_one(
    config: Config, spec: LauncherConfig, layout: ImageLayout,
    vcvars: str, workdir: Path, log,
) -> Path:
    log(f"launcher: build {spec.name}.exe ({'gui' if spec.gui else 'console'})")
    gen = workdir / spec.name
    gen.mkdir(parents=True, exist_ok=True)

    pyexe = _stage_app_python(config, spec, layout, workdir, log)
    fixed_args = _windows_fixed_args(spec)
    header = (
        f"#define PYAPPDIST_PYEXE L\"{_c_str(pyexe)}\"\n"
        f"#define PYAPPDIST_BOOTSTRAP L\"{_c_str(_bootstrap(spec, config))}\"\n"
        f"#define PYAPPDIST_FIXED_ARGS L\"{_c_str(fixed_args)}\"\n"
    )
    # Write as UTF-8. With cl's /utf-8, non-ASCII in the source is read correctly,
    # and L"..." compiles to wide (UTF-16) literals.
    (gen / "pyappdist_launcher_config.h").write_text(header, encoding="utf-8")

    # Stage the bundled launcher.c into the build dir so every cl/rc input lives
    # alongside the generated files; the tools then run with cwd=gen and need only
    # relative paths (no wslpath conversion across the Linux/Windows boundary).
    shutil.copy2(_LAUNCHER_C, gen / "launcher.c")

    # Every cl/rc input and output uses a fixed ASCII basename so build.bat — and
    # the command lines cmd.exe parses out of it — stay pure ASCII no matter what
    # the launcher (or app) name is. The non-ASCII final name is applied by Python
    # afterwards via a rename, which handles Unicode filenames natively; this avoids
    # `chcp 65001` / console-codepage games inside the batch entirely. The .rc still
    # carries non-ASCII resource strings, but through its own UTF-8 encoding plus a
    # `#pragma code_page(65001)` (see _render_rc), independent of the console.
    (gen / "launcher.rc").write_text(_render_rc(config, spec, gen), encoding="utf-8")

    exe = layout.image_dir / f"{spec.name}.exe"
    subsystem = "WINDOWS" if spec.gui else "CONSOLE"
    built = run_msvc(gen, vcvars, subsystem, with_rc=True, label=spec.name)
    exe.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(built), str(exe))
    return exe


def run_msvc(
    gen: Path, vcvars: str, subsystem: str, *, with_rc: bool, label: str
) -> Path:
    """Compile the staged ``launcher.c`` (+ optional ``launcher.rc``) with MSVC.

    ``gen`` must already contain ``launcher.c``, ``pyappdist_launcher_config.h``,
    and — with ``with_rc`` — ``launcher.rc`` plus its inputs. Returns the built
    ``gen/launcher_out.exe``. Shared by the per-app source build and the
    prebuilt-stub builder (which compiles without resources).
    """
    # vcvars64.bat's path is passed as an argument rather than embedded, so the batch
    # file itself stays pure ASCII even when the VS install path contains non-ASCII
    # (cmd.exe receives argv as Unicode through interop; batch file bytes are read in
    # an unpredictable console codepage).
    # Remove any launcher.res left by a previous run: the gen dir is reused across
    # incremental builds, and a stale .res would let cl link successfully even if
    # rc failed, shipping the previous icon/VERSIONINFO.
    (gen / "launcher.res").unlink(missing_ok=True)

    bat = gen / "build.bat"
    lines = [
        "@echo off",
        # Only vcvars' stdout is silenced; its diagnostics still reach stderr and end
        # up in the BuildError below. Without the errorlevel check a failed vcvars
        # (a broken VS install, say) went unnoticed and surfaced one step later as
        # "'rc' is not recognized", pointing at the wrong cause. The distinct exit
        # code lets the Python side name the real one.
        'call %1 >nul',
        f"if errorlevel 1 exit /b {_VCVARS_EXIT}",
    ]
    if with_rc:
        lines += [
            'rc /nologo /fo "launcher.res" "launcher.rc"',
            "if errorlevel 1 exit /b 1",
        ]
    lines.append(
        'cl /nologo /O2 /W3 /utf-8 /I"." '
        '"launcher.c" '
        + ('"launcher.res" ' if with_rc else "")
        + '/Fe:"launcher_out.exe" '
        '/Fo:"launcher.obj" '
        f"/link /SUBSYSTEM:{subsystem} Shell32.lib"
    )
    bat.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")

    # Use an explicit ".\" path: when Windows has NoDefaultCurrentDirectoryInExePath
    # set, cmd.exe will not search the current directory for "build.bat" and the
    # launch fails. ".\build.bat" forces resolution relative to cwd=gen.
    # The path argument is quoted by the subprocess layer when it contains spaces, and
    # %1 in the batch keeps those quotes, so `call %1` resolves it verbatim.
    proc = subprocess.run(
        ["cmd.exe", "/c", r".\build.bat", vcvars],
        cwd=str(gen),
        capture_output=True, text=True, errors="replace",
    )
    built = gen / "launcher_out.exe"
    if proc.returncode == _VCVARS_EXIT:
        raise BuildError(
            f"the Visual Studio environment script failed: {vcvars}\n"
            "(the MSVC toolchain was never set up, so cl/rc could not run; "
            "check the Visual Studio installation)\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    if proc.returncode != 0 or not built.exists():
        raise BuildError(
            f"launcher build failed ({label}):\n{proc.stdout}\n{proc.stderr}"
        )
    return built


def _render_rc(config: Config, spec: LauncherConfig, gen: Path) -> str:
    """Generate the .rc with icon (optional) + VERSIONINFO.

    The icon is staged into ``gen`` (the rc compiler's cwd) and referenced by
    name, so the source tree's location never needs path conversion.

    The file is written as UTF-8 (see _build_one) and opens with
    ``#pragma code_page(65001)`` so rc.exe reads non-ASCII resource strings
    (app/file names) correctly without depending on the console codepage.
    """
    # Must precede any string data so rc.exe decodes the rest of the file as UTF-8.
    parts: list[str] = ["#pragma code_page(65001)"]
    icon = _launcher_icon(config, spec)
    if icon:
        shutil.copy2(icon, gen / icon.name)
        parts.append(f'1 ICON "{_c_str(icon.name)}"')

    quad = ",".join(str(n) for n in _version_quad_ints(config.version))
    strings = _version_strings(config, spec)
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
                *(
                    f'      VALUE "{key}", "{_rc_str(value)}"'
                    for key, value in strings.items()
                ),
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


def _version_strings(config: Config, spec: LauncherConfig) -> dict[str, str]:
    """The StringFileInfo values, shared by the .rc and the patched VERSIONINFO."""
    company = config.wix.manufacturer or config.name
    return {
        "CompanyName": company,
        "FileDescription": config.name,
        "FileVersion": config.version,
        "ProductName": config.name,
        "ProductVersion": config.version,
        "OriginalFilename": f"{spec.name}.exe",
    }


def _version_quad_ints(version: str) -> tuple[int, int, int, int]:
    """"1.2.3" -> (1, 2, 3, 0) (ignore non-digits, pad to 4 elements)."""
    nums: list[int] = []
    for token in version.split("."):
        digits = "".join(c for c in token if c.isdigit())
        nums.append(int(digits) if digits else 0)
    nums = (nums + [0, 0, 0, 0])[:4]
    return (nums[0], nums[1], nums[2], nums[3])


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

    # A Python string literal of the app name: repr() escapes quotes/backslashes so an
    # arbitrary name can't break the generated source (Unicode passes through as-is,
    # the header is UTF-8).
    title = repr(config.name)
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


def _vcvars_candidates(target: Target) -> list[str]:
    """vcvars script basenames for ``target``, in preference order.

    MSVC ships one script per host/target pair. For an arm64 target on an arm64
    host the native ``vcvarsarm64.bat`` is preferred, but the x64-hosted cross
    compiler (``vcvarsamd64_arm64.bat``) also runs there under emulation, so it
    is kept as a fallback for VS installs without the arm64-hosted tools. The
    host is the machine actually running cl.exe — on WSL that is the Windows
    side, whose architecture matches the WSL kernel's (``platform.machine()``).
    """
    if target.wix_arch == "arm64":
        host_arm64 = platform.machine().lower() in ("arm64", "aarch64")
        if host_arm64:
            return ["vcvarsarm64.bat", "vcvarsamd64_arm64.bat"]
        return ["vcvarsamd64_arm64.bat"]
    return ["vcvars64.bat"]


def _find_vcvars(target: Target) -> str:
    vswhere = _vswhere_path()
    if not vswhere.is_file():
        raise BuildError(f"vswhere not found: {vswhere}")
    # The arm64 compilers are their own optional VS component, distinct from the
    # x86/x64 one the x64 target needs.
    component = (
        "Microsoft.VisualStudio.Component.VC.Tools.ARM64"
        if target.wix_arch == "arm64"
        else "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"
    )
    # Mirror setuptools' MSVC discovery (_distutils/compilers/C/msvc.py):
    #   -products *    also matches the standalone "C++ Build Tools" SKU
    #                  (bare -latest excludes it; common on CI/build machines)
    #   -requires ...  only an install with the C++ compiler workload, so the
    #                  returned path actually has the vcvars script
    #   -prerelease    also matches preview / Insiders channels
    proc = subprocess.run(
        [
            str(vswhere), "-latest", "-prerelease", "-products", "*",
            "-requires", component,
            "-property", "installationPath",
        ],
        capture_output=True, text=True, errors="replace",
    )
    install = proc.stdout.strip()
    if not install:
        raise BuildError(
            "Visual Studio C++ build tools not found. Install the "
            '"Desktop development with C++" workload or the standalone '
            f"Build Tools (vswhere found no install with the {component} "
            "component)."
        )
    # Keep the native Windows path (with backslashes) for build.bat's `call`,
    # which runs under cmd.exe on the Windows side. The existence check must use
    # the host-side path, since on WSL the C:\... string is not a real Linux path.
    names = _vcvars_candidates(target)
    for name in names:
        vcvars = install + r"\VC\Auxiliary\Build" + "\\" + name
        if _to_host_path(vcvars).is_file():
            return vcvars
    raise BuildError(
        f"no vcvars script ({' / '.join(names)}) found under the VS install: "
        f"{install}"
    )
