"""WiX XML 生成のゴールデン比較・バリデーションテスト。"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyappdist.config import InstallerConfig
from pyappdist.errors import ConfigError
from pyappdist.wix.generate import generate_wxs

GOLDEN = Path(__file__).parent / "golden" / "sample.wxs"


def test_golden(sample_config, sample_tree):
    expected = GOLDEN.read_text(encoding="utf-8")
    actual = generate_wxs(sample_config, sample_tree)
    assert actual == expected, "WiX 出力がゴールデンと不一致（意図的なら golden を更新する）"


def test_requires_manufacturer(sample_config, sample_tree):
    cfg = dataclasses.replace(
        sample_config, installer=InstallerConfig(manufacturer=None, upgrade_code="x")
    )
    with pytest.raises(ConfigError, match="manufacturer"):
        generate_wxs(cfg, sample_tree)


def test_requires_valid_upgrade_code(sample_config, sample_tree):
    cfg = dataclasses.replace(
        sample_config,
        installer=InstallerConfig(manufacturer="X", upgrade_code="PUT-GUID-HERE"),
    )
    with pytest.raises(ConfigError, match="upgrade_code"):
        generate_wxs(cfg, sample_tree)
