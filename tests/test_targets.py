"""Tests for the target table and target-arch-driven vcvars selection."""

import pytest

from pyappdist.errors import ConfigError
from pyappdist.launcher.build import _vcvars_candidates
from pyappdist.targets import get_target


def test_windows_arm64_target():
    t = get_target("windows-arm64")
    assert t.triple == "aarch64-pc-windows-msvc"
    assert t.os == "windows"
    assert t.wix_arch == "arm64"


def test_linux_aarch64_target():
    t = get_target("linux-aarch64")
    assert t.triple == "aarch64-unknown-linux-gnu"
    assert t.os == "linux"
    assert t.wix_arch == "arm64"


def test_unknown_target_lists_supported():
    with pytest.raises(ConfigError, match="windows-arm64"):
        get_target("solaris-sparc")


def test_vcvars_candidates_x64_target(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert _vcvars_candidates(get_target("windows-x86_64")) == ["vcvars64.bat"]


def test_vcvars_candidates_arm64_target_on_x64_host(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert _vcvars_candidates(get_target("windows-arm64")) == [
        "vcvarsamd64_arm64.bat"
    ]


@pytest.mark.parametrize("machine", ["aarch64", "ARM64"])
def test_vcvars_candidates_arm64_target_on_arm64_host(monkeypatch, machine):
    # WSL reports the kernel's machine ("aarch64"); native Windows says "ARM64".
    monkeypatch.setattr("platform.machine", lambda: machine)
    assert _vcvars_candidates(get_target("windows-arm64")) == [
        "vcvarsarm64.bat", "vcvarsamd64_arm64.bat"
    ]
