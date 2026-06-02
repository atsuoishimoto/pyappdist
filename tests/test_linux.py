"""Tests for the Linux .tar.gz + self-extracting .run build."""

from __future__ import annotations

import dataclasses
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from pyappdist.config import LauncherConfig, LinuxConfig
from pyappdist.image.layout import ImageLayout
from pyappdist.linux.build import _PAYLOAD_MARKER, _sq, _wrapper, build_linux
from pyappdist.targets import get_target


def _make_image(tmp_path: Path) -> ImageLayout:
    """A minimal fake image tree (a stand-in interpreter + one file)."""
    image_dir = tmp_path / "image"
    (image_dir / "python" / "bin").mkdir(parents=True)
    (image_dir / "python" / "bin" / "python3").write_text("#!/bin/sh\n")
    (image_dir / "python" / "marker.txt").write_text("hi")
    return ImageLayout(image_dir=image_dir, target=get_target("linux-x86_64"), minor="3.12")


def _linux_config(sample_config, project_dir: Path, **launcher_kwargs):
    launcher = LauncherConfig(name="helloworld", entry="helloworld:main", **launcher_kwargs)
    return dataclasses.replace(
        sample_config,
        project_dir=project_dir,
        target=get_target("linux-x86_64"),
        target_name="linux-x86_64",
        format="linux",
        launchers=(launcher,),
        linux=LinuxConfig(),
    )


def _split_run(run: Path) -> tuple[str, bytes]:
    """Return (script text before the payload, payload bytes after the marker)."""
    data = run.read_bytes()
    idx = data.index(_PAYLOAD_MARKER)
    return data[:idx].decode("utf-8"), data[idx + len(_PAYLOAD_MARKER):]


def test_build_linux_produces_both_artifacts(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)

    names = sorted(p.name for p in arts)
    assert names == [
        "helloworld-1.2.3-linux-x86_64.run",
        "helloworld-1.2.3-linux-x86_64.tar.gz",
    ]
    run = next(p for p in arts if p.suffix == ".run")
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
    assert payload[:2] == b"\x1f\x8b"  # gzip magic


def test_run_payload_is_the_image_tree(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    _, payload = _split_run(run)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
        members = set(tf.getnames())
    # Payload has no top-level dir; it includes the generated launcher wrapper.
    assert "python/bin/python3" in members
    assert "helloworld" in members


def test_tarball_has_top_level_dir(tmp_path, sample_config):
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    tarball = next(p for p in arts if p.name.endswith(".tar.gz"))

    with tarfile.open(tarball, "r:gz") as tf:
        names = tf.getnames()
    assert all(n.startswith("helloworld-1.2.3/") for n in names)


def test_icon_triggers_desktop_record(tmp_path, sample_config):
    (tmp_path / "app.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path, gui=True, icon="app.png")
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    script, payload = _split_run(run)
    assert "LAUNCHERS='helloworld:1:helloworld.png'" in script
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
        assert "helloworld.png" in tf.getnames()  # icon staged into the image


def test_build_linux_skips_non_linux(tmp_path, sample_config):
    layout = ImageLayout(
        image_dir=tmp_path / "image", target=get_target("windows-x86_64"), minor="3.12"
    )
    assert build_linux(sample_config, layout, tmp_path / "dist", log=lambda *a: None) is None


def test_wrapper_is_relocatable():
    spec = LauncherConfig(name="app", entry="pkg.mod:main")
    w = _wrapper(spec)
    assert "readlink -f" in w
    assert '"$HERE/python/bin/python3"' in w
    assert "from pkg.mod import main" in w


def test_sq_escapes_single_quotes():
    assert _sq("a'b") == "'a'\\''b'"


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
def test_run_installs_and_uninstalls(tmp_path, sample_config):
    """End-to-end: execute the .run into a throwaway prefix, then uninstall."""
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    prefix = tmp_path / "prefix"
    env = {"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin"}
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
