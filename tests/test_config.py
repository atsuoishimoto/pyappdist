"""Tests for config loading and validation (Linux-only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.config import ensure_upgrade_code, load_config
from pyappdist.errors import ConfigError
from pyappdist.wix.guid import is_guid

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
    # break the entry
    text = (cfg_dir / "pyproject.toml").read_text().replace(
        '"helloworld:main"', '"helloworld_no_colon"'
    )
    (cfg_dir / "pyproject.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="module:callable"):
        load_config(cfg_dir)


def test_unknown_target(tmp_path: Path):
    with pytest.raises(ConfigError, match="unknown target"):
        load_config(_write(tmp_path), target_override="solaris-sparc")


def test_manager_default_none(tmp_path: Path):
    cfg = load_config(_write(tmp_path))
    assert cfg.manager is None


def test_manager_valid(tmp_path: Path):
    cfg = load_config(_write(tmp_path, extra='manager = "requirements.txt"'))
    assert cfg.manager == "requirements.txt"


def test_manager_invalid(tmp_path: Path):
    with pytest.raises(ConfigError, match="manager"):
        load_config(_write(tmp_path, extra='manager = "conda"'))


def test_wix_scope_default_permachine(tmp_path: Path):
    cfg = load_config(_write(tmp_path))
    assert cfg.wix.scope == "perMachine"


def test_wix_scope_valid(tmp_path: Path):
    cfg = load_config(
        _write(
            tmp_path,
            extra='[tool.pyappdist.wix]\nscope = "perUserOrMachine"',
        )
    )
    assert cfg.wix.scope == "perUserOrMachine"


def test_wix_scope_invalid(tmp_path: Path):
    with pytest.raises(ConfigError, match="scope"):
        load_config(_write(tmp_path, extra='[tool.pyappdist.wix]\nscope = "perUser"'))


def test_ensure_upgrade_code_generates_and_persists(tmp_path: Path):
    proj = _write(tmp_path)  # no [tool.pyappdist.wix] section
    code = ensure_upgrade_code(proj, log=lambda _m: None)

    assert is_guid(code)
    # persisted: reloading via tomllib + a second call returns the same value
    assert ensure_upgrade_code(proj, log=lambda _m: None) == code
    assert code in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_ensure_upgrade_code_keeps_existing(tmp_path: Path):
    existing = "7E3F9A2C-5B1D-4E8A-9C6F-1A2B3C4D5E6F"
    proj = _write(tmp_path, extra=f'[tool.pyappdist.wix]\nupgrade_code = "{existing}"')
    before = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    assert ensure_upgrade_code(proj, log=lambda _m: None) == existing
    # unchanged file (no rewrite when a valid code is already present)
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == before
