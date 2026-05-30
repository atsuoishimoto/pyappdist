"""wheel の用意（アプリ wheel のビルド + 依存 wheel の収集）。

ビルド/管理ツールに依存しないよう、すべて標準の ``python -m pip`` で行う
（uv 専用ではなく、PEP 517/621 準拠であれば poetry・hatch・pdm 等どのツールで
作ったプロジェクトでも使える）。

* アプリ本体: ``pip wheel --no-deps`` でプロジェクトの build backend を使って wheel 化
  （アプリは pure-Python 想定なのでホストの python で OK）。
* 依存: 出来たアプリ wheel を **ターゲット runtime の python** に渡して ``pip wheel`` する。
  wheel が公開されている依存はその wheel を取得し、sdist しか無い依存はターゲット python で
  ビルドして wheel 化する（wheel が無いパッケージも扱える）。結果 wheelhouse には wheel だけが
  揃うので、後段のオフライン install は wheel だけ入れれば済む。
  ターゲット実機の解釈で解決するので ``sys_platform`` 等の環境マーカーも wheel タグも
  ネイティブに正しい（例: pandas の ``tzdata; sys_platform=="win32"`` も入る）。クロス指定は不要。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import Config
from .errors import BuildError
from .runtime import RuntimeInfo


def build_wheelhouse(config: Config, runtime: RuntimeInfo, wheelhouse: Path, *, log=print) -> list[Path]:
    """アプリ + 依存 wheel を wheelhouse に用意して一覧を返す。"""
    wheelhouse.mkdir(parents=True, exist_ok=True)
    app_wheel = build_app_wheel(config.project_dir, wheelhouse, log=log)
    collect_dependencies(runtime, app_wheel, wheelhouse, log=log)
    return sorted(wheelhouse.glob("*.whl"))


def build_app_wheel(project_dir: Path, wheelhouse: Path, *, log=print) -> Path:
    log(f"wheels: アプリ wheel をビルド ({project_dir.name})")
    before = set(wheelhouse.glob("*.whl"))
    # PEP 517 ビルド: プロジェクトの build-system backend で wheel を作る（backend 非依存）。
    _run([
        sys.executable, "-m", "pip", "wheel",
        "--no-deps", "--wheel-dir", str(wheelhouse), str(project_dir),
    ])
    after = set(wheelhouse.glob("*.whl"))
    new = sorted(after - before)
    if not new:
        # 再ビルドで上書きされた等で差分が無い場合は最新を返す
        all_wheels = sorted(after, key=lambda p: p.stat().st_mtime)
        if not all_wheels:
            raise BuildError("pip wheel が wheel を生成しなかった")
        return all_wheels[-1]
    return new[-1]


def collect_dependencies(runtime: RuntimeInfo, app_wheel: Path, wheelhouse: Path, *, log=print) -> list[Path]:
    """アプリ wheel の依存を、ターゲット runtime の python で wheel として集める。

    ``pip wheel`` なので wheel がある依存はその wheel を取得し、sdist しか無い依存は
    ターゲット python でビルドして wheel 化する（wheel が無いパッケージも扱える）。
    依存が無ければ何も増えない。cwd=wheelhouse なので相対指定で済み、WSL→Windows
    でも wslpath 変換が要らない（interop が cwd を変換する）。
    """
    log("wheels: 依存 wheel を収集 (target runtime の python で pip wheel)")
    before = set(wheelhouse.glob("*.whl"))
    cmd = [
        str(runtime.python_exe), "-m", "pip", "wheel", app_wheel.name,
        "--wheel-dir", ".",
    ]
    proc = subprocess.run(
        cmd, cwd=str(wheelhouse), capture_output=True, text=True, errors="replace"
    )
    if proc.returncode != 0:
        raise BuildError(
            f"依存 wheel 収集失敗 ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
    return sorted(set(wheelhouse.glob("*.whl")) - before)


def _run(cmd: list[str]) -> None:
    # pip は基本 UTF-8 出力（ネイティブ Windows の非 ASCII は化け得るが診断用途なので許容）。
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise BuildError(
            f"コマンド失敗 ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
