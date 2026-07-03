"""Tests for the macOS self-extracting .run build.

macOS shares the POSIX builder with Linux (see test_linux.py); these tests cover the
macOS-specific behavior: gzip default compression and no freedesktop integration
(``DESKTOP='0'``, launcher icons ignored).
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from pyappdist.config import LauncherConfig, MacosConfig
from pyappdist.image.layout import ImageLayout
from pyappdist.macos.build import build_macos
from pyappdist.posix.build import _PAYLOAD_MARKER
from pyappdist.targets import get_target


def _make_image(tmp_path: Path) -> ImageLayout:
    """A minimal fake image tree (a stand-in interpreter + one file)."""
    image_dir = tmp_path / "image"
    (image_dir / "python" / "bin").mkdir(parents=True)
    (image_dir / "python" / "bin" / "python3").write_text("#!/bin/sh\n")
    (image_dir / "python" / "marker.txt").write_text("hi")
    return ImageLayout(image_dir=image_dir, target=get_target("macos-aarch64"), minor="3.12")


def _macos_config(sample_config, project_dir: Path, *, compression="gzip", **launcher_kwargs):
    launcher = LauncherConfig(name="helloworld", entry="helloworld:main", **launcher_kwargs)
    return dataclasses.replace(
        sample_config,
        project_dir=project_dir,
        target=get_target("macos-aarch64"),
        target_name="macos-aarch64",
        format="macos",
        launchers=(launcher,),
        macos=MacosConfig(compression=compression),
    )


def _split_run(run: Path) -> tuple[str, bytes]:
    """Return (script text before the payload, payload bytes after the marker)."""
    data = run.read_bytes()
    idx = data.index(_PAYLOAD_MARKER)
    return data[:idx].decode("utf-8"), data[idx + len(_PAYLOAD_MARKER):]


def test_build_macos_produces_only_the_run_installer(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _macos_config(sample_config, tmp_path)
    arts = build_macos(config, layout, tmp_path / "dist", log=lambda *a: None)

    # Only the installer lands in dist/ — no portable tarball.
    names = sorted(p.name for p in arts)
    assert names == ["helloworld-1.2.3-macos-aarch64.run"]
    assert sorted(p.name for p in (tmp_path / "dist").iterdir()) == names
    run = arts[0]
    assert run.suffix == ".run"
    assert run.stat().st_mode & 0o111  # executable


def test_run_header_has_metadata_and_no_desktop(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _macos_config(sample_config, tmp_path)
    arts = build_macos(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    script, payload = _split_run(run)
    assert script.startswith("#!/bin/sh")
    assert "APP_NAME='Hello World'" in script
    assert "DIST_NAME='helloworld'" in script
    assert "VERSION='1.2.3'" in script
    assert "DESKTOP='0'" in script  # macOS has no freedesktop integration
    assert "LAUNCHERS='helloworld:0:'" in script
    assert "DECOMPRESS='gzip -dc'" in script
    assert f"PAYLOAD_SHA256='{hashlib.sha256(payload).hexdigest()}'" in script
    assert payload[:2] == b"\x1f\x8b"  # gzip magic (the default)


def test_icon_is_ignored_on_macos(tmp_path, sample_config):
    """A launcher icon produces no .desktop record and is not staged into the image."""
    (tmp_path / "app.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    layout = _make_image(tmp_path)
    config = _macos_config(sample_config, tmp_path, gui=True, icons=(("linux", "app.png"),))
    arts = build_macos(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    script, payload = _split_run(run)
    # gui flag is still recorded, but the icon field stays empty (no desktop entry).
    assert "LAUNCHERS='helloworld:1:'" in script
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
        assert "helloworld.png" not in tf.getnames()


def test_run_payload_is_the_image_tree(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _macos_config(sample_config, tmp_path)
    arts = build_macos(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    _, payload = _split_run(run)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
        members = set(tf.getnames())
    assert "python/bin/python3" in members
    assert "helloworld" in members  # the generated launcher wrapper


def test_build_macos_skips_non_macos(tmp_path, sample_config):
    layout = ImageLayout(
        image_dir=tmp_path / "image", target=get_target("linux-x86_64"), minor="3.12"
    )
    assert build_macos(sample_config, layout, tmp_path / "dist", log=lambda *a: None) is None


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
def test_run_installs_and_uninstalls_without_desktop(tmp_path, sample_config):
    """End-to-end: execute the .run into a throwaway prefix; no .desktop is written."""
    layout = _make_image(tmp_path)
    config = _macos_config(sample_config, tmp_path)
    arts = build_macos(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    prefix = tmp_path / "prefix"
    home = tmp_path / "home"
    # Inherit the real PATH (gzip lives in /usr/bin, but tools generally may be in Homebrew
    # etc.); only HOME is overridden, to sandbox the install. See test_linux._installer_env.
    env = {**os.environ, "HOME": str(home)}
    res = subprocess.run(
        ["/bin/sh", str(run), "--prefix", str(prefix)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    libdir = prefix / "lib" / "helloworld"
    assert (libdir / "python" / "bin" / "python3").exists()
    assert (prefix / "bin" / "helloworld").is_symlink()
    assert (libdir / "uninstall.sh").exists()
    # No freedesktop entry anywhere under the fake HOME.
    assert not list(home.glob("**/*.desktop"))

    res = subprocess.run(
        ["/bin/sh", str(run), "--prefix", str(prefix), "--uninstall"],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    assert not libdir.exists()
    assert not (prefix / "bin" / "helloworld").exists()
