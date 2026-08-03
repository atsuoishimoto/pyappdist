"""Tests for build-prebuilt target selection (host-independent logic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.errors import BuildError, ConfigError
from pyappdist.launcher import build as launcher_build
from pyappdist.launcher import prebuilt
from pyappdist.targets import Target


def test_unknown_selector_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="unknown build-prebuilt target"):
        prebuilt.build_prebuilt(tmp_path, select=["bogus"])


def _no_windows_toolchain(monkeypatch, tmp_path: Path) -> None:
    # _windows_capable consults vswhere's location (the test host is Linux, so
    # sys.platform never short-circuits it).
    monkeypatch.setattr(
        launcher_build, "_vswhere_path", lambda: tmp_path / "missing" / "vswhere.exe"
    )


def test_explicit_macos_requires_darwin(tmp_path: Path):
    # The test suite runs on Linux, where an explicit macos selection must fail.
    with pytest.raises(BuildError, match="macOS host"):
        prebuilt.build_prebuilt(tmp_path, select=["macos"])


def test_explicit_windows_requires_toolchain(tmp_path: Path, monkeypatch):
    _no_windows_toolchain(monkeypatch, tmp_path)
    with pytest.raises(BuildError, match="Windows, or on WSL with Visual Studio"):
        prebuilt.build_prebuilt(tmp_path, select=["windows-x86_64"])


def test_auto_without_toolchain_skips_with_note(tmp_path: Path, monkeypatch):
    _no_windows_toolchain(monkeypatch, tmp_path)
    logs: list[str] = []
    assert prebuilt.build_prebuilt(tmp_path, log=logs.append) == []
    assert any(m.startswith("skip: no launcher toolchain") for m in logs)


def _fake_windows_host(monkeypatch, tmp_path: Path, *, arm64: bool) -> list[str]:
    """A pretend Windows host: x64 vcvars always found, arm64 optionally not.
    Returns the list that records _build_windows calls."""
    vswhere = tmp_path / "vswhere.exe"
    vswhere.write_bytes(b"MZ")
    monkeypatch.setattr(launcher_build, "_vswhere_path", lambda: vswhere)

    def fake_vcvars(target: Target) -> str:
        if target.wix_arch == "arm64" and not arm64:
            raise BuildError("no arm64 tools")
        return r"C:\VS\vcvars64.bat"

    monkeypatch.setattr(launcher_build, "_find_vcvars", fake_vcvars)

    built: list[str] = []

    def fake_build(target: Target, gui: bool, vcvars: str, workdir, out, log):
        name = prebuilt.windows_stub(target, gui).name
        built.append(name)
        return out / name

    monkeypatch.setattr(prebuilt, "_build_windows", fake_build)
    return built


def test_auto_skips_missing_arm64_toolchain(tmp_path: Path, monkeypatch):
    built = _fake_windows_host(monkeypatch, tmp_path, arm64=False)
    logs: list[str] = []
    out = prebuilt.build_prebuilt(tmp_path, log=logs.append)
    assert built == [
        "launcher-windows-x86_64-console.exe",
        "launcher-windows-x86_64-gui.exe",
    ]
    assert len(out) == 2
    assert any(m.startswith("skip: windows-arm64") for m in logs)


def test_explicit_selection_builds_pairs_and_dedups(tmp_path: Path, monkeypatch):
    built = _fake_windows_host(monkeypatch, tmp_path, arm64=True)
    out = prebuilt.build_prebuilt(
        tmp_path, select=["windows-arm64", "windows-arm64"], log=lambda m: None
    )
    assert built == [
        "launcher-windows-arm64-console.exe",
        "launcher-windows-arm64-gui.exe",
    ]
    assert len(out) == 2


def test_explicit_selection_missing_toolchain_is_an_error(tmp_path: Path, monkeypatch):
    _fake_windows_host(monkeypatch, tmp_path, arm64=False)
    with pytest.raises(BuildError, match="no arm64 tools"):
        prebuilt.build_prebuilt(
            tmp_path, select=["windows-arm64"], log=lambda m: None
        )
