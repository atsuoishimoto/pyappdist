"""Tests for the ``wix build`` invocation (subprocess and path resolution stubbed)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import pyappdist.wix.build as wb
from pyappdist.errors import BuildError
from pyappdist.wix.generate import ICON_STAGED_NAME, LICENSE_STAGED_NAME


def _fake_wix(monkeypatch, out_msi: Path) -> dict:
    """Stub out wix.exe discovery, the Windows path lookup, and the build itself."""
    calls: dict = {}
    monkeypatch.setenv("PYAPPDIST_WIN_WIX", "wix.exe")
    monkeypatch.setattr(wb, "windows_abspath", lambda path, python_exe: r"C:\image")

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["cwd"] = kwargs.get("cwd")
        out_msi.parent.mkdir(parents=True, exist_ok=True)
        out_msi.write_bytes(b"")

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    monkeypatch.setattr(wb.subprocess, "run", fake_run)
    return calls


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The real layout: build intermediates and artifacts in sibling trees.

    ``tmp_path`` is their common ancestor (the project dir), so a staged file
    landing there rather than in the build dir is visible to the assertions.
    """
    build = tmp_path / ".appdist-build" / "win32-msi"
    image = build / "image"
    image.mkdir(parents=True)
    wxs = build / "helloworld.wxs"
    wxs.write_text("<Wix/>", encoding="utf-8")
    return image, wxs, tmp_path / "appdist" / "win32-msi" / "dist" / "helloworld-1.2.3.msi"


def _with_icon(config, icon_rel: str):
    launcher = dataclasses.replace(config.launchers[0], icons=(("windows", icon_rel),))
    return dataclasses.replace(config, launchers=(launcher,))


def test_product_icon_is_staged_next_to_the_wxs(sample_config, tmp_path, monkeypatch):
    # Icon/@SourceFile is a bare name, so the source .ico is copied next to the .wxs
    # and found through the bind path build.py adds for that directory. It must not
    # land in cwd (the project dir), which stays free of build artifacts.
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.ico").write_bytes(b"icondata")
    image, wxs, out = _layout(tmp_path)
    cfg = _with_icon(dataclasses.replace(sample_config, project_dir=project), "app.ico")

    calls = _fake_wix(monkeypatch, out)
    assert wb.build_msi(cfg, image, wxs, out) == out
    assert calls["cwd"] == str(tmp_path)
    assert (wxs.parent / ICON_STAGED_NAME).read_bytes() == b"icondata"
    assert not (tmp_path / ICON_STAGED_NAME).exists()
    # ...and wix is told where to look for it, relative to cwd like the other args.
    assert calls["cmd"].count("-b") == 2
    staged_rel = ".appdist-build\\win32-msi"
    assert ["-b", staged_rel] == calls["cmd"][calls["cmd"].index(staged_rel) - 1:][:2]


def test_no_icon_stages_nothing(sample_config, tmp_path, monkeypatch):
    image, wxs, out = _layout(tmp_path)
    calls = _fake_wix(monkeypatch, out)
    assert wb.build_msi(sample_config, image, wxs, out) == out
    for staged in (tmp_path, wxs.parent):
        assert not (staged / ICON_STAGED_NAME).exists()
        assert not (staged / LICENSE_STAGED_NAME).exists()
    # Nothing staged, so only the image bind path is passed.
    assert calls["cmd"].count("-b") == 1


def test_missing_product_icon_errors(sample_config, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    image, wxs, out = _layout(tmp_path)
    cfg = _with_icon(dataclasses.replace(sample_config, project_dir=project), "gone.ico")

    _fake_wix(monkeypatch, out)
    with pytest.raises(BuildError, match="product icon not found"):
        wb.build_msi(cfg, image, wxs, out)


def test_non_windows_target_is_skipped(sample_config, tmp_path):
    from pyappdist.targets import get_target

    image, wxs, out = _layout(tmp_path)
    cfg = dataclasses.replace(sample_config, target=get_target("linux-x86_64"))
    assert wb.build_msi(cfg, image, wxs, out, log=lambda _m: None) is None
