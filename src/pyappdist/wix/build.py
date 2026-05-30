"""生成した .wxs を ``wix build`` で MSI 化する（Phase 5）。

WiX は dotnet グローバルツール（``dotnet tool install --global wix``）。
WSL から Windows ターゲットを扱う場合は wix.exe + Windows パスを使う。
File@Source は image ルート相対なので ``-b <image>`` を bind path に渡す。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .._hostexec import is_cross_windows, target_path
from ..config import Config
from ..errors import BuildError


def build_msi(config: Config, image_dir: Path, wxs_path: Path, out_msi: Path, *, log=print) -> Path | None:
    """``wix build`` で MSI を生成する。非 Windows ターゲットでは None を返す。"""
    target = config.target
    if target.os != "windows":
        log("msi: 非 Windows ターゲットのためスキップ")
        return None

    wix = _find_wix(target)
    out_msi.parent.mkdir(parents=True, exist_ok=True)
    log(f"msi: wix build -> {out_msi}")
    cmd = [
        wix, "build",
        "-arch", target.wix_arch,  # 64bit パッケージにして C:\Program Files へ入れる
        target_path(target, wxs_path),
        "-b", target_path(target, image_dir),
        "-o", target_path(target, out_msi),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0 or not out_msi.exists():
        raise BuildError(
            f"wix build 失敗 ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
    return out_msi


def _find_wix(target) -> str:
    override = os.environ.get("PYAPPDIST_WIX")
    if override:
        return override
    name = "wix.exe" if is_cross_windows(target) else "wix"
    found = shutil.which(name)
    if found:
        return found
    raise BuildError(
        "wix が見つからない。`dotnet tool install --global wix` を実行するか "
        "PYAPPDIST_WIX で wix の絶対パスを指定する。"
    )
