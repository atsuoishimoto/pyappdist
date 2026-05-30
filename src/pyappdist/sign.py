"""コード署名フック（Phase 5）。

MVP は未署名で出荷する。環境変数 ``PYAPPDIST_SIGN_CMD`` が設定されていれば、
各成果物（launcher.exe / MSI）に対してそのコマンドを実行する。``{file}`` は
対象ファイルパスに置換される（無ければ末尾に追記）。証明書は CI secret 等で
コマンド側に渡す前提で、pyappdist は証明書を扱わない。

コマンドはプラットフォームのシェル経由で実行する（Windows は cmd.exe）。普段
ターミナルで打つコマンドラインをそのまま書けばよく、Windows のバックスラッシュ
パスや環境変数もシェルがそのまま解釈する。``{file}`` を含む場合は空白対策で
``"{file}"`` のように引用すること。

例: PYAPPDIST_SIGN_CMD='signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"'
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import BuildError

_ENV = "PYAPPDIST_SIGN_CMD"


def sign_artifact(path: Path, *, log=print) -> bool:
    """成果物に署名する。署名コマンド未設定なら何もせず False を返す。"""
    template = os.environ.get(_ENV)
    if not template:
        log(f"sign: スキップ（{_ENV} 未設定）: {path.name}")
        return False
    if "{file}" in template:
        command = template.replace("{file}", str(path))
    else:
        command = f'{template} "{path}"'
    log(f"sign: {path.name}")
    proc = subprocess.run(command, shell=True, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise BuildError(f"署名失敗 ({path.name}):\n{proc.stdout}\n{proc.stderr}")
    return True
