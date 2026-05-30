"""依存リストの決定（パッケージ管理ツールのロックファイル → requirements.txt）。

依存はプロジェクトの **ロックファイル基準** で固定する。開発者が使っている管理ツール
（uv / poetry / pipenv / PDM）でロックから ``requirements.txt`` を export し、後段で
ターゲット runtime の python により ``pip wheel -r requirements.txt`` する。export は
クロス用のマーカー付き・ハッシュ付き・本番依存のみ（dev 除外）で出力する。

判定:
* ``[tool.pyappdist].manager`` の明示指定が最優先（``requirements.txt`` 指定ならプロジェクト
  直下の requirements.txt をそのまま使う）。
* 指定が無ければロックファイルの存在を uv.lock → poetry.lock → Pipfile.lock → pdm.lock の
  順で探し、最初に見つかったツールを採用。
* 判定不能なら warning を出し ``requirements.txt`` モードとして動作（無ければ ``BuildError``）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import Config
from .errors import BuildError

# ツール名 → ロックファイル名（自動判定の探索順）。
_LOCKFILES: tuple[tuple[str, str], ...] = (
    ("uv", "uv.lock"),
    ("poetry", "poetry.lock"),
    ("pipenv", "Pipfile.lock"),
    ("pdm", "pdm.lock"),
)

# ツール名 → export コマンド（cwd=project_dir で実行し stdout を requirements.txt とする）。
# いずれも本番依存のみ（dev 除外）・ハッシュ付き。
_EXPORT_CMDS: dict[str, list[str]] = {
    "uv": ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt"],
    "poetry": ["poetry", "export", "-f", "requirements.txt", "--without", "dev"],
    "pipenv": ["pipenv", "requirements", "--hash"],
    "pdm": ["pdm", "export", "-f", "requirements", "--prod"],
}


def _auto_detect(project_dir: Path) -> str | None:
    """ロックファイルの存在から管理ツールを判定する（無ければ None）。"""
    for manager, lockfile in _LOCKFILES:
        if (project_dir / lockfile).is_file():
            return manager
    return None


def _warn(log, message: str) -> None:
    log(f"warning: {message}")


def resolve_manager(project_dir: Path, override: str | None, *, log=print) -> str:
    """使用する管理ツール（または "requirements.txt"）を決定する。"""
    if override:
        return override
    detected = _auto_detect(project_dir)
    if detected:
        return detected
    _warn(
        log,
        "ロックファイル（uv.lock 等）も [tool.pyappdist].manager 指定も無い。"
        "requirements.txt を参照する",
    )
    return "requirements.txt"


def resolve_requirements(config: Config, wheelhouse: Path, *, log=print) -> Path:
    """依存の固定リストを ``wheelhouse/requirements.txt`` に用意してそのパスを返す。"""
    manager = resolve_manager(config.project_dir, config.manager, log=log)
    out = wheelhouse / "requirements.txt"

    if manager == "requirements.txt":
        src = config.project_dir / "requirements.txt"
        if not src.is_file():
            raise BuildError(
                f"requirements.txt が無い: {src}"
                "（管理ツールのロックファイルを用意するか requirements.txt を置く）"
            )
        log(f"deps: requirements.txt を参照 ({src})")
        out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return out

    cmd = _EXPORT_CMDS[manager]
    log(f"deps: {manager} のロックから requirements.txt を export")
    proc = subprocess.run(
        cmd,
        cwd=str(config.project_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise BuildError(
            f"requirements.txt の export 失敗 ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.strip()}"
        )
    out.write_text(proc.stdout, encoding="utf-8")
    return out
