"""Tests for runtime asset selection (no network: ``_http_get`` is monkeypatched)."""

from __future__ import annotations

import hashlib
import http.client
import io
import urllib.error

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
    versions = iter(["pip 24.0 from /x (python 3.12)", "pip 26.1 from /x (python 3.12)"])

    def handler(cmd):
        if cmd[-1] == "--version":
            return _FakeProc(stdout=next(versions))
        return _FakeProc()  # the upgrade

    calls = _fake_run(monkeypatch, handler)
    runtime.ensure_pip(_info(tmp_path), log=lambda m: None)
    assert any("install" in c and "--upgrade" in c for c in calls)


def test_ensure_pip_upgrade_still_too_old(monkeypatch, tmp_path):
    # An old runtime whose newest installable pip stays below _MIN_PIP must fail
    # here with the real cause, not later inside "pip wheel -r pylock.toml".
    def handler(cmd):
        if cmd[-1] == "--version":
            return _FakeProc(stdout="pip 24.0 from /x (python 3.9)")
        return _FakeProc()  # the upgrade "succeeds" but pip stays at 24.0

    _fake_run(monkeypatch, handler)
    with pytest.raises(BuildError, match="could only be upgraded"):
        runtime.ensure_pip(_info(tmp_path), log=lambda m: None)


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


# --- download / HTTP error handling ---------------------------------------


def _fake_urlopen(monkeypatch, factory):
    """Replace urlopen with ``factory(url)``, recording the timeout it was given."""
    seen = {}

    def urlopen(url, timeout=None):
        seen["timeout"] = timeout
        return factory(url)

    monkeypatch.setattr(runtime.urllib.request, "urlopen", urlopen)
    return seen


def test_http_get_wraps_network_errors(monkeypatch):
    def factory(url):
        raise urllib.error.URLError("name resolution failed")

    _fake_urlopen(monkeypatch, factory)
    with pytest.raises(BuildError, match="download failed"):
        runtime._http_get("http://x/latest-release.json")


def test_http_get_passes_timeout(monkeypatch):
    seen = _fake_urlopen(monkeypatch, lambda url: io.BytesIO(b"{}"))
    assert runtime._http_get("http://x") == b"{}"
    assert seen["timeout"] == runtime._HTTP_TIMEOUT


def test_download_verified_ok(monkeypatch, tmp_path):
    data = b"runtime archive bytes"
    _fake_urlopen(monkeypatch, lambda url: io.BytesIO(data))
    dest = tmp_path / "cpython.tar.gz"
    runtime._download_verified(
        "http://x/a.tar.gz", dest, hashlib.sha256(data).hexdigest(), lambda m: None
    )
    assert dest.read_bytes() == data
    # No temp files linger next to the cached archive.
    assert list(tmp_path.iterdir()) == [dest]


def test_download_verified_sha_mismatch(monkeypatch, tmp_path):
    _fake_urlopen(monkeypatch, lambda url: io.BytesIO(b"corrupted"))
    dest = tmp_path / "cpython.tar.gz"
    with pytest.raises(BuildError, match="sha256 mismatch"):
        runtime._download_verified("http://x/a.tar.gz", dest, "0" * 64, lambda m: None)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_verified_dropped_connection(monkeypatch, tmp_path):
    class _Broken(io.BytesIO):
        def read(self, *args):
            raise http.client.IncompleteRead(b"")

    _fake_urlopen(monkeypatch, lambda url: _Broken())
    dest = tmp_path / "cpython.tar.gz"
    with pytest.raises(BuildError, match="download failed"):
        runtime._download_verified("http://x/a.tar.gz", dest, "0" * 64, lambda m: None)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_verified_cache_hit(monkeypatch, tmp_path):
    data = b"cached"
    dest = tmp_path / "cpython.tar.gz"
    dest.write_bytes(data)

    def factory(url):  # pragma: no cover - must not be reached
        raise AssertionError("network hit despite cache")

    _fake_urlopen(monkeypatch, factory)
    runtime._download_verified(
        "http://x/a.tar.gz", dest, hashlib.sha256(data).hexdigest(), lambda m: None
    )


# --- fetch_runtime reuse / self-heal ---------------------------------------


def _write_valid_tree(dest):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "python.exe").write_bytes(b"")
    (dest / "python312.dll").write_bytes(b"")
    (dest / "Lib").mkdir(exist_ok=True)


def _windows_target():
    from pyappdist.targets import get_target

    return get_target("windows-x86_64")


def test_fetch_runtime_reuses_verified_tree(monkeypatch, tmp_path):
    dest = tmp_path / "runtime"
    _write_valid_tree(dest)
    runtime._write_marker(dest, _info(dest), "0" * 64)

    def no_network(*args):  # pragma: no cover - must not be reached
        raise AssertionError("network hit despite valid reuse")

    monkeypatch.setattr(runtime, "_resolve_release", no_network)
    monkeypatch.setattr(runtime, "ensure_pip", lambda info, log: None)
    info = runtime.fetch_runtime(_windows_target(), "3.12", dest, log=lambda m: None)
    assert info.version == "3.12.11"


def test_fetch_runtime_refetches_damaged_tree(monkeypatch, tmp_path):
    # Marker present but python.exe missing: the reuse branch must re-verify,
    # discard the tree, and fall through to a fresh fetch.
    dest = tmp_path / "runtime"
    dest.mkdir()
    runtime._write_marker(dest, _info(dest), "0" * 64)

    monkeypatch.setattr(runtime, "_resolve_release", lambda pinned, log: ("t", "http://x"))
    monkeypatch.setattr(
        runtime, "_select_asset", lambda *a: ("a.tar.gz", "0" * 64, "3.12.11")
    )
    downloaded = []
    monkeypatch.setattr(
        runtime, "_download_verified", lambda *a: downloaded.append(a[0])
    )
    monkeypatch.setattr(
        runtime, "_extract_install_only", lambda archive, d, log: _write_valid_tree(d)
    )
    monkeypatch.setattr(runtime, "ensure_pip", lambda info, log: None)
    info = runtime.fetch_runtime(
        _windows_target(),
        "3.12",
        dest,
        cache_dir=tmp_path / "cache",
        log=lambda m: None,
    )
    assert downloaded  # the damaged tree triggered a real fetch
    assert info.python_exe.exists()
