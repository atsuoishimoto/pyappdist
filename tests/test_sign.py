from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.config import WixConfig
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
