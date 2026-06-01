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


# --- signing options + notarization config ---------------------------------

import pytest  # noqa: E402

from pyappdist.errors import BuildError  # noqa: E402
from pyappdist.macos.notarize import resolve_notary_profile  # noqa: E402
from pyappdist.macos.sign import (  # noqa: E402
    entitlements_plist,
    resolve_sign_options,
)


def test_entitlements_plist_keys():
    ent = plistlib.loads(entitlements_plist())
    assert ent["com.apple.security.cs.disable-library-validation"] is True
    assert ent["com.apple.security.cs.allow-jit"] is True
    assert ent["com.apple.security.cs.allow-unsigned-executable-memory"] is True


def test_resolve_sign_options_adhoc_by_default(sample_config, tmp_path, monkeypatch):
    monkeypatch.delenv("PYAPPDIST_SIGNING_IDENTITY", raising=False)
    opts = resolve_sign_options(_macos(sample_config), tmp_path, log=lambda _m: None)
    assert opts.adhoc is True
    assert opts.identity == "-"
    assert opts.hardened is False
    assert opts.entitlements is None


def test_resolve_sign_options_developer_id_from_config(sample_config, tmp_path):
    cfg = _macos(sample_config, signing_identity="Developer ID Application: Acme (TEAM123)")
    opts = resolve_sign_options(cfg, tmp_path, log=lambda _m: None)
    assert opts.adhoc is False
    assert opts.hardened is True
    assert opts.timestamp is True
    # a default entitlements plist is written into the build dir
    assert opts.entitlements == tmp_path / "entitlements.plist"
    assert opts.entitlements.is_file()
    assert b"disable-library-validation" in opts.entitlements.read_bytes()


def test_resolve_sign_options_identity_from_env(sample_config, tmp_path, monkeypatch):
    monkeypatch.setenv("PYAPPDIST_SIGNING_IDENTITY", "Developer ID Application: Env (TEAMENV)")
    opts = resolve_sign_options(_macos(sample_config), tmp_path, log=lambda _m: None)
    assert opts.identity == "Developer ID Application: Env (TEAMENV)"
    assert opts.adhoc is False


def test_resolve_sign_options_entitlements_override(sample_config, tmp_path):
    ent = tmp_path / "custom.entitlements"
    ent.write_text("<plist></plist>")
    cfg = dataclasses.replace(
        _macos(sample_config, signing_identity="Developer ID Application: A (T)",
               entitlements="custom.entitlements"),
        project_dir=tmp_path,
    )
    opts = resolve_sign_options(cfg, tmp_path / "_build", log=lambda _m: None)
    assert opts.entitlements == ent


def test_resolve_sign_options_entitlements_missing(sample_config, tmp_path):
    cfg = dataclasses.replace(
        _macos(sample_config, signing_identity="Developer ID Application: A (T)",
               entitlements="nope.entitlements"),
        project_dir=tmp_path,
    )
    with pytest.raises(BuildError, match="entitlements file not found"):
        resolve_sign_options(cfg, tmp_path / "_build", log=lambda _m: None)


def test_resolve_notary_profile_config_and_env(sample_config, monkeypatch):
    monkeypatch.delenv("PYAPPDIST_NOTARY_PROFILE", raising=False)
    assert resolve_notary_profile(_macos(sample_config)) is None
    assert resolve_notary_profile(_macos(sample_config, notary_profile="myprof")) == "myprof"
    monkeypatch.setenv("PYAPPDIST_NOTARY_PROFILE", "envprof")
    assert resolve_notary_profile(_macos(sample_config)) == "envprof"
    # config takes precedence over env
    assert resolve_notary_profile(_macos(sample_config, notary_profile="cfgprof")) == "cfgprof"
