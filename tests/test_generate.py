"""Golden-comparison and validation tests for WiX XML generation."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyappdist.config import WixConfig
from pyappdist.errors import ConfigError
from pyappdist.wix.generate import generate_wxs

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
