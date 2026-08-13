"""Tests for MSIX manifest generation and helpers."""

from __future__ import annotations

import dataclasses
import xml.etree.ElementTree as ET

from pyappdist.config import MsixConfig, WixConfig
from pyappdist.msix.manifest import (
    DESKTOP,
    FOUNDATION,
    UAP,
    _app_id,
    _rdn_escape,
    _version4,
    generate_manifest,
)


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


def test_manifest_launcher_title_overrides_entry_name(sample_config):
    launchers = (
        dataclasses.replace(sample_config.launchers[0], title="My Application"),
        dataclasses.replace(sample_config.launchers[0], name="hellocli"),
    )
    cfg = dataclasses.replace(_msix(sample_config), launchers=launchers)
    root = ET.fromstring(generate_manifest(cfg))
    names = {
        app.get("Executable"): app.find(f"{{{UAP}}}VisualElements").get("DisplayName")
        for app in root.iter(f"{{{FOUNDATION}}}Application")
    }
    # A titled launcher shows its title; an untitled one keeps the multi-launcher
    # default of "<display name> - <launcher name>".
    assert names["helloworld.exe"] == "My Application"
    assert names["hellocli.exe"] == "Hello World - hellocli"


def test_manifest_no_app_execution_alias_by_default(sample_config):
    xml = generate_manifest(_msix(sample_config))
    assert "windows.appExecutionAlias" not in xml


def test_manifest_app_execution_alias(sample_config):
    xml = generate_manifest(_msix(sample_config, app_execution_alias=True))
    assert 'Category="windows.appExecutionAlias"' in xml
    assert 'Executable="helloworld.exe"' in xml
    assert '<desktop:ExecutionAlias Alias="helloworld.exe" />' in xml
    assert 'xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"' in xml
    assert 'xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"' in xml


def test_manifest_no_app_list_entry_by_default(sample_config):
    assert "AppListEntry" not in generate_manifest(_msix(sample_config))


def test_manifest_hidden_launcher_not_in_app_list(sample_config):
    launchers = (
        sample_config.launchers[0],
        dataclasses.replace(sample_config.launchers[0], name="hellocli", app_entry=False),
    )
    cfg = dataclasses.replace(
        _msix(sample_config, app_execution_alias=True), launchers=launchers
    )
    root = ET.fromstring(generate_manifest(cfg))
    apps = {
        app.get("Executable"): app for app in root.iter(f"{{{FOUNDATION}}}Application")
    }
    # The visible launcher keeps a normal app-list entry...
    visible = apps["helloworld.exe"].find(f"{{{UAP}}}VisualElements")
    assert visible.get("AppListEntry") is None
    # ...the hidden one stays an <Application> (its execution alias needs one)
    # but is dropped from the Start Menu app list.
    hidden = apps["hellocli.exe"]
    assert hidden.find(f"{{{UAP}}}VisualElements").get("AppListEntry") == "none"
    alias = hidden.find(f".//{{{DESKTOP}}}ExecutionAlias")
    assert alias.get("Alias") == "hellocli.exe"


def test_manifest_default_publisher_escapes_rdn(sample_config):
    # "Acme, Inc." must become one escaped RDN value, not parse as two RDNs.
    cfg = dataclasses.replace(
        sample_config,
        wix=WixConfig(manufacturer="Acme, Inc.", upgrade_code=sample_config.wix.upgrade_code),
    )
    xml = generate_manifest(_msix(cfg))
    assert 'Publisher="CN=Acme\\, Inc."' in xml


def test_manifest_explicit_publisher_taken_verbatim(sample_config):
    # A user-supplied publisher is a complete DN (already escaped to match the
    # signing cert subject) and must not be escaped again.
    xml = generate_manifest(
        _msix(sample_config, publisher="CN=Acme\\, Inc., O=Acme")
    )
    assert 'Publisher="CN=Acme\\, Inc., O=Acme"' in xml


def test_rdn_escape():
    assert _rdn_escape("Example Inc.") == "Example Inc."
    assert _rdn_escape("Acme, Inc.") == "Acme\\, Inc."
    assert _rdn_escape('A+B"C<D>E;F=G\\H') == 'A\\+B\\"C\\<D\\>E\\;F\\=G\\\\H'
    assert _rdn_escape("#leading") == "\\#leading"
    assert _rdn_escape(" spaces ") == "\\ spaces\\ "


def test_version4():
    assert _version4("1.2.3") == "1.2.3.0"
    assert _version4("1.2") == "1.2.0.0"
    assert _version4("1.2.3.4") == "1.2.3.4"


def test_app_id_sanitizes():
    assert _app_id("my-app") == "myapp"
    assert _app_id("1app") == "App1app"


def test_build_msix_invokes_makeappx_with_relative_paths(
    sample_config, tmp_path, monkeypatch
):
    """build_msix runs makeappx with cwd at the common ancestor and relative paths."""
    import pyappdist.msix.build as mb

    image = tmp_path / "image"
    image.mkdir()
    out = tmp_path / "dist" / "helloworld-1.2.3.msix"
    monkeypatch.setenv("PYAPPDIST_WIN_MAKEAPPX", "makeappx.exe")

    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["cwd"] = kwargs.get("cwd")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"")

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    monkeypatch.setattr(mb.subprocess, "run", fake_run)

    assert mb.build_msix(_msix(sample_config), image, out) == out
    assert calls["cmd"][:2] == ["makeappx.exe", "pack"]
    assert calls["cwd"] == str(tmp_path)
    # /d and /p are relative to cwd, with Windows separators (no absolute paths).
    d = calls["cmd"][calls["cmd"].index("/d") + 1]
    p = calls["cmd"][calls["cmd"].index("/p") + 1]
    assert d == "image"
    assert p == "dist\\helloworld-1.2.3.msix"
    # The manifest and logos were staged into the image.
    assert (image / "AppxManifest.xml").is_file()
    assert (image / "Assets" / "StoreLogo.png").is_file()
