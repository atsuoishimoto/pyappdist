"""Tests for runtime asset selection (no network: ``_http_get`` is monkeypatched)."""

from __future__ import annotations

import pytest

from pyappdist import runtime
from pyappdist.errors import BuildError

_TRIPLE = "x86_64-pc-windows-msvc"

_SUMS = (
    "\n".join(
        f"{sha * 64} *cpython-{ver}+20250106-{_TRIPLE}-install_only_stripped.tar.gz"
        for sha, ver in (("a", "3.12.9"), ("b", "3.12.11"), ("c", "3.13.2"))
    )
    + "\n"
)


@pytest.fixture
def fake_sums(monkeypatch):
    monkeypatch.setattr(runtime, "_http_get", lambda url: _SUMS.encode())


def test_select_latest_patch_for_minor(fake_sums):
    name, sha, ver = runtime._select_asset(
        "http://x", _TRIPLE, "3.12", None, lambda m: None
    )
    assert ver == "3.12.11"
    assert sha == "b" * 64
    assert "3.12.11" in name


def test_select_exact_pin(fake_sums):
    # An X.Y.Z config must select that exact patch, not the latest one.
    name, sha, ver = runtime._select_asset(
        "http://x", _TRIPLE, "3.12", "3.12.9", lambda m: None
    )
    assert ver == "3.12.9"
    assert sha == "a" * 64


def test_select_exact_pin_missing(fake_sums):
    with pytest.raises(BuildError, match="3.12.10"):
        runtime._select_asset("http://x", _TRIPLE, "3.12", "3.12.10", lambda m: None)


def test_select_no_match_for_minor(fake_sums):
    with pytest.raises(BuildError, match="3.11"):
        runtime._select_asset("http://x", _TRIPLE, "3.11", None, lambda m: None)


# --- ensure_pip / _pip_version -------------------------------------------


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _info(tmp_path):
    return runtime.RuntimeInfo(
        version="3.12.11", minor="3.12", tag="20250106", triple=_TRIPLE, root=tmp_path
    )


def _fake_run(monkeypatch, handler):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return handler(cmd)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    return calls


def test_pip_version_parsed(monkeypatch, tmp_path):
    _fake_run(monkeypatch, lambda cmd: _FakeProc(stdout="pip 24.0 from /x/pip (python 3.12)"))
    assert runtime._pip_version(_info(tmp_path)) == (24, 0)


def test_pip_version_unparseable(monkeypatch, tmp_path):
    _fake_run(monkeypatch, lambda cmd: _FakeProc(stdout="garbage"))
    with pytest.raises(BuildError, match="parse"):
        runtime._pip_version(_info(tmp_path))


def test_pip_version_query_failure(monkeypatch, tmp_path):
    _fake_run(monkeypatch, lambda cmd: _FakeProc(returncode=1, stderr="boom"))
    with pytest.raises(BuildError, match="pip version"):
        runtime._pip_version(_info(tmp_path))


def test_ensure_pip_upgrades_when_old(monkeypatch, tmp_path):
    def handler(cmd):
        if cmd[-1] == "--version":
            return _FakeProc(stdout="pip 24.0 from /x (python 3.12)")
        return _FakeProc()  # the upgrade

    calls = _fake_run(monkeypatch, handler)
    runtime.ensure_pip(_info(tmp_path), log=lambda m: None)
    assert any("install" in c and "--upgrade" in c for c in calls)


def test_ensure_pip_skips_when_recent(monkeypatch, tmp_path):
    calls = _fake_run(
        monkeypatch, lambda cmd: _FakeProc(stdout="pip 26.2 from /x (python 3.12)")
    )
    runtime.ensure_pip(_info(tmp_path), log=lambda m: None)
    # Only the version check ran; no upgrade (and so no network round-trip).
    assert len(calls) == 1 and calls[0][-1] == "--version"


def test_ensure_pip_skips_at_threshold(monkeypatch, tmp_path):
    calls = _fake_run(
        monkeypatch, lambda cmd: _FakeProc(stdout="pip 26.1 from /x (python 3.12)")
    )
    runtime.ensure_pip(_info(tmp_path), log=lambda m: None)
    assert len(calls) == 1


def test_ensure_pip_upgrade_failure_raises(monkeypatch, tmp_path):
    def handler(cmd):
        if cmd[-1] == "--version":
            return _FakeProc(stdout="pip 24.0 from /x (python 3.12)")
        return _FakeProc(returncode=1, stderr="network down")

    _fake_run(monkeypatch, handler)
    with pytest.raises(BuildError, match="pip upgrade failed"):
        runtime.ensure_pip(_info(tmp_path), log=lambda m: None)
