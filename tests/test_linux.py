"""Tests for the Linux self-extracting .run build."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from pyappdist.config import LauncherConfig, LinuxConfig
from pyappdist.image.layout import ImageLayout
from pyappdist.linux.build import build_linux
from pyappdist.posix.build import _PAYLOAD_MARKER, _sq, _wrapper
from pyappdist.targets import get_target


def _make_image(tmp_path: Path) -> ImageLayout:
    """A minimal fake image tree (a stand-in interpreter + one file)."""
    image_dir = tmp_path / "image"
    (image_dir / "python" / "bin").mkdir(parents=True)
    (image_dir / "python" / "bin" / "python3").write_text("#!/bin/sh\n")
    (image_dir / "python" / "marker.txt").write_text("hi")
    return ImageLayout(image_dir=image_dir, target=get_target("linux-x86_64"), minor="3.12")


# compression name -> (payload magic bytes, tarfile read mode)
_COMPRESSION = {
    "gzip": (b"\x1f\x8b", "r:gz"),
    "bzip2": (b"BZh", "r:bz2"),
    "xz": (b"\xfd7zXZ\x00", "r:xz"),
}
# CLI decompressor each compression needs at install time.
_DECOMP_TOOL = {"gzip": "gzip", "bzip2": "bzip2", "xz": "xz"}


def _installer_env(tmp_path: Path) -> dict[str, str]:
    """Environment for running the .run in the E2E tests.

    The real PATH is inherited rather than reconstructed: the installer only uses standard
    utilities (tar, the decompressor, shasum/sha256sum, cp/ln/...) found by PATH, and never
    resolves python through it (the launcher execs the bundled interpreter by absolute
    path). So a user's normal PATH — including Homebrew, where macOS's ``xz`` typically
    lives — is exactly the right environment, and there's nothing to exclude. Only HOME is
    overridden, to sandbox the per-user install (prefix and any .desktop) into tmp_path.
    """
    return {**os.environ, "HOME": str(tmp_path / "home")}


def _linux_config(sample_config, project_dir: Path, *, compression="xz", **launcher_kwargs):
    launcher = LauncherConfig(name="helloworld", entry="helloworld:main", **launcher_kwargs)
    return dataclasses.replace(
        sample_config,
        project_dir=project_dir,
        target=get_target("linux-x86_64"),
        target_name="linux-x86_64",
        format="linux",
        launchers=(launcher,),
        linux=LinuxConfig(compression=compression),
    )


def _split_run(run: Path) -> tuple[str, bytes]:
    """Return (script text before the payload, payload bytes after the marker)."""
    data = run.read_bytes()
    idx = data.index(_PAYLOAD_MARKER)
    return data[:idx].decode("utf-8"), data[idx + len(_PAYLOAD_MARKER):]


def test_build_linux_produces_only_the_run_installer(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)

    # Only the installer lands in dist/ — no portable tarball.
    names = sorted(p.name for p in arts)
    assert names == ["helloworld-1.2.3-linux-x86_64.run"]
    assert sorted(p.name for p in (tmp_path / "dist").iterdir()) == names
    run = arts[0]
    assert run.suffix == ".run"
    assert run.stat().st_mode & 0o111  # executable


def test_run_header_has_metadata_and_marker(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    script, payload = _split_run(run)
    assert script.startswith("#!/bin/sh")
    assert "APP_NAME='Hello World'" in script
    assert "DIST_NAME='helloworld'" in script
    assert "VERSION='1.2.3'" in script
    # No icon -> the launcher record carries an empty icon field.
    assert "LAUNCHERS='helloworld:0:'" in script
    assert "DECOMPRESS='xz -dc'" in script
    assert f"PAYLOAD_SHA256='{hashlib.sha256(payload).hexdigest()}'" in script
    assert payload[:6] == b"\xfd7zXZ\x00"  # xz magic (the default)


def test_run_payload_is_the_image_tree(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    _, payload = _split_run(run)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as tf:
        members = set(tf.getnames())
    # Payload has no top-level dir; it includes the generated launcher wrapper.
    assert "python/bin/python3" in members
    assert "helloworld" in members


def test_icon_triggers_desktop_record(tmp_path, sample_config):
    (tmp_path / "app.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path, gui=True, icons=(("linux", "app.png"),))
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    script, payload = _split_run(run)
    assert "LAUNCHERS='helloworld:1:helloworld.png'" in script
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as tf:
        assert "helloworld.png" in tf.getnames()  # icon staged into the image


def test_build_linux_skips_non_linux(tmp_path, sample_config):
    layout = ImageLayout(
        image_dir=tmp_path / "image", target=get_target("windows-x86_64"), minor="3.12"
    )
    assert build_linux(sample_config, layout, tmp_path / "dist", log=lambda *a: None) is None


def test_wrapper_is_relocatable():
    spec = LauncherConfig(name="app", entry="pkg.mod:main")
    w = _wrapper(spec)
    # Resolves symlinks via a POSIX loop (no `readlink -f`, absent on macOS/BSD) so the
    # wrapper works both in place and when invoked through a <prefix>/bin symlink.
    assert "readlink -f" not in w
    assert 'while [ -L "$p" ]' in w
    assert '"$HERE/python/bin/python3"' in w
    assert "from pkg.mod import main" in w


def test_wrapper_isolates_python_env():
    spec = LauncherConfig(name="app", entry="pkg.mod:main")
    w = _wrapper(spec)
    # Mirrors the C launchers: -I (=-E -s) tells the bundled interpreter to ignore
    # PYTHON* env vars and the user site dir, and PYTHON* is scrubbed from the
    # environment so the app (and anything it spawns) never sees a stray PYTHONHOME
    # or PYTHONPATH from the host.
    assert '"$HERE/python/bin/python3" -I -c ' in w
    assert "unset" in w
    assert "PYTHON" in w


def test_sq_escapes_single_quotes():
    assert _sq("a'b") == "'a'\\''b'"


@pytest.mark.parametrize("compression", ["gzip", "bzip2", "xz"])
def test_compression_option(tmp_path, sample_config, compression):
    """Each compression sets the payload format, decompressor and sha256."""
    magic, read_mode = _COMPRESSION[compression]
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path, compression=compression)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)

    run = next(p for p in arts if p.suffix == ".run")
    script, payload = _split_run(run)
    assert payload[: len(magic)] == magic
    with tarfile.open(fileobj=io.BytesIO(payload), mode=read_mode) as tf:  # correct compression
        assert tf.getnames()
    assert f"PAYLOAD_SHA256='{hashlib.sha256(payload).hexdigest()}'" in script
    assert f"DECOMPRESS='{_DECOMP_TOOL[compression]} -dc'" in script


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
def test_run_detects_corrupt_payload(tmp_path, sample_config):
    """A flipped payload byte fails the checksum and leaves an existing install intact."""
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    # Flip the final byte of the payload to corrupt it.
    data = bytearray(run.read_bytes())
    data[-1] ^= 0xFF
    run.write_bytes(data)

    prefix = tmp_path / "prefix"
    env = _installer_env(tmp_path)
    res = subprocess.run(
        ["/bin/sh", str(run), "--prefix", str(prefix)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode != 0
    assert "checksum mismatch" in res.stderr
    assert not (prefix / "lib" / "helloworld").exists()  # nothing was extracted


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
@pytest.mark.parametrize("compression", ["gzip", "bzip2", "xz"])
def test_run_installs_and_uninstalls(tmp_path, sample_config, compression):
    """End-to-end: execute the .run into a throwaway prefix, then uninstall."""
    if shutil.which(_DECOMP_TOOL[compression]) is None:
        pytest.skip(f"{_DECOMP_TOOL[compression]} not installed")
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path, compression=compression)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    prefix = tmp_path / "prefix"
    env = _installer_env(tmp_path)
    res = subprocess.run(
        ["/bin/sh", str(run), "--prefix", str(prefix)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    libdir = prefix / "lib" / "helloworld"
    assert (libdir / "python" / "bin" / "python3").exists()
    assert (prefix / "bin" / "helloworld").is_symlink()
    assert (libdir / "uninstall.sh").exists()

    res = subprocess.run(
        ["/bin/sh", str(run), "--prefix", str(prefix), "--uninstall"],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    assert not libdir.exists()
    assert not (prefix / "bin" / "helloworld").exists()
