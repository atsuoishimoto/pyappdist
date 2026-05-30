"""launcher.exe を MSVC でビルドする (Windows ターゲット)。

WSL から vcvars64.bat + cl.exe を cmd.exe 経由で呼ぶ。各 launcher ごとに
設定ヘッダを生成し、同一の launcher.c をサブシステムを変えてコンパイルする。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .._hostexec import target_path
from ..config import Config, LauncherConfig
from ..errors import BuildError
from ..image.layout import ImageLayout

_LAUNCHER_C = Path(__file__).resolve().parent.parent / "resources" / "launcher.c"


def _vswhere_path() -> Path:
    """vswhere.exe の位置（ネイティブ Windows / WSL 双方対応）。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    else:
        base = Path("/mnt/c/Program Files (x86)")
    return base / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


def build_launchers(config: Config, layout: ImageLayout, workdir: Path, *, log=print) -> list[Path]:
    if config.target.os != "windows":
        log("launcher: 非 Windows ターゲットのためスキップ")
        return []
    if not config.launchers:
        log("launcher: 定義なし")
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
        f"#define PYAPPDIST_BOOTSTRAP L\"{_c_str(_bootstrap(spec.entry))}\"\n"
        f"#define PYAPPDIST_FIXED_ARGS L\"{_c_str(spec.args)}\"\n"
    )
    (gen / "pyappdist_launcher_config.h").write_text(header, encoding="ascii")

    rc = gen / f"{spec.name}.rc"
    res = gen / f"{spec.name}.res"
    rc.write_text(_render_rc(config, spec), encoding="ascii")

    exe = layout.image_dir / f"{spec.name}.exe"
    obj = gen / f"{spec.name}.obj"
    subsystem = "WINDOWS" if spec.gui else "CONSOLE"

    bat = gen / "build.bat"
    lines = [
        "@echo off",
        f'call "{vcvars}" >nul',
        f'rc /nologo /fo "{target_path(config.target, res)}" "{target_path(config.target, rc)}"',
        (
            f'cl /nologo /O2 /W3 /utf-8 /I"{target_path(config.target, gen)}" '
            f'"{target_path(config.target, _LAUNCHER_C)}" '
            f'"{target_path(config.target, res)}" '
            f'/Fe:"{target_path(config.target, exe)}" '
            f'/Fo:"{target_path(config.target, obj)}" '
            f"/link /SUBSYSTEM:{subsystem} Shell32.lib"
        ),
    ]
    bat.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")

    proc = subprocess.run(
        ["cmd.exe", "/c", target_path(config.target, bat)],
        capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0 or not exe.exists():
        raise BuildError(
            f"launcher ビルド失敗 ({spec.name}):\n{proc.stdout}\n{proc.stderr}"
        )
    return exe


def _render_rc(config: Config, spec: LauncherConfig) -> str:
    """icon (任意) + VERSIONINFO の .rc を生成する。"""
    parts: list[str] = []
    if spec.icon:
        icon = (config.project_dir / spec.icon).resolve()
        if not icon.is_file():
            raise BuildError(f"launcher icon が見つからない ({spec.name}): {icon}")
        parts.append(f'1 ICON "{_c_str(target_path(config.target, icon))}"')

    quad = _version_quad(config.version)
    company = config.installer.manufacturer or config.name
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
    """"1.2.3" -> "1,2,3,0"（数字以外は無視、4 要素に揃える）。"""
    nums: list[int] = []
    for token in version.split("."):
        digits = "".join(c for c in token if c.isdigit())
        nums.append(int(digits) if digits else 0)
    nums = (nums + [0, 0, 0, 0])[:4]
    return ",".join(str(n) for n in nums)


def _rc_str(s: str) -> str:
    """.rc の文字列リテラル用エスケープ（バックスラッシュと引用符）。"""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _bootstrap(entry: str) -> str:
    module, _, func = entry.partition(":")
    return f"import sys; from {module} import {func}; sys.exit({func}())"


def _c_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _find_vcvars() -> str:
    vswhere = _vswhere_path()
    if not vswhere.is_file():
        raise BuildError(f"vswhere が見つからない: {vswhere}")
    proc = subprocess.run(
        [str(vswhere), "-latest", "-property", "installationPath"],
        capture_output=True, text=True, errors="replace",
    )
    install = proc.stdout.strip()
    if not install:
        raise BuildError("Visual Studio (C++ ツール) が見つからない")
    return install + r"\VC\Auxiliary\Build\vcvars64.bat"
