"""Golden-comparison and validation tests for WiX XML generation."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyappdist.config import WixConfig
from pyappdist.errors import ConfigError
from pyappdist.wix.generate import (
    ICON_STAGED_NAME,
    _PRODUCT_ICON_ID,
    generate_wxs,
    product_icon,
)

GOLDEN = Path(__file__).parent / "golden" / "sample.wxs"
GOLDEN_MACHINE = Path(__file__).parent / "golden" / "sample_machine.wxs"


def test_golden(sample_config, sample_tree):
    # sample_config uses the default scope ("user").
    expected = GOLDEN.read_text(encoding="utf-8")
    actual = generate_wxs(sample_config, sample_tree)
    assert actual == expected, "WiX output differs from the golden (update the golden if intentional)"


def test_golden_machine(sample_config, sample_tree):
    cfg = dataclasses.replace(
        sample_config, wix=dataclasses.replace(sample_config.wix, scope="machine")
    )
    expected = GOLDEN_MACHINE.read_text(encoding="utf-8")
    actual = generate_wxs(cfg, sample_tree)
    assert actual == expected, "WiX output differs from the machine golden (update the golden if intentional)"


def test_license_adds_minimal_ui(sample_config, sample_tree):
    cfg = dataclasses.replace(
        sample_config, wix=dataclasses.replace(sample_config.wix, license="EULA.rtf")
    )
    xml = generate_wxs(cfg, sample_tree)
    assert 'Id="WixUI_Minimal"' in xml
    assert 'Id="WixUILicenseRtf"' in xml


def _with_icons(config, *icons):
    """Replace the launchers with one per entry in ``icons`` (a per-OS icon table)."""
    launchers = tuple(
        dataclasses.replace(config.launchers[0], name=f"app{i}", icons=table)
        for i, table in enumerate(icons)
    )
    return dataclasses.replace(config, launchers=launchers)


def test_no_product_icon_without_a_windows_icon(sample_config, sample_tree):
    # The default sample has no icons: no Icon element, no ARPPRODUCTICON.
    xml = generate_wxs(sample_config, sample_tree)
    assert "ARPPRODUCTICON" not in xml
    assert "<Icon " not in xml
    assert product_icon(sample_config) is None


def test_product_icon_emitted(sample_config, sample_tree):
    cfg = _with_icons(sample_config, (("windows", "art/app.ico"),))
    assert product_icon(cfg) == "art/app.ico"
    xml = generate_wxs(cfg, sample_tree)
    assert f'<Icon Id="{_PRODUCT_ICON_ID}" SourceFile="{ICON_STAGED_NAME}" />' in xml
    assert f'<Property Id="ARPPRODUCTICON" Value="{_PRODUCT_ICON_ID}" />' in xml


def test_product_icon_ignores_other_oses(sample_config, sample_tree):
    # A launcher with only a macOS/Linux icon contributes no Windows product icon.
    cfg = _with_icons(sample_config, (("macos", "app.png"), ("linux", "app.png")))
    assert product_icon(cfg) is None
    assert "ARPPRODUCTICON" not in generate_wxs(cfg, sample_tree)


def test_product_icon_uses_the_first_launcher_with_one(sample_config, sample_tree):
    # ARP shows one icon per product; the first launcher declaring one wins.
    cfg = _with_icons(
        sample_config,
        (("linux", "first.png"),),
        (("windows", "second.ico"),),
        (("windows", "third.ico"),),
    )
    assert product_icon(cfg) == "second.ico"


def test_allow_same_version_upgrades(sample_config, sample_tree):
    # Off by default: the MajorUpgrade element carries no AllowSameVersionUpgrades.
    assert "AllowSameVersionUpgrades" not in generate_wxs(sample_config, sample_tree)
    cfg = dataclasses.replace(
        sample_config,
        wix=dataclasses.replace(sample_config.wix, allow_same_version_upgrades=True),
    )
    assert 'AllowSameVersionUpgrades="yes"' in generate_wxs(cfg, sample_tree)


def test_requires_manufacturer(sample_config, sample_tree):
    cfg = dataclasses.replace(
        sample_config, wix=WixConfig(manufacturer=None, upgrade_code="x")
    )
    with pytest.raises(ConfigError, match="manufacturer"):
        generate_wxs(cfg, sample_tree)


def test_requires_valid_upgrade_code(sample_config, sample_tree):
    cfg = dataclasses.replace(
        sample_config,
        wix=WixConfig(manufacturer="X", upgrade_code="PUT-GUID-HERE"),
    )
    with pytest.raises(ConfigError, match="upgrade-code"):
        generate_wxs(cfg, sample_tree)
