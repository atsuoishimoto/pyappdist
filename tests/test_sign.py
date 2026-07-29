from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from pyappdist import sign as sign_mod
from pyappdist.config import Config, MsixConfig, WixConfig
from pyappdist.errors import BuildError
from pyappdist.sign import (
    DEFAULT_WIN_SIGN_CMD,
    resolve_sign_command,
    sign_artifact,
)
from pyappdist.targets import get_target

_WIN_ENV = "PYAPPDIST_WIN_SIGN_CMD"
_LEGACY_ENV = "PYAPPDIST_SIGN_CMD"


def _config(**kwargs) -> Config:
    defaults = dict(
        project_dir=Path("/proj"),
        name="Hello World",
        dist_name="helloworld",
        version="1.2.3",
        python="3.12",
        identifier=None,
        target=get_target("windows-x86_64"),
        target_name="win",
        format="msi",
        launchers=(),
        wix=WixConfig(),
        msix=MsixConfig(),
        manager=None,
    )
    defaults.update(kwargs)
    return Config(**defaults)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for env in (_WIN_ENV, _LEGACY_ENV):
        monkeypatch.delenv(env, raising=False)


def test_resolve_off_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(_WIN_ENV, "should-be-ignored")
    # code_sign is off, so nothing signs even when the env var is set.
    assert resolve_sign_command(_config(code_sign=False), None) is None


def test_resolve_default_when_on():
    assert resolve_sign_command(_config(code_sign=True), None) == DEFAULT_WIN_SIGN_CMD


def test_resolve_config_over_default():
    cfg = _config(code_sign=True, code_sign_command="cfgsign {file}")
    assert resolve_sign_command(cfg, None) == "cfgsign {file}"


def test_resolve_env_over_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(_WIN_ENV, "envsign {file}")
    cfg = _config(code_sign=True, code_sign_command="cfgsign {file}")
    assert resolve_sign_command(cfg, None) == "envsign {file}"


def test_resolve_cli_forces_on():
    # --code-sign overrides code-sign = false (and the unset default).
    assert resolve_sign_command(_config(code_sign=False), True) == DEFAULT_WIN_SIGN_CMD


def test_resolve_cli_forces_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(_WIN_ENV, "envsign {file}")
    assert resolve_sign_command(_config(code_sign=True), False) is None


def test_legacy_env_is_ignored_with_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    monkeypatch.setenv(_LEGACY_ENV, "legacysign {file}")
    monkeypatch.setattr(sign_mod, "_legacy_warned", False)
    # The legacy variable neither enables signing nor supplies the command.
    assert resolve_sign_command(_config(code_sign=False), None) is None
    assert resolve_sign_command(_config(code_sign=True), None) == DEFAULT_WIN_SIGN_CMD
    err = capsys.readouterr().err
    assert err.count(_LEGACY_ENV) == 1  # warned once, not per resolution
    assert _WIN_ENV in err


def test_no_warning_without_legacy_env(capsys: pytest.CaptureFixture, monkeypatch):
    monkeypatch.setattr(sign_mod, "_legacy_warned", False)
    resolve_sign_command(_config(), None)
    assert capsys.readouterr().err == ""


def test_sign_artifact_skips_without_command(tmp_path: Path):
    target = tmp_path / "app.msi"
    target.write_bytes(b"")
    assert sign_artifact(target, None) is False
    assert sign_artifact(target, "") is False


# Writes the cwd and the received file argument to record.txt (in the cwd), so tests
# can assert how sign_artifact invoked the command.
_RECORD_SNIPPET = "import os,sys; open('record.txt','w').write(os.getcwd()+chr(10)+sys.argv[1])"


def _read_record(tmp_path: Path) -> tuple[str, str]:
    cwd, arg = (tmp_path / "record.txt").read_text().splitlines()
    return cwd, arg


def test_sign_artifact_runs_in_artifact_dir_with_file_name(tmp_path: Path):
    # The command must run with cwd = the artifact's directory and receive the bare
    # file name for {file}: WSL cross-builds rely on this (signtool.exe cannot
    # resolve an absolute Linux path).
    target = tmp_path / "app.msi"
    target.write_bytes(b"")
    command = f'"{sys.executable}" -c "{_RECORD_SNIPPET}" "{{file}}"'
    assert sign_artifact(target, command) is True
    cwd, arg = _read_record(tmp_path)
    assert os.path.samefile(cwd, tmp_path)
    assert arg == "app.msi"


def test_sign_artifact_appends_file_name_without_token(tmp_path: Path):
    target = tmp_path / "app.msi"
    target.write_bytes(b"")
    command = f'"{sys.executable}" -c "{_RECORD_SNIPPET}"'
    assert sign_artifact(target, command) is True
    cwd, arg = _read_record(tmp_path)
    assert os.path.samefile(cwd, tmp_path)
    assert arg == "app.msi"


def test_sign_artifact_failure_raises(tmp_path: Path):
    target = tmp_path / "app.msi"
    target.write_bytes(b"")
    command = f'"{sys.executable}" -c "import sys; sys.exit(1)" "{{file}}"'
    with pytest.raises(BuildError, match="signing failed"):
        sign_artifact(target, command)
