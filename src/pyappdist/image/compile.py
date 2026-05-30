"""image 内 site-packages の .pyc をビルド時に生成する。"""

from __future__ import annotations

import subprocess

from .._hostexec import target_path
from ..errors import BuildError
from .layout import ImageLayout


def compile_site_packages(layout: ImageLayout, *, log=print) -> None:
    """runtime の python で compileall を実行する。

    対象 OS の python を実行する必要がある（Linux ホスト→Windows ターゲットは
    WSL interop で python.exe を実行、パスは Windows 形式に変換する）。
    実行できない環境では BuildError を投げる。
    """
    target = layout.target
    log("image: compileall")
    cmd = [
        str(layout.python_exe), "-m", "compileall", "-q",
        target_path(target, layout.site_packages),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as e:
        raise BuildError(
            f"compileall を実行できない（{target.name} の python を実行不可）: {e}"
        ) from e
    if proc.returncode != 0:
        raise BuildError(f"compileall 失敗 ({proc.returncode}):\n{proc.stderr.strip()}")
