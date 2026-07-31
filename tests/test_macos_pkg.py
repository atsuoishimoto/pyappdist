"""Tests for the macOS .pkg packaging helpers (pure logic; no external tools)."""

from __future__ import annotations

import dataclasses
import plistlib
from pathlib import Path

from pyappdist.config import Config, LauncherConfig, MacosConfig, MsixConfig, WixConfig
from pyappdist.macos.pkg import (
    distribution_xml,
    package_identifier,
    pin_bundle_locations,
    postinstall_script,
)
from pyappdist.targets import get_target


def _pkg_config(
    launchers: tuple[LauncherConfig, ...] = (
        LauncherConfig(name="helloworld", entry="helloworld:main"),
    ),
    **macos_kw,
) -> Config:
    return Config(
        project_dir=Path("/proj"),
        name="Hello World",
        dist_name="helloworld",
        version="1.2.3",
        python="3.12",
        identifier="com.example.helloworld",
        target=get_target("macos-aarch64"),
        target_name="macos-arm-pkg",
        format="pkg",
        launchers=launchers,
        wix=WixConfig(),
        msix=MsixConfig(),
        manager=None,
        macos=MacosConfig(**macos_kw),
    )


def test_package_identifier_suffixed():
    # ".pkg" keeps the receipt id distinct from the single-launcher .app's
    # CFBundleIdentifier (which is the bare app-level identifier).
    assert package_identifier(_pkg_config()) == "com.example.helloworld.pkg"


def test_distribution_xml_system_scope_only():
    xml = distribution_xml(_pkg_config(), "component.pkg")
    assert '<domains enable_localSystem="true"/>' in xml
    # The home-directory domain must not be offered: the install is system scope.
    assert "enable_currentUserHome" not in xml
    assert "enable_anywhere" not in xml


def test_distribution_xml_pkg_ref_and_version():
    xml = distribution_xml(_pkg_config(), "component.pkg")
    assert '<pkg-ref id="com.example.helloworld.pkg" version="1.2.3">component.pkg</pkg-ref>' in xml
    assert '<pkg-ref id="com.example.helloworld.pkg"/>' in xml  # the choice reference


def test_distribution_xml_title_and_min_os():
    xml = distribution_xml(_pkg_config(min_macos="12.0"), "component.pkg")
    assert "<title>Hello World</title>" in xml
    assert '<os-version min="12.0"/>' in xml


def test_distribution_xml_escapes_title():
    cfg = dataclasses.replace(_pkg_config(), name="Tom & Jerry <LLC>")
    xml = distribution_xml(cfg, "component.pkg")
    assert "<title>Tom &amp; Jerry &lt;LLC&gt;</title>" in xml


def test_pin_bundle_locations():
    analyzed = plistlib.dumps(
        [
            {
                "BundleIsRelocatable": True,
                "BundleIsVersionChecked": True,
                "BundleOverwriteAction": "upgrade",
                "RootRelativeBundlePath": "Applications/Hello World.app",
            }
        ]
    )
    components = plistlib.loads(pin_bundle_locations(analyzed))
    assert components[0]["BundleIsRelocatable"] is False
    # The other analyzed keys pass through untouched.
    assert components[0]["BundleOverwriteAction"] == "upgrade"
    assert components[0]["RootRelativeBundlePath"] == "Applications/Hello World.app"


def test_postinstall_symlinks_single_cli_launcher():
    # A single launcher's .app is named after the app-level name ("Hello World"),
    # so the symlink target contains a space and must be quoted.
    script = postinstall_script(_pkg_config())
    assert script is not None
    assert script.startswith("#!/bin/sh\n")
    assert "mkdir -p /usr/local/bin" in script
    assert (
        "ln -sfn '/Applications/Hello World.app/Contents/MacOS/helloworld' "
        "/usr/local/bin/helloworld" in script
    )


def test_postinstall_multi_launcher_uses_launcher_names():
    # With several launchers each .app is named after its launcher, and only the
    # non-gui ones get a symlink.
    launchers = (
        LauncherConfig(name="mytool", entry="helloworld:main"),
        LauncherConfig(name="MyApp", entry="helloworld:gui", gui=True),
    )
    script = postinstall_script(_pkg_config(launchers=launchers))
    assert script is not None
    assert "ln -sfn /Applications/mytool.app/Contents/MacOS/mytool /usr/local/bin/mytool" in script
    assert "MyApp" not in script


def test_postinstall_none_when_all_gui():
    launchers = (LauncherConfig(name="MyApp", entry="helloworld:gui", gui=True),)
    assert postinstall_script(_pkg_config(launchers=launchers)) is None
