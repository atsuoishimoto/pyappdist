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
