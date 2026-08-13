"""Tests for the macOS .app/.dmg packaging helpers (pure logic; no external tools)."""

from __future__ import annotations

import dataclasses
import plistlib
from pathlib import Path

import pytest

from pyappdist.config import Config, LauncherConfig, MacosConfig, MsixConfig, WixConfig
from pyappdist.errors import BuildError
from pyappdist.launcher.build import macos_arch
from pyappdist.macos.bundle import build_macos_apps, bundle_label, info_plist
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


def _with_launchers(*launchers: LauncherConfig) -> Config:
    return dataclasses.replace(_macos_config(), launchers=launchers)


def test_bundle_label_single_visible_uses_app_name():
    cfg = _with_launchers(LauncherConfig(name="helloworld", entry="helloworld:main"))
    assert bundle_label(cfg, cfg.launchers[0]) == "Hello World"


def test_bundle_label_multi_visible_uses_launcher_names():
    cfg = _with_launchers(
        LauncherConfig(name="mytool", entry="helloworld:main"),
        LauncherConfig(name="MyApp", entry="helloworld:gui", gui=True),
    )
    assert bundle_label(cfg, cfg.launchers[0]) == "mytool"
    assert bundle_label(cfg, cfg.launchers[1]) == "MyApp"


def test_bundle_label_hidden_maps_to_first_visible():
    # A hidden launcher lives inside the first visible launcher's bundle; with a
    # single visible launcher that bundle is named after the app.
    cfg = _with_launchers(
        LauncherConfig(name="MyApp", entry="helloworld:gui", gui=True),
        LauncherConfig(name="mytool", entry="helloworld:main", app_entry=False),
    )
    assert bundle_label(cfg, cfg.launchers[1]) == "Hello World"


def test_bundle_label_title_wins_single_and_multi():
    # A title overrides both defaults: the app name (single visible launcher)
    # and the launcher name (several visible launchers).
    cfg = _with_launchers(
        LauncherConfig(name="helloworld", entry="helloworld:main", title="My Application")
    )
    assert bundle_label(cfg, cfg.launchers[0]) == "My Application"

    cfg = _with_launchers(
        LauncherConfig(name="mytool", entry="helloworld:main", title="My Tool"),
        LauncherConfig(name="MyApp", entry="helloworld:gui", gui=True),
    )
    assert bundle_label(cfg, cfg.launchers[0]) == "My Tool"
    assert bundle_label(cfg, cfg.launchers[1]) == "MyApp"


def test_bundle_label_hidden_follows_host_title():
    # A hidden launcher lives in the first visible launcher's bundle, so it
    # follows that bundle's title.
    cfg = _with_launchers(
        LauncherConfig(name="MyApp", entry="helloworld:gui", gui=True, title="My Application"),
        LauncherConfig(name="mytool", entry="helloworld:main", app_entry=False),
    )
    assert bundle_label(cfg, cfg.launchers[1]) == "My Application"


def test_bundle_label_all_hidden_rejected():
    cfg = _with_launchers(
        LauncherConfig(name="mytool", entry="helloworld:main", app_entry=False)
    )
    with pytest.raises(BuildError, match="app-entry"):
        bundle_label(cfg, cfg.launchers[0])


def _fake_image(tmp_path: Path, *names: str) -> Path:
    """A minimal image tree: a stand-in python plus a stub + sidecar per launcher."""
    image = tmp_path / "image"
    (image / "python" / "bin").mkdir(parents=True)
    (image / "python" / "bin" / "python3").write_text("#!/bin/sh\n")
    for name in names:
        (image / name).write_bytes(b"stub")
        (image / f"{name}.launcher.json").write_text("{}")
    return image


@pytest.fixture
def fake_icns(monkeypatch):
    """make_icns needs sips/iconutil (macOS-only); stand in a dummy .icns."""
    def _make(source_png, dest_icns, *, log=print):
        dest_icns.write_bytes(b"icns")
        return dest_icns

    monkeypatch.setattr("pyappdist.macos.bundle.make_icns", _make)


def test_build_macos_apps_embeds_hidden_launcher(tmp_path, fake_icns):
    image = _fake_image(tmp_path, "MyApp", "mytool")
    cfg = _with_launchers(
        LauncherConfig(name="MyApp", entry="helloworld:gui", gui=True),
        LauncherConfig(name="mytool", entry="helloworld:main", app_entry=False),
    )
    apps = build_macos_apps(cfg, image, tmp_path / "out", log=lambda *a: None)
    # The hidden launcher gets no bundle of its own...
    assert [app.name for app in apps] == ["Hello World.app"]
    app = apps[0]
    # ...its executable and sidecar are embedded into the visible launcher's bundle,
    # each sidecar staged under its per-executable name.
    assert (app / "Contents" / "MacOS" / "mytool").is_file()
    assert (app / "Contents" / "Resources" / "mytool.launcher.json").is_file()
    assert (app / "Contents" / "Resources" / "MyApp.launcher.json").is_file()
    # The sole visible launcher keeps the app-level identity.
    plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert plist["CFBundleIdentifier"] == "com.example.helloworld"
    assert plist["CFBundleExecutable"] == "MyApp"


def test_build_macos_apps_all_hidden_rejected(tmp_path, fake_icns):
    image = _fake_image(tmp_path, "mytool")
    cfg = _with_launchers(
        LauncherConfig(name="mytool", entry="helloworld:main", app_entry=False)
    )
    with pytest.raises(BuildError, match="app-entry"):
        build_macos_apps(cfg, image, tmp_path / "out", log=lambda *a: None)
