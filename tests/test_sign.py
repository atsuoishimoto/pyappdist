from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from pyappdist.config import WixConfig
from pyappdist.errors import BuildError
from pyappdist.sign import (
    DEFAULT_MSI_SIGN_CMD,
    env_sign_command,
    resolve_msi_sign_command,
    sign_artifact,
)

_ENV = "PYAPPDIST_SIGN_CMD"


def test_resolve_off_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(_ENV, "should-be-ignored")
    # code_sign is off, so nothing signs even when the env var is set.
    assert resolve_msi_sign_command(WixConfig(code_sign=False)) is None


def test_resolve_default_when_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(_ENV, raising=False)
    assert resolve_msi_sign_command(WixConfig(code_sign=True)) == DEFAULT_MSI_SIGN_CMD


def test_resolve_config_over_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(_ENV, raising=False)
    wix = WixConfig(code_sign=True, code_sign_command="cfgsign {file}")
    assert resolve_msi_sign_command(wix) == "cfgsign {file}"


def test_resolve_env_over_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(_ENV, "envsign {file}")
    wix = WixConfig(code_sign=True, code_sign_command="cfgsign {file}")
    assert resolve_msi_sign_command(wix) == "envsign {file}"


def test_env_sign_command(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(_ENV, raising=False)
    assert env_sign_command() is None
    monkeypatch.setenv(_ENV, "envsign {file}")
    assert env_sign_command() == "envsign {file}"


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
