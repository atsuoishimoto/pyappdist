"""Resolution of the macOS signing/notarization settings (env overrides config)."""

from __future__ import annotations

from dataclasses import replace

from pyappdist.config import MacosConfig
from pyappdist.macos.notarize import resolve_notary_profile
from pyappdist.macos.pkg import resolve_installer_identity
from pyappdist.macos.sign import resolve_sign_options

_ENVS = (
    "PYAPPDIST_MACOS_SIGNING_IDENTITY",
    "PYAPPDIST_MACOS_NOTARY_PROFILE",
    "PYAPPDIST_MACOS_INSTALLER_IDENTITY",
)


def _config(sample_config, **macos_kwargs):
    return replace(sample_config, macos=MacosConfig(**macos_kwargs))


def _clear_envs(monkeypatch):
    for env in _ENVS:
        monkeypatch.delenv(env, raising=False)


def test_signing_identity_env_overrides_config(sample_config, tmp_path, monkeypatch):
    _clear_envs(monkeypatch)
    monkeypatch.setenv("PYAPPDIST_MACOS_SIGNING_IDENTITY", "Env Application ID")
    config = _config(sample_config, signing_identity="Config Application ID")
    opts = resolve_sign_options(config, tmp_path, log=lambda *a: None)
    assert opts.identity == "Env Application ID"
    assert opts.hardened


def test_signing_identity_config_when_env_unset(sample_config, tmp_path, monkeypatch):
    _clear_envs(monkeypatch)
    config = _config(sample_config, signing_identity="Config Application ID")
    opts = resolve_sign_options(config, tmp_path, log=lambda *a: None)
    assert opts.identity == "Config Application ID"


def test_signing_identity_adhoc_when_neither(sample_config, tmp_path, monkeypatch):
    _clear_envs(monkeypatch)
    opts = resolve_sign_options(_config(sample_config), tmp_path, log=lambda *a: None)
    assert opts.adhoc


def test_notary_profile_env_overrides_config(sample_config, monkeypatch):
    _clear_envs(monkeypatch)
    monkeypatch.setenv("PYAPPDIST_MACOS_NOTARY_PROFILE", "env-profile")
    config = _config(sample_config, notary_profile="config-profile")
    assert resolve_notary_profile(config) == "env-profile"


def test_notary_profile_config_when_env_unset(sample_config, monkeypatch):
    _clear_envs(monkeypatch)
    config = _config(sample_config, notary_profile="config-profile")
    assert resolve_notary_profile(config) == "config-profile"


def test_installer_identity_env_overrides_config(sample_config, monkeypatch):
    _clear_envs(monkeypatch)
    monkeypatch.setenv("PYAPPDIST_MACOS_INSTALLER_IDENTITY", "Env Installer ID")
    config = _config(sample_config, installer_identity="Config Installer ID")
    assert resolve_installer_identity(config) == "Env Installer ID"


def test_installer_identity_config_when_env_unset(sample_config, monkeypatch):
    _clear_envs(monkeypatch)
    config = _config(sample_config, installer_identity="Config Installer ID")
    assert resolve_installer_identity(config) == "Config Installer ID"
