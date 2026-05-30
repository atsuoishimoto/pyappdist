"""wheelhouse の全 wheel を runtime の site-packages へ install する。

venv は使わず、image 内 runtime の python を直接使って ``python -m pip install``
する（uv は使わない: uv のキャッシュ/インデックス挙動を避け、ビルドした wheel が
確実に使われるようにするため）。

wheelhouse にはアプリ + 依存だけが揃っているので、dist_name を解決せず **全 wheel を
そのまま pip に渡す**。``--no-index`` で外部参照しない。cwd を wheelhouse にして
相対指定（wheel 名のみ）するので、WSL→Windows でも wslpath が要らない
（interop が cwd を Windows 側に変換する）。``--target`` も使わず runtime 自身の
site-packages へ正規 install する。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..errors import BuildError
from .layout import ImageLayout


def install_app(layout: ImageLayout, wheelhouse: Path, *, log=print) -> None:
    wheels = sorted(p.name for p in wheelhouse.glob("*.whl"))
    if not wheels:
        raise BuildError(f"wheelhouse に wheel が無い: {wheelhouse}")
    log(f"image: {len(wheels)} wheel を install -> {layout.site_packages}")
    cmd = [str(layout.python_exe), "-m", "pip", "install", "--no-index", *wheels]
    # cwd=wheelhouse なので wheel 名だけで済む（WSL interop が Windows 側 cwd に変換）。
    proc = subprocess.run(
        cmd, cwd=str(wheelhouse), capture_output=True, text=True, errors="replace"
    )
    if proc.returncode != 0:
        raise BuildError(
            f"install 失敗 ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
