"""Tests for config loading and validation (Linux-only)."""

from __future__ import annotations

import json
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
name = "win"
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
    assert cfg.target_name == "win"
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


def test_target_name_required(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'name = "win"\n', ""
    )
    with pytest.raises(ConfigError, match="name is required"):
        load_configs(_write_text(tmp_path, text))


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        ".",
        "trailing.",
        "a/b",
        "a\\b",
        "/tmp/evil",
        "C:\\evil",
        "has space",
        "has\ttab",
        "ctrl\x01char",
        "win?",
    ],
)
def test_target_name_invalid(tmp_path: Path, bad: str):
    # json.dumps escapes backslashes and control characters the same way a TOML
    # basic string does, so the name survives the round-trip verbatim.
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'name = "win"', f"name = {json.dumps(bad)}"
    )
    with pytest.raises(ConfigError, match=r"targets\[0\].name"):
        load_configs(_write_text(tmp_path, text))


@pytest.mark.parametrize("good", ["win", "helloworld-win64", "app_1.2", "日本語"])
def test_target_name_valid(tmp_path: Path, good: str):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'name = "win"', f"name = {json.dumps(good)}"
    )
    cfgs = load_configs(_write_text(tmp_path, text))
    assert cfgs[0].target_name == good


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


def test_unquoted_python_rejected(tmp_path: Path):
    # python = 3.10 is the TOML float 3.1; require a quoted string.
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'python = "3.12"', "python = 3.10"
    )
    with pytest.raises(ConfigError, match="quoted string"):
        load_configs(_write_text(tmp_path, text))


def test_unquoted_tool_version_rejected(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="version = 1.10", target_extra="")
    with pytest.raises(ConfigError, match="quoted string"):
        load_configs(_write_text(tmp_path, text))


def test_unquoted_project_version_rejected(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'version = "0.1.0"', "version = 1.10"
    )
    with pytest.raises(ConfigError, match="quoted string"):
        load_configs(_write_text(tmp_path, text))


@pytest.mark.parametrize("bad", ['":main"', '"helloworld:"', '"bad name"', '"a..b"'])
def test_launcher_entry_invalid(tmp_path: Path, bad: str):
    proj = _write(tmp_path)
    text = (proj / "pyproject.toml").read_text().replace('"helloworld:main"', bad)
    (proj / "pyproject.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="module:callable"):
        load_configs(proj)


def _bootstrap_for(tmp_path: Path, entry: str) -> str:
    proj = _write(tmp_path)
    text = (proj / "pyproject.toml").read_text().replace('"helloworld:main"', f'"{entry}"')
    (proj / "pyproject.toml").write_text(text, encoding="utf-8")
    return load_configs(proj)[0].launchers[0].bootstrap


def test_launcher_entry_callable_form(tmp_path: Path):
    assert _bootstrap_for(tmp_path, "helloworld:main") == (
        "import sys; from helloworld import main; sys.exit(main())"
    )


def test_launcher_entry_module_form_dotted(tmp_path: Path):
    assert _bootstrap_for(tmp_path, "niceguidemo.main") == (
        "import runpy; runpy.run_module('niceguidemo.main', "
        "run_name='__main__', alter_sys=True)"
    )


def test_launcher_entry_module_form_bare(tmp_path: Path):
    assert _bootstrap_for(tmp_path, "niceguidemo") == (
        "import runpy; runpy.run_module('niceguidemo', "
        "run_name='__main__', alter_sys=True)"
    )


def test_manager_default_none(tmp_path: Path):
    assert load_configs(_write(tmp_path))[0].manager is None


def test_manager_valid(tmp_path: Path):
    cfg = load_configs(_write(tmp_path, app_extra='manager = "requirements.txt"'))[0]
    assert cfg.manager == "requirements.txt"


def test_manager_invalid(tmp_path: Path):
    with pytest.raises(ConfigError, match="manager"):
        load_configs(_write(tmp_path, app_extra='manager = "conda"'))


def test_extras_default_empty(tmp_path: Path):
    assert load_configs(_write(tmp_path))[0].extras == ()


def test_extras_parsed(tmp_path: Path):
    cfg = load_configs(_write(tmp_path, target_extra='extras = ["gui", "extra"]'))[0]
    assert cfg.extras == ("gui", "extra")


def test_extras_must_be_list_of_strings(tmp_path: Path):
    with pytest.raises(ConfigError, match="extras"):
        load_configs(_write(tmp_path, target_extra='extras = "gui"'))
    with pytest.raises(ConfigError, match="extras"):
        load_configs(_write(tmp_path, target_extra="extras = [1, 2]"))


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


def test_code_sign_default_off(tmp_path: Path):
    cfg = load_configs(_write(tmp_path))[0]
    assert cfg.wix.code_sign is False
    assert cfg.wix.code_sign_command is None


def test_code_sign_parsed(tmp_path: Path):
    cfg = load_configs(
        _write(
            tmp_path,
            target_extra='code-sign = true\ncode-sign-command = "mysign \\"{file}\\""',
        )
    )[0]
    assert cfg.wix.code_sign is True
    assert cfg.wix.code_sign_command == 'mysign "{file}"'


def test_code_sign_must_be_bool(tmp_path: Path):
    with pytest.raises(ConfigError, match="code-sign"):
        load_configs(_write(tmp_path, target_extra='code-sign = "yes"'))


def test_allow_same_version_upgrades_default_false(tmp_path: Path):
    cfg = load_configs(_write(tmp_path))[0]
    assert cfg.wix.allow_same_version_upgrades is False


def test_allow_same_version_upgrades_parsed(tmp_path: Path):
    cfg = load_configs(
        _write(tmp_path, target_extra="allow-same-version-upgrades = true")
    )[0]
    assert cfg.wix.allow_same_version_upgrades is True


def test_allow_same_version_upgrades_must_be_bool(tmp_path: Path):
    with pytest.raises(ConfigError, match="allow-same-version-upgrades"):
        load_configs(_write(tmp_path, target_extra='allow-same-version-upgrades = "yes"'))


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


def _macos_app_pyproject(fmt: str, *, app_extra: str = "", target_extra: str = "") -> str:
    return _BASE.format(fmt=fmt, app_extra=app_extra, target_extra=target_extra).replace(
        '"windows-x86_64"', '"macos-aarch64"'
    )


_IDENT = 'identifier = "com.example.helloworld"'


@pytest.mark.parametrize("fmt", ["macapp", "dmg"])
def test_format_app_dmg_accepted(tmp_path: Path, fmt: str):
    cfg = load_configs(
        _write_text(tmp_path, _macos_app_pyproject(fmt, app_extra=_IDENT))
    )[0]
    assert cfg.format == fmt
    assert cfg.target.os == "macos"
    assert cfg.identifier == "com.example.helloworld"


@pytest.mark.parametrize("fmt", ["macapp", "dmg"])
def test_app_dmg_require_identifier(tmp_path: Path, fmt: str):
    # No app-level identifier -> error (a .app needs a CFBundleIdentifier).
    with pytest.raises(ConfigError, match="identifier is required"):
        load_configs(_write_text(tmp_path, _macos_app_pyproject(fmt)))


@pytest.mark.parametrize("fmt", ["macapp", "dmg"])
def test_app_dmg_only_on_macos(tmp_path: Path, fmt: str):
    text = _BASE.format(fmt=fmt, app_extra=_IDENT, target_extra="")  # windows platform
    with pytest.raises(ConfigError, match="windows"):
        load_configs(_write_text(tmp_path, text))


def test_identifier_must_be_reverse_dns(tmp_path: Path):
    with pytest.raises(ConfigError, match="reverse-DNS"):
        load_configs(
            _write_text(
                tmp_path, _macos_app_pyproject("dmg", app_extra='identifier = "helloworld"')
            )
        )


def test_identifier_optional_for_non_app_targets(tmp_path: Path):
    # A plain msi target needs no identifier.
    cfg = load_configs(_write(tmp_path))[0]
    assert cfg.identifier is None


def test_macos_app_fields_parsed(tmp_path: Path):
    extra = (
        'min-macos = "12.0"\n'
        'signing-identity = "Developer ID Application: Me (TEAMID)"\n'
        'team-id = "TEAMID"\n'
        'notary-profile = "myprofile"\n'
        'entitlements = "ent.plist"\n'
        'category = "public.app-category.utilities"\n'
    )
    cfg = load_configs(
        _write_text(tmp_path, _macos_app_pyproject("dmg", app_extra=_IDENT, target_extra=extra))
    )[0]
    m = cfg.macos
    assert m.min_macos == "12.0"
    assert m.signing_identity == "Developer ID Application: Me (TEAMID)"
    assert m.team_id == "TEAMID"
    assert m.notary_profile == "myprofile"
    assert m.entitlements == "ent.plist"
    assert m.category == "public.app-category.utilities"


def test_macos_min_macos_default(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _macos_app_pyproject("dmg", app_extra=_IDENT)))[0]
    assert cfg.macos.min_macos == "11.0"


def _icon_pyproject(icon_toml: str) -> str:
    # A windows/msi project whose single launcher carries the given `icon` value.
    return f"""
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
name = "Hello World"
python = "3.12"
launchers = [
  {{ name = "helloworld", entry = "helloworld:main", icon = {icon_toml} }},
]

[[tool.pyappdist.targets]]
name = "win"
platform = "windows-x86_64"
format = "msi"
"""


def test_launcher_icon_table_parsed(tmp_path: Path):
    cfg = load_configs(
        _write_text(
            tmp_path,
            _icon_pyproject('{ windows = "a.ico", macos = "a.png", linux = "a.png" }'),
        )
    )[0]
    spec = cfg.launchers[0]
    assert spec.icon_for("windows") == "a.ico"
    assert spec.icon_for("macos") == "a.png"
    assert spec.icon_for("linux") == "a.png"


def test_launcher_icon_partial_table(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _icon_pyproject('{ macos = "a.png" }')))[0]
    spec = cfg.launchers[0]
    assert spec.icon_for("macos") == "a.png"
    assert spec.icon_for("windows") is None


def test_launcher_icon_string_rejected(tmp_path: Path):
    # The old single-string form is no longer accepted.
    with pytest.raises(ConfigError, match="must be a table"):
        load_configs(_write_text(tmp_path, _icon_pyproject('"app.ico"')))


def test_launcher_icon_unknown_os_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="unknown key"):
        load_configs(_write_text(tmp_path, _icon_pyproject('{ mac = "a.png" }')))


def test_launcher_icon_wrong_suffix_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="must be a .ico"):
        load_configs(_write_text(tmp_path, _icon_pyproject('{ windows = "a.png" }')))
    with pytest.raises(ConfigError, match="must be a .png"):
        load_configs(_write_text(tmp_path, _icon_pyproject('{ macos = "a.ico" }')))


def test_msix_fields(tmp_path: Path):
    cfg = load_configs(
        _write(
            tmp_path,
            fmt="msix",
            target_extra='identity-name = "Contoso.App"\npublisher = "CN=Contoso"',
        )
    )[0]
    assert cfg.msix.identity_name == "Contoso.App"
    assert cfg.msix.publisher == "CN=Contoso"


def test_msix_logo_must_be_png(tmp_path: Path):
    with pytest.raises(ConfigError, match="png"):
        load_configs(_write(tmp_path, target_extra='logo = "logo.jpg"'))


def test_ensure_upgrade_code_generates_and_persists(tmp_path: Path):
    proj = _write(tmp_path)  # target has no upgrade_code yet
    code = ensure_upgrade_code(proj, "win", log=lambda _m: None)

    assert is_guid(code)
    # persisted: a second call returns the same value
    assert ensure_upgrade_code(proj, "win", log=lambda _m: None) == code
    assert code in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_ensure_upgrade_code_keeps_existing(tmp_path: Path):
    existing = "7E3F9A2C-5B1D-4E8A-9C6F-1A2B3C4D5E6F"
    proj = _write(tmp_path, target_extra=f'upgrade-code = "{existing}"')
    before = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    assert ensure_upgrade_code(proj, "win", log=lambda _m: None) == existing
    # unchanged file (no rewrite when a valid code is already present)
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == before


def _launcher_pyproject(name_toml: str) -> str:
    """A pyproject with one launcher whose ``name`` is the given TOML literal."""
    return f"""
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
python = "3.12"
launchers = [ {{ name = {name_toml}, entry = "helloworld:main" }} ]

[[tool.pyappdist.targets]]
name = "win"
platform = "windows-x86_64"
format = "msi"
"""


@pytest.mark.parametrize(
    "bad", ["my app", "a:b", "a/b", "a\\b", 'a"b', "a\tb", "a*b"]
)
def test_launcher_name_rejects_unsafe_chars(tmp_path: Path, bad: str):
    # TOML literal strings ('...') take the name verbatim, no escape processing.
    text = _launcher_pyproject(f"'{bad}'")
    with pytest.raises(ConfigError, match="launchers\\[0\\].name"):
        load_configs(_write_text(tmp_path, text))


def test_launcher_name_allows_unicode(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _launcher_pyproject("'ハローワールド'")))[0]
    assert cfg.launchers[0].name == "ハローワールド"


def test_msi_rejects_non_numeric_version(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'version = "0.1.0"', 'version = "0.1.0a1"'
    )
    with pytest.raises(ConfigError, match="numeric version"):
        load_configs(_write_text(tmp_path, text))


def test_posix_allows_non_numeric_version(tmp_path: Path):
    text = _linux_pyproject("").replace('version = "0.1.0"', 'version = "0.1.0a1"')
    cfg = load_configs(_write_text(tmp_path, text))[0]
    assert cfg.version == "0.1.0a1"


# An msi target and a linux target side by side, so select-scoped validation can be
# exercised: the msi-only version check must not fire when only "lin" is selected.
_MSI_PLUS_LINUX = """
[project]
name = "helloworld"
version = "0.1.0a1"

[tool.pyappdist]
python = "3.12"
launchers = [ { name = "helloworld", entry = "helloworld:main" } ]

[[tool.pyappdist.targets]]
name = "win"
platform = "windows-x86_64"
format = "msi"

[[tool.pyappdist.targets]]
name = "lin"
platform = "linux-x86_64"
format = "linux"
"""


def test_msi_version_check_skipped_for_unselected_target(tmp_path: Path):
    # A declared-but-unselected msi target must not block a posix build (issue #61).
    cfgs = load_configs(_write_text(tmp_path, _MSI_PLUS_LINUX), select=["lin"])
    assert [c.target_name for c in cfgs] == ["lin"]
    assert cfgs[0].version == "0.1.0a1"


def test_msi_version_check_applies_to_selected_target(tmp_path: Path):
    with pytest.raises(ConfigError, match="numeric version"):
        load_configs(_write_text(tmp_path, _MSI_PLUS_LINUX), select=["win"])


def test_identifier_not_required_for_unselected_app_target(tmp_path: Path):
    # A declared-but-unselected macapp target must not force identifier (issue #61).
    text = _macos_app_pyproject("macapp").replace('name = "win"', 'name = "app"') + (
        '\n[[tool.pyappdist.targets]]\n'
        'name = "run"\n'
        'platform = "macos-aarch64"\n'
        'format = "macos"\n'
    )
    cfgs = load_configs(_write_text(tmp_path, text), select=["run"])
    assert [c.target_name for c in cfgs] == ["run"]
    assert cfgs[0].identifier is None
    with pytest.raises(ConfigError, match="identifier is required"):
        load_configs(_write_text(tmp_path, text), select=["app"])
