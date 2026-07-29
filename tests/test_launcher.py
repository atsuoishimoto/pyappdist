"""Tests for the launcher bootstrap string generation (OS-independent, pure functions)."""

from __future__ import annotations

import dataclasses

import pytest

from pyappdist.config import Config, LauncherConfig
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
