"""Tests for config loading and validation (Linux-only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.config import ensure_upgrade_code, load_configs
from pyappdist.errors import ConfigError
from pyappdist.wix.guid import is_guid

_BASE = """
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
name = "Hello World"
python = "3.12"
launchers = [
  {{ name = "helloworld", entry = "helloworld:main" }},
]
{app_extra}

[[tool.pyappdist.targets]]
platform = "windows-x86_64"
format = "{fmt}"
{target_extra}
"""

_MULTI = """
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
python = "3.12"
launchers = [ { name = "helloworld", entry = "helloworld:main" } ]

[[tool.pyappdist.targets]]
name = "win-user"
platform = "windows-x86_64"
format = "msi"
scope = "user"

[[tool.pyappdist.targets]]
name = "win-machine"
platform = "windows-x86_64"
format = "msi"
scope = "machine"
"""


def _write(
    tmp_path: Path, *, fmt: str = "msi", app_extra: str = "", target_extra: str = ""
) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        _BASE.format(fmt=fmt, app_extra=app_extra, target_extra=target_extra),
        encoding="utf-8",
    )
    return tmp_path


def _write_text(tmp_path: Path, text: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_load_basic(tmp_path: Path):
    cfgs = load_configs(_write(tmp_path))
    assert len(cfgs) == 1
    cfg = cfgs[0]
    assert cfg.name == "Hello World"
    assert cfg.dist_name == "helloworld"
    assert cfg.python == "3.12"
    assert cfg.python_minor == "3.12"
    assert cfg.target.os == "windows"
    assert cfg.target_name == "windows-x86_64"  # defaults to the platform
    assert cfg.launchers[0].entry == "helloworld:main"


def test_build_all_targets_by_default(tmp_path: Path):
    cfgs = load_configs(_write_text(tmp_path, _MULTI))
    assert [c.target_name for c in cfgs] == ["win-user", "win-machine"]
    assert [c.wix.scope for c in cfgs] == ["user", "machine"]


def test_select_subset(tmp_path: Path):
    cfgs = load_configs(_write_text(tmp_path, _MULTI), select=["win-machine"])
    assert [c.target_name for c in cfgs] == ["win-machine"]


def test_select_unknown_target(tmp_path: Path):
    with pytest.raises(ConfigError, match="unknown target"):
        load_configs(_write_text(tmp_path, _MULTI), select=["nope"])


def test_duplicate_target_name(tmp_path: Path):
    dup = _MULTI.replace('name = "win-machine"', 'name = "win-user"')
    with pytest.raises(ConfigError, match="duplicate"):
        load_configs(_write_text(tmp_path, dup))


def test_no_targets_error(tmp_path: Path):
    text = '[project]\nname="x"\nversion="1"\n[tool.pyappdist]\npython="3.12"\n'
    with pytest.raises(ConfigError, match="targets"):
        load_configs(_write_text(tmp_path, text))


def test_unknown_platform(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        '"windows-x86_64"', '"solaris-sparc"'
    )
    with pytest.raises(ConfigError, match="unknown target"):
        load_configs(_write_text(tmp_path, text))


def test_missing_pyappdist_table(tmp_path: Path):
    with pytest.raises(ConfigError, match="tool.pyappdist"):
        load_configs(_write_text(tmp_path, '[project]\nname = "x"\nversion = "1"\n'))


def test_invalid_python(tmp_path: Path):
    text = '[project]\nname="x"\nversion="1"\n[tool.pyappdist]\npython="3"\n'
    with pytest.raises(ConfigError, match="python"):
        load_configs(_write_text(tmp_path, text))


def test_launcher_entry_must_be_module_callable(tmp_path: Path):
    proj = _write(tmp_path)
    text = (proj / "pyproject.toml").read_text().replace(
        '"helloworld:main"', '"helloworld_no_colon"'
    )
    (proj / "pyproject.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="module:callable"):
        load_configs(proj)


def test_manager_default_none(tmp_path: Path):
    assert load_configs(_write(tmp_path))[0].manager is None


def test_manager_valid(tmp_path: Path):
    cfg = load_configs(_write(tmp_path, app_extra='manager = "requirements.txt"'))[0]
    assert cfg.manager == "requirements.txt"


def test_manager_invalid(tmp_path: Path):
    with pytest.raises(ConfigError, match="manager"):
        load_configs(_write(tmp_path, app_extra='manager = "conda"'))


def test_scope_default_user(tmp_path: Path):
    assert load_configs(_write(tmp_path))[0].wix.scope == "user"


def test_scope_machine(tmp_path: Path):
    cfg = load_configs(_write(tmp_path, target_extra='scope = "machine"'))[0]
    assert cfg.wix.scope == "machine"


def test_scope_invalid(tmp_path: Path):
    with pytest.raises(ConfigError, match="scope"):
        load_configs(_write(tmp_path, target_extra='scope = "perMachine"'))


def test_license_optional_and_parsed(tmp_path: Path):
    cfg = load_configs(_write(tmp_path, target_extra='license = "EULA.rtf"'))[0]
    assert cfg.wix.license == "EULA.rtf"


def test_license_must_be_rtf(tmp_path: Path):
    with pytest.raises(ConfigError, match="rtf"):
        load_configs(_write(tmp_path, target_extra='license = "EULA.txt"'))


def test_format_required(tmp_path: Path):
    # A target table with no `format` is rejected (no default).
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        '\nformat = "msi"', ""
    )
    with pytest.raises(ConfigError, match="format"):
        load_configs(_write_text(tmp_path, text))


def test_format_msix(tmp_path: Path):
    cfg = load_configs(_write(tmp_path, fmt="msix"))[0]
    assert cfg.format == "msix"


def test_format_invalid(tmp_path: Path):
    with pytest.raises(ConfigError, match="format"):
        load_configs(_write(tmp_path, fmt="appx"))


def test_format_platform_mismatch(tmp_path: Path):
    # msi/msix only on Windows; linux only on Linux; macos only on macOS.
    msi_on_linux = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        '"windows-x86_64"', '"linux-x86_64"'
    )
    with pytest.raises(ConfigError, match="linux"):
        load_configs(_write_text(tmp_path, msi_on_linux))

    linux_on_windows = _BASE.format(fmt="linux", app_extra="", target_extra="")
    with pytest.raises(ConfigError, match="windows"):
        load_configs(_write_text(tmp_path, linux_on_windows))

    macos_on_windows = _BASE.format(fmt="macos", app_extra="", target_extra="")
    with pytest.raises(ConfigError, match="windows"):
        load_configs(_write_text(tmp_path, macos_on_windows))

    msi_on_macos = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        '"windows-x86_64"', '"macos-aarch64"'
    )
    with pytest.raises(ConfigError, match="macos"):
        load_configs(_write_text(tmp_path, msi_on_macos))


def _linux_pyproject(target_extra: str) -> str:
    return _BASE.format(fmt="linux", app_extra="", target_extra=target_extra).replace(
        '"windows-x86_64"', '"linux-x86_64"'
    )


def test_linux_compression_default_xz(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _linux_pyproject("")))[0]
    assert cfg.linux.compression == "xz"


def test_linux_compression_valid(tmp_path: Path):
    text = _linux_pyproject('compression = "bzip2"\n')
    cfg = load_configs(_write_text(tmp_path, text))[0]
    assert cfg.linux.compression == "bzip2"


def test_linux_compression_invalid(tmp_path: Path):
    text = _linux_pyproject('compression = "zip"\n')
    with pytest.raises(ConfigError, match="compression"):
        load_configs(_write_text(tmp_path, text))


def _macos_pyproject(target_extra: str) -> str:
    return _BASE.format(fmt="macos", app_extra="", target_extra=target_extra).replace(
        '"windows-x86_64"', '"macos-aarch64"'
    )


def test_macos_load_basic(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _macos_pyproject("")))[0]
    assert cfg.format == "macos"
    assert cfg.target.os == "macos"
    assert cfg.target.triple == "aarch64-apple-darwin"


def test_macos_compression_default_gzip(tmp_path: Path):
    # xz is not preinstalled on macOS, so the default differs from Linux (xz).
    cfg = load_configs(_write_text(tmp_path, _macos_pyproject("")))[0]
    assert cfg.macos.compression == "gzip"


def test_macos_compression_valid(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _macos_pyproject('compression = "xz"\n')))[0]
    assert cfg.macos.compression == "xz"


def test_macos_compression_invalid(tmp_path: Path):
    text = _macos_pyproject('compression = "zip"\n')
    with pytest.raises(ConfigError, match="compression"):
        load_configs(_write_text(tmp_path, text))


def test_msix_fields(tmp_path: Path):
    cfg = load_configs(
        _write(
            tmp_path,
            fmt="msix",
            target_extra='identity_name = "Contoso.App"\npublisher = "CN=Contoso"',
        )
    )[0]
    assert cfg.msix.identity_name == "Contoso.App"
    assert cfg.msix.publisher == "CN=Contoso"


def test_msix_logo_must_be_png(tmp_path: Path):
    with pytest.raises(ConfigError, match="png"):
        load_configs(_write(tmp_path, target_extra='logo = "logo.jpg"'))


def test_ensure_upgrade_code_generates_and_persists(tmp_path: Path):
    proj = _write(tmp_path)  # target has no upgrade_code yet
    code = ensure_upgrade_code(proj, "windows-x86_64", log=lambda _m: None)

    assert is_guid(code)
    # persisted: a second call returns the same value
    assert ensure_upgrade_code(proj, "windows-x86_64", log=lambda _m: None) == code
    assert code in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_ensure_upgrade_code_keeps_existing(tmp_path: Path):
    existing = "7E3F9A2C-5B1D-4E8A-9C6F-1A2B3C4D5E6F"
    proj = _write(tmp_path, target_extra=f'upgrade_code = "{existing}"')
    before = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    assert ensure_upgrade_code(proj, "windows-x86_64", log=lambda _m: None) == existing
    # unchanged file (no rewrite when a valid code is already present)
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == before
