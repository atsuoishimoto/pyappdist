"""Tests for the macOS .app/.dmg packaging helpers (pure logic; no external tools)."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from pyappdist.config import Config, LauncherConfig, MacosConfig, MsixConfig, WixConfig
from pyappdist.launcher.build import macos_arch
from pyappdist.macos.bundle import info_plist
from pyappdist.macos.sign import SignOptions, entitlements_plist
from pyappdist.targets import get_target


def _macos_config(**macos_kw) -> Config:
    return Config(
        project_dir=Path("/proj"),
        name="Hello World",
        dist_name="helloworld",
        version="1.2.3",
        python="3.12",
        identifier="com.example.helloworld",
        target=get_target("macos-aarch64"),
        target_name="macos-arm",
        format="dmg",
        launchers=(LauncherConfig(name="helloworld", entry="helloworld:main"),),
        wix=WixConfig(),
        msix=MsixConfig(),
        manager=None,
        macos=MacosConfig(**macos_kw),
    )


@pytest.mark.parametrize(
    "platform,expected", [("macos-aarch64", "arm64"), ("macos-x86_64", "x86_64")]
)
def test_macos_arch(platform: str, expected: str):
    assert macos_arch(get_target(platform)) == expected


def test_info_plist_core_keys():
    cfg = _macos_config()
    plist = plistlib.loads(
        info_plist(cfg, executable="helloworld", identifier=cfg.identifier, display_name="Hello World")
    )
    assert plist["CFBundleExecutable"] == "helloworld"
    assert plist["CFBundleIdentifier"] == "com.example.helloworld"
    assert plist["CFBundleName"] == "Hello World"
    assert plist["CFBundlePackageType"] == "APPL"
    assert plist["CFBundleShortVersionString"] == "1.2.3"
    assert plist["CFBundleIconFile"] == "AppIcon"  # extension omitted by convention
    assert plist["LSMinimumSystemVersion"] == "11.0"
    assert plist["NSHighResolutionCapable"] is True
    assert "LSApplicationCategoryType" not in plist  # no category set


def test_info_plist_min_macos_and_category():
    cfg = _macos_config(min_macos="12.3", category="public.app-category.utilities")
    plist = plistlib.loads(
        info_plist(cfg, executable="x", identifier="com.example.x", display_name="X")
    )
    assert plist["LSMinimumSystemVersion"] == "12.3"
    assert plist["LSApplicationCategoryType"] == "public.app-category.utilities"


def test_entitlements_default_disables_library_validation():
    ent = plistlib.loads(entitlements_plist())
    assert ent == {"com.apple.security.cs.disable-library-validation": True}


def test_sign_options_adhoc_default():
    opts = SignOptions()
    assert opts.adhoc
    assert not opts.hardened
    assert opts.entitlements is None
    assert not opts.timestamp


def test_sign_options_developer_id_not_adhoc():
    opts = SignOptions(
        identity="Developer ID Application: Me (TEAMID)", hardened=True, timestamp=True
    )
    assert not opts.adhoc
