"""Tests for the launcher bootstrap string generation (OS-independent, pure functions)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyappdist.config import Config, LauncherConfig
from pyappdist.errors import BuildError
from pyappdist.image.layout import ImageLayout
from pyappdist.launcher import build as launcher_build
from pyappdist.launcher.build import _bootstrap


def _with_launcher(config: Config, launcher: LauncherConfig) -> Config:
    return dataclasses.replace(config, launchers=(launcher,))


def test_bootstrap_gui_callable_wraps_in_messagebox(sample_config: Config):
    spec = LauncherConfig(name="app", entry="pkg.mod:main", gui=True)
    out = _bootstrap(spec, _with_launcher(sample_config, spec))
    assert "from pkg.mod import main" in out
    assert "MessageBoxW" in out
    assert "sys.exit(main())" in out


def test_bootstrap_gui_module_form_no_wrapper(sample_config: Config):
    """The python -m (dotted) form is not wrapped, even for a GUI launcher."""
    spec = LauncherConfig(name="app", entry="pkg.mod", gui=True)
    out = _bootstrap(spec, _with_launcher(sample_config, spec))
    assert out == spec.bootstrap
    assert "runpy.run_module('pkg.mod'" in out
    assert "MessageBoxW" not in out


def test_bootstrap_console_uses_spec_bootstrap(sample_config: Config):
    spec = LauncherConfig(name="app", entry="pkg.mod:main", gui=False)
    assert _bootstrap(spec, _with_launcher(sample_config, spec)) == spec.bootstrap


# --- build.bat generation / vcvars failure --------------------------------


class _FakeProc:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = "vcvars: cannot determine the Windows SDK version"


def _run_build_one(config: Config, tmp_path: Path, monkeypatch, returncode: int):
    """Drive _build_one with cmd.exe stubbed out; returns the generated build.bat text."""
    spec = config.launchers[0]
    layout = ImageLayout(
        image_dir=tmp_path / "image", target=config.target, minor=config.python_minor
    )
    layout.image_dir.mkdir(parents=True)
    workdir = tmp_path / "_launcher_build"
    monkeypatch.setattr(
        launcher_build.subprocess, "run", lambda *a, **kw: _FakeProc(returncode)
    )
    launcher_build._build_one(
        config, spec, layout, r"C:\VS\vcvars64.bat", workdir, lambda m: None
    )
    return (workdir / spec.name / "build.bat").read_text(encoding="ascii")


def test_build_bat_checks_vcvars(sample_config: Config, tmp_path: Path, monkeypatch):
    # A failing vcvars must stop the batch immediately; without the check it fell
    # through to rc and surfaced as "'rc' is not recognized".
    with pytest.raises(BuildError):
        _run_build_one(sample_config, tmp_path, monkeypatch, launcher_build._VCVARS_EXIT)
    bat = (tmp_path / "_launcher_build" / "helloworld" / "build.bat").read_text()
    lines = [line.strip() for line in bat.splitlines() if line.strip()]
    call_at = lines.index("call %1 >nul")
    assert lines[call_at + 1] == f"if errorlevel 1 exit /b {launcher_build._VCVARS_EXIT}"


def test_vcvars_failure_names_the_cause(sample_config: Config, tmp_path: Path, monkeypatch):
    with pytest.raises(BuildError, match="Visual Studio environment script failed") as exc:
        _run_build_one(sample_config, tmp_path, monkeypatch, launcher_build._VCVARS_EXIT)
    # vcvars' own stderr reaches the user (only its stdout is silenced).
    assert "Windows SDK version" in str(exc.value)
    assert r"C:\VS\vcvars64.bat" in str(exc.value)


def test_compiler_failure_keeps_generic_message(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    # cl exits 2 on compile errors; that must not be mistaken for a vcvars failure.
    with pytest.raises(BuildError, match="launcher build failed") as exc:
        _run_build_one(sample_config, tmp_path, monkeypatch, 2)
    assert "Visual Studio environment script" not in str(exc.value)


# --- fixed args: one canonical split, rendered per launcher kind ------------


@pytest.mark.parametrize(
    "args,expected",
    [
        ("", ()),
        ("--verbose", ("--verbose",)),
        ("--path 'a b'", ("--path", "a b")),
        ('--path "a b"', ("--path", "a b")),
        ("-x *", ("-x", "*")),          # never glob-expanded
        ("--name 'it''s'", ("--name", "its")),
    ],
)
def test_argv_splits_with_posix_rules(args: str, expected: tuple[str, ...]):
    assert LauncherConfig(name="app", entry="m:main", args=args).argv == expected


@pytest.mark.parametrize(
    "arg,expected",
    [
        ("plain", "plain"),
        ("a b", '"a b"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("C:\\dir\\", "C:\\dir\\"),          # no quoting needed, so no doubling
        ("C:\\a b\\", '"C:\\a b\\\\"'),      # trailing run doubled before the quote
        ('a\\"b', '"a\\\\\\"b"'),            # backslash before a quote is doubled
    ],
)
def test_msvc_quote(arg: str, expected: str):
    assert launcher_build.msvc_quote(arg) == expected


@pytest.mark.parametrize(
    "args,expected",
    [
        ("", ""),
        ("--verbose", "--verbose"),
        ("--path 'a b'", '--path "a b"'),   # one argument, not two
        ("-x *", "-x *"),                   # the child does not glob
    ],
)
def test_windows_fixed_args_are_requoted(args: str, expected: str):
    # launcher.c appends this verbatim, so it must already be MSVC-quoted.
    spec = LauncherConfig(name="app", entry="m:main", args=args)
    assert launcher_build._windows_fixed_args(spec) == expected


def test_macos_fixed_args_array():
    spec = LauncherConfig(name="app", entry="m:main", args="--path 'a b'")
    assert launcher_build._fixed_args_initializer(spec) == '{ "--path", "a b", NULL }'


def test_macos_fixed_args_empty():
    spec = LauncherConfig(name="app", entry="m:main")
    assert launcher_build._fixed_args_initializer(spec) == "{ NULL }"
