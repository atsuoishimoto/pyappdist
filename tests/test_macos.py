"""Tests for macOS bundle helpers (Info.plist + Mach-O detection).

Pure-function tests only; the heavy toolchain steps (sips/iconutil/codesign/hdiutil)
are exercised by the end-to-end build, not here.
"""

from __future__ import annotations

import dataclasses
import plistlib

from pyappdist.config import LauncherConfig, MacosConfig
from pyappdist.macos.bundle import info_plist
from pyappdist.macos.sign import _MACHO_MAGIC, _iter_machos
from pyappdist.targets import get_target


def _macos(sample_config, **macos_kwargs):
    return dataclasses.replace(
        sample_config,
        target=get_target("macos-arm64"),
        target_name="macos-arm64",
        format="dmg",
        macos=MacosConfig(**macos_kwargs),
    )


def test_info_plist_keys(sample_config):
    cfg = _macos(sample_config)
    data = plistlib.loads(
        info_plist(cfg, executable="helloworld", identifier="com.example.helloworld",
                   display_name="Hello World")
    )
    assert data["CFBundleExecutable"] == "helloworld"
    assert data["CFBundleIdentifier"] == "com.example.helloworld"
    assert data["CFBundleName"] == "Hello World"
    assert data["CFBundlePackageType"] == "APPL"
    assert data["CFBundleShortVersionString"] == "1.2.3"
    assert data["CFBundleVersion"] == "1.2.3"
    assert data["CFBundleIconFile"] == "AppIcon"  # extension omitted by convention
    assert data["LSMinimumSystemVersion"] == "11.0"
    assert data["NSHighResolutionCapable"] is True
    assert "LSApplicationCategoryType" not in data  # absent unless category set


def test_info_plist_category_optional(sample_config):
    cfg = _macos(sample_config, category="public.app-category.utilities")
    data = plistlib.loads(
        info_plist(cfg, executable="x", identifier="com.example.x", display_name="X")
    )
    assert data["LSApplicationCategoryType"] == "public.app-category.utilities"


def test_info_plist_min_macos_override(sample_config):
    cfg = _macos(sample_config, min_macos="12.3")
    data = plistlib.loads(
        info_plist(cfg, executable="x", identifier="com.example.x", display_name="X")
    )
    assert data["LSMinimumSystemVersion"] == "12.3"


def test_macho_detection(tmp_path):
    macho = tmp_path / "bin"
    macho.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 100)  # MH_MAGIC_64
    text = tmp_path / "script.py"
    text.write_bytes(b"print('hi')\n")
    found = set(_iter_machos(tmp_path))
    assert macho in found
    assert text not in found


def test_macho_magic_set_nonempty():
    assert b"\xcf\xfa\xed\xfe" in _MACHO_MAGIC
    assert b"\xca\xfe\xba\xbe" in _MACHO_MAGIC


def test_iter_machos_skips_symlinks(tmp_path):
    target = tmp_path / "real"
    target.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 10)
    link = tmp_path / "link"
    link.symlink_to(target)
    found = set(_iter_machos(tmp_path))
    assert target in found
    assert link not in found  # symlinks are skipped (sign the real file)


def test_fixed_args_initializer():
    from pyappdist.launcher.build import _fixed_args_initializer

    assert _fixed_args_initializer("") == "{ NULL }"
    assert _fixed_args_initializer("--foo bar") == '{ "--foo", "bar", NULL }'
    # shell-quoted arg with a space stays one element
    assert _fixed_args_initializer('"a b" c') == '{ "a b", "c", NULL }'
