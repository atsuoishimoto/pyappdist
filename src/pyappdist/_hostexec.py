"""ホスト/ターゲット差を吸収する実行ヘルパ。

WSL(Linux ホスト) から Windows ターゲットを扱う場合、Windows ツール(uv.exe)を
呼び、パスは Windows 形式 (wslpath -w) に変換する必要がある。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .targets import Target


def is_cross_windows(target: Target) -> bool:
    """Linux ホストから Windows ターゲットを扱う (.exe ブリッジが必要)。"""
    return target.os == "windows" and sys.platform != "win32"


def target_path(target: Target, path: Path | str) -> str:
    """ターゲットツールに渡すためのパス文字列。"""
    p = Path(path)
    if is_cross_windows(target):
        out = subprocess.run(
            ["wslpath", "-w", str(p)], capture_output=True, text=True,
            errors="replace", check=True,
        )
        return out.stdout.strip()
    return str(p)
