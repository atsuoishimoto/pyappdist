"""Tests for the launcher bootstrap string generation (OS-independent, pure functions)."""

from __future__ import annotations

import dataclasses

from pyappdist.config import Config, LauncherConfig
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
