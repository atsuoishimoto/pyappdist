"""wheel の用意（アプリ wheel のビルド + 依存 wheel の収集）。

* アプリ本体: ``uv build --wheel`` で wheelhouse へ。
* 依存: ``uv pip compile`` で解決し ``pip download`` で wheelhouse へ。
  （uv には pip download 相当が無いため download は pip を使う。
  ``--platform`` 指定でクロスプラットフォーム取得に対応。）
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from .config import Config
from .errors import BuildError


def build_wheelhouse(config: Config, wheelhouse: Path, *, log=print) -> list[Path]:
    """アプリ + 依存 wheel を wheelhouse に用意して一覧を返す。"""
    wheelhouse.mkdir(parents=True, exist_ok=True)
    wheels = [build_app_wheel(config.project_dir, wheelhouse, log=log)]
    wheels += collect_dependencies(config, wheelhouse, log=log)
    return wheels


def build_app_wheel(project_dir: Path, wheelhouse: Path, *, log=print) -> Path:
    log(f"wheels: アプリ wheel をビルド ({project_dir.name})")
    before = set(wheelhouse.glob("*.whl"))
    _run(["uv", "build", "--wheel", "--out-dir", str(wheelhouse), str(project_dir)])
    after = set(wheelhouse.glob("*.whl"))
    new = sorted(after - before)
    if not new:
        # 再ビルドで上書きされた等で差分が無い場合は最新を返す
        all_wheels = sorted(after, key=lambda p: p.stat().st_mtime)
        if not all_wheels:
            raise BuildError("uv build が wheel を生成しなかった")
        return all_wheels[-1]
    return new[-1]


def collect_dependencies(config: Config, wheelhouse: Path, *, log=print) -> list[Path]:
    deps = _project_dependencies(config.project_dir)
    if not deps:
        log("wheels: 依存なし（収集スキップ）")
        return []

    req = wheelhouse.parent / "requirements.txt"
    log("wheels: 依存を解決 (uv pip compile)")
    _run([
        "uv", "pip", "compile",
        str(config.project_dir / "pyproject.toml"),
        "--python-platform", config.target.uv_platform,
        "--python-version", config.python_minor,
        "--quiet",
        "-o", str(req),
    ])

    log("wheels: 依存 wheel を download (pip download)")
    before = set(wheelhouse.glob("*.whl"))
    _run([
        sys.executable, "-m", "pip", "download",
        "-r", str(req),
        "--dest", str(wheelhouse),
        "--only-binary=:all:",
        "--implementation", "cp",
        "--python-version", config.python_minor,
        "--platform", config.target.pip_platform,
    ])
    return sorted(set(wheelhouse.glob("*.whl")) - before)


def _project_dependencies(project_dir: Path) -> list[str]:
    data = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data.get("project", {}).get("dependencies", []) or [])


def _run(cmd: list[str]) -> None:
    # uv は UTF-8 出力。pip の英数字メッセージも UTF-8 で問題なく読める。
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise BuildError(
            f"コマンド失敗 ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
