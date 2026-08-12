"""Tests for config loading and validation (Linux-only)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from pyappdist.config import (
    LauncherConfig,
    check_msi_version,
    ensure_upgrade_code,
    load_configs,
)
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


@pytest.mark.parametrize(
    "project_version",
    ['version = "0.1.0"', 'dynamic = ["version"]', ""],
    ids=["static", "dynamic", "absent"],
)
def test_version_from_wheel_without_tool_version(tmp_path: Path, project_version: str):
    # Without [tool.pyappdist].version, the version comes from the app wheel the
    # CLI builds — whatever form [project] declares it in (the build backend
    # knows it either way). The msi/msix version check is deferred until then
    # (the placeholder "0.0.0" would pass it, but the real version is unknown).
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'version = "0.1.0"', project_version
    )
    (cfg,) = load_configs(_write_text(tmp_path, text))
    assert cfg.version_from_wheel
    assert cfg.version == "0.0.0"


def test_explicit_tool_version_skips_wheel_resolution(tmp_path: Path):
    # An explicit [tool.pyappdist].version pins the product version.
    text = _BASE.format(
        fmt="msi", app_extra='version = "2.0.0"', target_extra=""
    ).replace('version = "0.1.0"', 'dynamic = ["version"]')
    (cfg,) = load_configs(_write_text(tmp_path, text))
    assert cfg.version == "2.0.0"
    assert not cfg.version_from_wheel


def test_check_msi_version():
    # The deferred check the CLI runs on a wheel-resolved version: the same
    # dotted-numeric rule load_configs applies to an explicit tool.version.
    check_msi_version("1.2.3", {"msi"})
    check_msi_version("1.2.3.dev4+g1a2b3c", {"linux"})  # non-MSI formats accept PEP 440
    with pytest.raises(ConfigError, match="dotted numeric"):
        check_msi_version("1.2.3.dev4+g1a2b3c", {"msi"})
    with pytest.raises(ConfigError, match="dotted numeric"):
        check_msi_version("1.0.0rc1", {"msix"})


@pytest.mark.parametrize("bad", ['":main"', '"helloworld:"', '"bad name"', '"a..b"'])
def test_launcher_entry_invalid(tmp_path: Path, bad: str):
    proj = _write(tmp_path)
    text = (proj / "pyproject.toml").read_text().replace('"helloworld:main"', bad)
    (proj / "pyproject.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="module:callable"):
        load_configs(proj)


def test_launcher_args_unparsable(tmp_path: Path):
    # args is split with POSIX quoting rules; an unbalanced quote is rejected at load
    # time rather than surfacing as a shlex traceback mid-build.
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'entry = "helloworld:main"', "entry = \"helloworld:main\", args = \"--path 'a\""
    )
    with pytest.raises(ConfigError, match=r"launchers\[0\].args"):
        load_configs(_write_text(tmp_path, text))


def test_launcher_args_split(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'entry = "helloworld:main"',
        "entry = \"helloworld:main\", args = \"--path 'a b' -x\"",
    )
    (cfg,) = load_configs(_write_text(tmp_path, text))
    assert cfg.launchers[0].argv == ("--path", "a b", "-x")


def test_launcher_args_exec_form(tmp_path: Path):
    # Exec form: an array is the argument list verbatim — no splitting, quoting,
    # or glob expansion, so spaces and shell metacharacters pass through as-is.
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'entry = "helloworld:main"',
        'entry = "helloworld:main", args = ["--path", "a b", "*"]',
    )
    (cfg,) = load_configs(_write_text(tmp_path, text))
    assert cfg.launchers[0].argv == ("--path", "a b", "*")


def test_launcher_args_exec_form_non_string(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'entry = "helloworld:main"',
        'entry = "helloworld:main", args = ["-n", 1]',
    )
    with pytest.raises(ConfigError, match=r"launchers\[0\].args\[1\] must be a string"):
        load_configs(_write_text(tmp_path, text))


def test_launcher_args_wrong_type(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'entry = "helloworld:main"',
        'entry = "helloworld:main", args = true',
    )
    with pytest.raises(ConfigError, match=r"launchers\[0\].args must be a string"):
        load_configs(_write_text(tmp_path, text))


def test_launcher_app_entry_default_true(tmp_path: Path):
    (cfg,) = load_configs(_write(tmp_path))
    assert cfg.launchers[0].app_entry is True


def test_launcher_app_entry_parsed(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        'entry = "helloworld:main"',
        'entry = "helloworld:main", app-entry = false',
    )
    (cfg,) = load_configs(_write_text(tmp_path, text))
    assert cfg.launchers[0].app_entry is False


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
    assert cfg.code_sign is False
    assert cfg.code_sign_command is None


def test_code_sign_parsed(tmp_path: Path):
    cfg = load_configs(
        _write(
            tmp_path,
            target_extra='code-sign = true\ncode-sign-command = "mysign \\"{file}\\""',
        )
    )[0]
    assert cfg.code_sign is True
    assert cfg.code_sign_command == 'mysign "{file}"'


def test_code_sign_must_be_bool(tmp_path: Path):
    with pytest.raises(ConfigError, match="code-sign"):
        load_configs(_write(tmp_path, target_extra='code-sign = "yes"'))


def test_code_sign_on_signable_formats(tmp_path: Path):
    # msix and a Windows image target accept code-sign like msi does.
    for fmt in ("msix", "image"):
        cfg = load_configs(_write(tmp_path, fmt=fmt, target_extra="code-sign = true"))[0]
        assert cfg.code_sign is True


@pytest.mark.parametrize(
    "platform, fmt",
    [
        ("linux-x86_64", "linux"),
        ("linux-x86_64", "image"),  # non-Windows image: shell wrappers, nothing to sign
        ("macos-aarch64", "macos"),
        ("macos-aarch64", "macapp"),  # .app/.dmg/.pkg are signed by their own codesign flow
        ("macos-aarch64", "dmg"),
        ("macos-aarch64", "pkg"),
    ],
)
def test_code_sign_rejected_without_signable_artifact(
    tmp_path: Path, platform: str, fmt: str
):
    text = f"""
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
python = "3.12"
identifier = "com.example.helloworld"
launchers = [ {{ name = "helloworld", entry = "helloworld:main" }} ]

[[tool.pyappdist.targets]]
name = "t"
platform = "{platform}"
format = "{fmt}"
code-sign = true
"""
    with pytest.raises(ConfigError, match="code-sign is not supported"):
        load_configs(_write_text(tmp_path, text))


def test_launcher_build_default_prebuilt(tmp_path: Path):
    assert load_configs(_write(tmp_path))[0].launcher_build == "prebuilt"


def test_launcher_build_parsed(tmp_path: Path):
    for value in ("prebuilt", "source"):
        cfg = load_configs(
            _write(tmp_path, target_extra=f'launcher-build = "{value}"')
        )[0]
        assert cfg.launcher_build == value


def test_launcher_build_rejects_unknown_value(tmp_path: Path):
    with pytest.raises(ConfigError, match="launcher-build must be one of"):
        load_configs(_write(tmp_path, target_extra='launcher-build = "never"'))


def test_launcher_build_on_compiled_launcher_formats(tmp_path: Path):
    # msix and a Windows image target compile launchers like msi does.
    for fmt in ("msix", "image"):
        cfg = load_configs(
            _write(tmp_path, fmt=fmt, target_extra='launcher-build = "source"')
        )[0]
        assert cfg.launcher_build == "source"


@pytest.mark.parametrize(
    "platform, fmt",
    [
        ("linux-x86_64", "linux"),
        ("linux-x86_64", "image"),   # non-Windows image: shell wrappers
        ("macos-aarch64", "macos"),
        ("macos-aarch64", "image"),
    ],
)
def test_launcher_build_rejected_on_shell_wrapper_formats(
    tmp_path: Path, platform: str, fmt: str
):
    text = f"""
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
python = "3.12"
launchers = [ {{ name = "helloworld", entry = "helloworld:main" }} ]

[[tool.pyappdist.targets]]
name = "t"
platform = "{platform}"
format = "{fmt}"
launcher-build = "prebuilt"
"""
    with pytest.raises(ConfigError, match="launcher-build has no effect"):
        load_configs(_write_text(tmp_path, text))


def test_launcher_build_on_macos_bundle_formats(tmp_path: Path):
    # macapp/dmg/pkg compile a Mach-O launcher, so the key applies there.
    text = """
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
python = "3.12"
identifier = "com.example.helloworld"
launchers = [ { name = "helloworld", entry = "helloworld:main" } ]

[[tool.pyappdist.targets]]
name = "t"
platform = "macos-aarch64"
format = "dmg"
launcher-build = "source"
"""
    assert load_configs(_write_text(tmp_path, text))[0].launcher_build == "source"


def test_code_sign_command_alone_is_inert(tmp_path: Path):
    # Without code-sign (or --code-sign) the command is stored but signing stays off.
    cfg = load_configs(
        _write(tmp_path, target_extra='code-sign-command = "mysign {file}"')
    )[0]
    assert cfg.code_sign is False
    assert cfg.code_sign_command == "mysign {file}"


def test_allow_same_version_upgrades_default_false(tmp_path: Path):
    cfg = load_configs(_write(tmp_path))[0]
    assert cfg.wix.allow_same_version_upgrades is False


def test_allow_same_version_upgrades_parsed(tmp_path: Path):
    cfg = load_configs(
        _write(tmp_path, target_extra="allow-same-version-upgrades = true")
    )[0]
    assert cfg.wix.allow_same_version_upgrades is True


def test_add_to_path_default_off(tmp_path: Path):
    cfg = load_configs(_write(tmp_path))[0]
    assert cfg.wix.add_to_path is False


def test_add_to_path_parsed(tmp_path: Path):
    cfg = load_configs(_write(tmp_path, target_extra="add-to-path = true"))[0]
    assert cfg.wix.add_to_path is True


def test_add_to_path_must_be_bool(tmp_path: Path):
    with pytest.raises(ConfigError, match="add-to-path"):
        load_configs(_write(tmp_path, target_extra='add-to-path = "yes"'))


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


def test_format_accepted_on_arm_platforms(tmp_path: Path):
    # The arm platforms take the same formats as their x86_64 siblings.
    msi_on_win_arm = _BASE.format(fmt="msi", app_extra="", target_extra="").replace(
        '"windows-x86_64"', '"windows-arm64"'
    )
    cfg = load_configs(_write_text(tmp_path, msi_on_win_arm))[0]
    assert cfg.target.triple == "aarch64-pc-windows-msvc"

    linux_on_aarch64 = _BASE.format(fmt="linux", app_extra="", target_extra="").replace(
        '"windows-x86_64"', '"linux-aarch64"'
    )
    cfg = load_configs(_write_text(tmp_path, linux_on_aarch64))[0]
    assert cfg.target.triple == "aarch64-unknown-linux-gnu"


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


@pytest.mark.parametrize("fmt", ["macapp", "dmg", "pkg"])
def test_format_app_dmg_accepted(tmp_path: Path, fmt: str):
    cfg = load_configs(
        _write_text(tmp_path, _macos_app_pyproject(fmt, app_extra=_IDENT))
    )[0]
    assert cfg.format == fmt
    assert cfg.target.os == "macos"
    assert cfg.identifier == "com.example.helloworld"


@pytest.mark.parametrize("fmt", ["macapp", "dmg", "pkg"])
def test_app_dmg_require_identifier(tmp_path: Path, fmt: str):
    # No app-level identifier -> error (a .app needs a CFBundleIdentifier).
    with pytest.raises(ConfigError, match="identifier is required"):
        load_configs(_write_text(tmp_path, _macos_app_pyproject(fmt)))


@pytest.mark.parametrize("fmt", ["macapp", "dmg", "pkg"])
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


def _macos_multi_launcher_pyproject(name_a: str, name_b: str) -> str:
    """A macapp pyproject with two launchers (each .app derives its own bundle id)."""
    return _macos_app_pyproject("macapp", app_extra=_IDENT).replace(
        '{ name = "helloworld", entry = "helloworld:main" },',
        f'{{ name = "{name_a}", entry = "helloworld:main" }},\n'
        f'  {{ name = "{name_b}", entry = "helloworld:other" }},',
    )


@pytest.mark.parametrize("name", ["My App", "my_tool", "a.b", "ハロー", "hello-world"])
def test_app_multi_launcher_name_unconstrained(tmp_path: Path, name: str):
    # The bundle-identifier segment is the base32 of the name, which is legal whatever
    # the name is — so no name has to be rejected for a macapp/dmg/pkg target.
    text = _macos_multi_launcher_pyproject("helloworld", name)
    cfg = load_configs(_write_text(tmp_path, text))[0]
    assert cfg.launchers[1].name == name


@pytest.mark.parametrize(
    "name,segment",
    [
        ("My App", "JV4SAQLQOA"),
        ("my_tool", "NV4V65DPN5WA"),
        # base32 of "ハロー" starts with a digit, so it takes the letter prefix.
        ("ハロー", "App4OBY7Y4DVXRYHPA"),
    ],
)
def test_identifier_segment_is_base32(name: str, segment: str):
    spec = LauncherConfig(name=name, entry="helloworld:main")
    assert spec.identifier_segment == segment
    raw = segment.removeprefix("App")
    assert base64.b32decode(raw + "=" * (-len(raw) % 8)).decode() == name


def test_identifier_segments_never_collide(tmp_path: Path):
    # Names that any character-folding scheme would map together stay distinct, and
    # bundle identifiers compare case-insensitively — so check the folded segments too.
    names = ["my tool", "My_Tool", "my-tool", "MY TOOL"]
    specs = [LauncherConfig(name=n, entry="helloworld:main") for n in names]
    segments = [spec.identifier_segment.casefold() for spec in specs]
    assert len(set(segments)) == len(names)


def test_app_single_launcher_name_unconstrained(tmp_path: Path):
    # One launcher -> the .app uses the app-level identifier as-is; the launcher
    # name never enters a bundle identifier, so underscores/unicode stay allowed.
    text = _macos_app_pyproject("macapp", app_extra=_IDENT).replace(
        'name = "helloworld", entry', 'name = "my_tool", entry'
    )
    cfg = load_configs(_write_text(tmp_path, text))[0]
    assert cfg.launchers[0].name == "my_tool"


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


def test_pkg_installer_identity_parsed(tmp_path: Path):
    extra = 'installer-identity = "Developer ID Installer: Me (TEAMID)"\n'
    cfg = load_configs(
        _write_text(
            tmp_path, _macos_app_pyproject("pkg", app_extra=_IDENT, target_extra=extra)
        )
    )[0]
    assert cfg.macos.installer_identity == "Developer ID Installer: Me (TEAMID)"


def test_pkg_installer_identity_default_none(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _macos_app_pyproject("pkg", app_extra=_IDENT)))[0]
    assert cfg.macos.installer_identity is None


@pytest.mark.parametrize("filename", ["LICENSE.txt", "EULA.rtf", "legal/eula.html"])
def test_pkg_license_parsed(tmp_path: Path, filename: str):
    extra = f'license = "{filename}"\n'
    cfg = load_configs(
        _write_text(
            tmp_path, _macos_app_pyproject("pkg", app_extra=_IDENT, target_extra=extra)
        )
    )[0]
    assert cfg.macos.license == filename
    # A pkg license never leaks into the MSI-side config.
    assert cfg.wix.license is None


def test_pkg_license_default_none(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _macos_app_pyproject("pkg", app_extra=_IDENT)))[0]
    assert cfg.macos.license is None


def test_pkg_license_bad_extension(tmp_path: Path):
    # RTFD bundles are directories, so only flat txt/rtf/html files are accepted.
    extra = 'license = "LICENSE.rtfd"\n'
    with pytest.raises(ConfigError, match=r"\.txt, \.rtf, or \.html"):
        load_configs(
            _write_text(
                tmp_path, _macos_app_pyproject("pkg", app_extra=_IDENT, target_extra=extra)
            )
        )


@pytest.mark.parametrize("fmt", ["msix", "macapp", "dmg"])
def test_license_rejected_on_formats_without_license_page(tmp_path: Path, fmt: str):
    if fmt == "msix":  # msix targets a windows platform, the bundle formats macOS
        text = _BASE.format(fmt=fmt, app_extra="", target_extra='license = "EULA.rtf"\n')
    else:
        text = _macos_app_pyproject(
            fmt, app_extra=_IDENT, target_extra='license = "EULA.rtf"\n'
        )
    with pytest.raises(ConfigError, match="license is only supported"):
        load_configs(_write_text(tmp_path, text))


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


def test_ensure_upgrade_code_rejects_invalid_existing(tmp_path: Path):
    # A mistyped code must never be silently replaced with a fresh GUID:
    # that would break MajorUpgrade of already-shipped installs.
    invalid = "7E3F9A2C-5B1D-4E8A-9C6F-1A2B3C4D5E6"  # one hex digit short
    proj = _write(tmp_path, target_extra=f'upgrade-code = "{invalid}"')
    before = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    with pytest.raises(ConfigError, match="upgrade-code"):
        ensure_upgrade_code(proj, "win", log=lambda _m: None)
    # the user's value stays in the file untouched
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == before


def test_invalid_upgrade_code_rejected_at_load(tmp_path: Path):
    with pytest.raises(ConfigError, match="upgrade-code must be a valid GUID"):
        load_configs(_write(tmp_path, target_extra='upgrade-code = "not-a-guid"'))
    with pytest.raises(ConfigError, match="upgrade-code must be a valid GUID"):
        load_configs(_write(tmp_path, target_extra='upgrade-code = ""'))


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
    "bad",
    # Only U+0020 is allowed as whitespace; a NBSP is not.
    ["a:b", "a/b", "a\\b", 'a"b', "a\tb", "a*b", " app", "app ", "a\u00a0b"],
)
def test_launcher_name_rejects_unsafe_chars(tmp_path: Path, bad: str):
    # TOML literal strings ('...') take the name verbatim, no escape processing.
    text = _launcher_pyproject(f"'{bad}'")
    with pytest.raises(ConfigError, match="launchers\\[0\\].name"):
        load_configs(_write_text(tmp_path, text))


def test_launcher_name_allows_unicode(tmp_path: Path):
    cfg = load_configs(_write_text(tmp_path, _launcher_pyproject("'ハローワールド'")))[0]
    assert cfg.launchers[0].name == "ハローワールド"


def test_launcher_name_allows_inner_spaces(tmp_path: Path):
    # "My App.exe" is an ordinary Windows/macOS app name; only tabs, newlines and
    # leading/trailing spaces are rejected.
    cfg = load_configs(_write_text(tmp_path, _launcher_pyproject("'My App'")))[0]
    assert cfg.launchers[0].name == "My App"


def _two_launcher_pyproject(name_a: str, name_b: str) -> str:
    """A pyproject with two launchers named ``name_a`` and ``name_b``."""
    return _launcher_pyproject(f'"{name_a}"').replace(
        f'launchers = [ {{ name = "{name_a}", entry = "helloworld:main" }} ]',
        f'launchers = [\n'
        f'  {{ name = "{name_a}", entry = "helloworld:main" }},\n'
        f'  {{ name = "{name_b}", entry = "helloworld:other" }},\n'
        f']',
    )


def test_duplicate_launcher_name(tmp_path: Path):
    # Same-named launchers clobber each other's exe and break WiX; reject at load.
    text = _two_launcher_pyproject("app", "app")
    with pytest.raises(ConfigError, match="duplicate.*launchers.*'app'"):
        load_configs(_write_text(tmp_path, text))


def test_duplicate_launcher_name_case_insensitive(tmp_path: Path):
    # Case-only variants collide on the case-insensitive Windows filesystem.
    text = _two_launcher_pyproject("App", "app")
    with pytest.raises(ConfigError, match="duplicate.*launchers"):
        load_configs(_write_text(tmp_path, text))


def test_distinct_launcher_names_accepted(tmp_path: Path):
    cfgs = load_configs(_write_text(tmp_path, _two_launcher_pyproject("app", "tool")))
    assert [spec.name for spec in cfgs[0].launchers] == ["app", "tool"]


def test_msi_rejects_non_numeric_version(tmp_path: Path):
    text = _BASE.format(fmt="msi", app_extra='version = "0.1.0a1"', target_extra="")
    with pytest.raises(ConfigError, match="numeric version"):
        load_configs(_write_text(tmp_path, text))


def test_posix_allows_non_numeric_version(tmp_path: Path):
    text = _BASE.format(
        fmt="linux", app_extra='version = "0.1.0a1"', target_extra=""
    ).replace('"windows-x86_64"', '"linux-x86_64"')
    cfg = load_configs(_write_text(tmp_path, text))[0]
    assert cfg.version == "0.1.0a1"


def test_msi_four_field_version_warns(tmp_path: Path, capsys):
    # Accepted, but MSI compares only the first three fields for upgrades.
    text = _BASE.format(fmt="msi", app_extra='version = "1.2.3.4"', target_extra="")
    cfg = load_configs(_write_text(tmp_path, text))[0]
    assert cfg.version == "1.2.3.4"
    err = capsys.readouterr().err
    assert "four fields" in err and "1.2.3.4" in err


def test_msi_three_field_version_does_not_warn(tmp_path: Path, capsys):
    load_configs(_write(tmp_path, app_extra='version = "1.2.3"'))
    assert capsys.readouterr().err == ""


def test_msix_four_field_version_does_not_warn(tmp_path: Path, capsys):
    # MSIX's Identity Version legitimately uses all four fields.
    text = _BASE.format(fmt="msix", app_extra='version = "1.2.3.4"', target_extra="")
    load_configs(_write_text(tmp_path, text))
    assert capsys.readouterr().err == ""


# An msi target and a linux target side by side, so select-scoped validation can be
# exercised: the msi-only version check must not fire when only "lin" is selected.
_MSI_PLUS_LINUX = """
[project]
name = "helloworld"

[tool.pyappdist]
version = "0.1.0a1"
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


@pytest.mark.parametrize(
    "platform",
    [
        "windows-x86_64", "windows-arm64", "linux-x86_64", "linux-aarch64",
        "macos-aarch64", "macos-x86_64",
    ],
)
def test_format_image_accepted_on_all_platforms(tmp_path: Path, platform: str):
    text = _BASE.format(fmt="image", app_extra="", target_extra="").replace(
        '"windows-x86_64"', f'"{platform}"'
    )
    cfg = load_configs(_write_text(tmp_path, text))[0]
    assert cfg.format == "image"
    assert cfg.no_launcher is False


def test_no_launcher_parsed(tmp_path: Path):
    cfg = load_configs(
        _write(tmp_path, fmt="image", target_extra="no-launcher = true")
    )[0]
    assert cfg.no_launcher is True


def test_no_launcher_must_be_bool(tmp_path: Path):
    with pytest.raises(ConfigError, match="no-launcher"):
        load_configs(_write(tmp_path, fmt="image", target_extra='no-launcher = "yes"'))


def test_no_launcher_rejected_on_non_image_format(tmp_path: Path):
    with pytest.raises(ConfigError, match="no-launcher"):
        load_configs(_write(tmp_path, fmt="msi", target_extra="no-launcher = true"))
