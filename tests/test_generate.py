"""Golden-comparison and validation tests for WiX XML generation."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyappdist.config import WixConfig
from pyappdist.errors import ConfigError
from pyappdist.wix.generate import generate_wxs

GOLDEN = Path(__file__).parent / "golden" / "sample.wxs"
GOLDEN_PERUSER = Path(__file__).parent / "golden" / "sample_peruser.wxs"


def test_golden(sample_config, sample_tree):
    expected = GOLDEN.read_text(encoding="utf-8")
    actual = generate_wxs(sample_config, sample_tree)
    assert actual == expected, "WiX output differs from the golden (update the golden if intentional)"


def test_golden_peruser(sample_config, sample_tree):
    cfg = dataclasses.replace(
        sample_config,
        wix=dataclasses.replace(
            sample_config.wix, scope="perUserOrMachine", license="EULA.rtf"
        ),
    )
    expected = GOLDEN_PERUSER.read_text(encoding="utf-8")
    actual = generate_wxs(cfg, sample_tree)
    assert actual == expected, "WiX output differs from the per-user golden (update the golden if intentional)"


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
    with pytest.raises(ConfigError, match="upgrade_code"):
        generate_wxs(cfg, sample_tree)
