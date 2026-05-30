"""config 読み込み・バリデーションのテスト（Linux 完結）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.config import load_config
from pyappdist.errors import ConfigError

_BASE = """
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
name = "Hello World"
python = "3.12"
target = "windows-x86_64"
launchers = [
  {{ name = "helloworld", entry = "helloworld:main" }},
]
{extra}
"""


def _write(tmp_path: Path, *, extra: str = "") -> Path:
    (tmp_path / "pyproject.toml").write_text(_BASE.format(extra=extra), encoding="utf-8")
    return tmp_path


def test_load_basic(tmp_path: Path):
    cfg = load_config(_write(tmp_path))
    assert cfg.name == "Hello World"
    assert cfg.dist_name == "helloworld"
    assert cfg.python == "3.12"
    assert cfg.python_minor == "3.12"
    assert cfg.target.os == "windows"
    assert cfg.launchers[0].entry == "helloworld:main"


def test_target_override(tmp_path: Path):
    cfg = load_config(_write(tmp_path), target_override="linux-x86_64")
    assert cfg.target.os == "linux"


def test_missing_pyappdist_table(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="tool.pyappdist"):
        load_config(tmp_path)


def test_invalid_python(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="1"\n[tool.pyappdist]\npython="3"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="python"):
        load_config(tmp_path)


def test_launcher_entry_must_be_module_callable(tmp_path: Path):
    cfg_dir = _write(
        tmp_path,
        extra="",
    )
    # entry を壊す
    text = (cfg_dir / "pyproject.toml").read_text().replace(
        '"helloworld:main"', '"helloworld_no_colon"'
    )
    (cfg_dir / "pyproject.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="module:callable"):
        load_config(cfg_dir)


def test_unknown_target(tmp_path: Path):
    with pytest.raises(ConfigError, match="未知の target"):
        load_config(_write(tmp_path), target_override="solaris-sparc")
