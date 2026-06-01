"""Tests for MSIX manifest generation and helpers."""

from __future__ import annotations

import dataclasses

from pyappdist.config import MsixConfig
from pyappdist.msix.build import _solid_png
from pyappdist.msix.manifest import _app_id, _version4, generate_manifest


def _msix(sample_config, **msix_kwargs):
    return dataclasses.replace(
        sample_config, format="msix", msix=MsixConfig(**msix_kwargs)
    )


def test_manifest_basic(sample_config):
    xml = generate_manifest(_msix(sample_config))
    assert 'EntryPoint="Windows.FullTrustApplication"' in xml
    assert 'Name="runFullTrust"' in xml
    assert 'Version="1.2.3.0"' in xml          # 4-part version
    assert 'Executable="helloworld.exe"' in xml
    assert xml.count("<Application ") == 1      # one launcher -> one Application


def test_manifest_defaults(sample_config):
    xml = generate_manifest(_msix(sample_config))
    assert 'Name="helloworld"' in xml           # Identity defaults to dist_name
    assert 'Publisher="CN=Example Inc."' in xml  # defaults to CN=<manufacturer>
    assert "<DisplayName>Hello World</DisplayName>" in xml


def test_manifest_overrides(sample_config):
    xml = generate_manifest(
        _msix(sample_config, identity_name="Contoso.App", publisher="CN=Contoso",
              display_name="My App")
    )
    assert 'Name="Contoso.App"' in xml
    assert 'Publisher="CN=Contoso"' in xml
    assert "<DisplayName>My App</DisplayName>" in xml


def test_version4():
    assert _version4("1.2.3") == "1.2.3.0"
    assert _version4("1.2") == "1.2.0.0"
    assert _version4("1.2.3.4") == "1.2.3.4"


def test_app_id_sanitizes():
    assert _app_id("my-app") == "myapp"
    assert _app_id("1app") == "App1app"


def test_solid_png_is_valid_png():
    data = _solid_png(16, 16, (0, 120, 212))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in data[:32] and data.rstrip().endswith(b"\xaeB`\x82")  # IEND CRC
