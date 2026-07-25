"""Tests for the image-format archive build (.zip / .tar.gz of the image tree)."""

from __future__ import annotations

import dataclasses
import tarfile
import zipfile
from pathlib import Path

from pyappdist.archive import build_archive
from pyappdist.image.layout import ImageLayout
from pyappdist.launcher.build import build_launchers
from pyappdist.targets import get_target

_PREFIX = "helloworld-1.2.3"  # the archive's top-level directory


def _make_image(tmp_path: Path, target_name: str) -> ImageLayout:
    """A minimal fake image tree (a stand-in interpreter + one file)."""
    image_dir = tmp_path / "image"
    (image_dir / "python" / "bin").mkdir(parents=True)
    (image_dir / "python" / "bin" / "python3").write_text("#!/bin/sh\n")
    (image_dir / "python" / "marker.txt").write_text("hi")
    return ImageLayout(image_dir=image_dir, target=get_target(target_name), minor="3.12")


def _image_config(sample_config, project_dir: Path, target_name: str, **overrides):
    return dataclasses.replace(
        sample_config,
        project_dir=project_dir,
        target=get_target(target_name),
        target_name=target_name,
        format="image",
        **overrides,
    )


def _tar_names(art: Path) -> set[str]:
    with tarfile.open(art, "r:gz") as tf:
        return set(tf.getnames())


def test_linux_archive_is_targz_with_top_level_dir(tmp_path, sample_config):
    layout = _make_image(tmp_path, "linux-x86_64")
    config = _image_config(sample_config, tmp_path, "linux-x86_64")
    arts = build_archive(config, layout, tmp_path / "dist", log=lambda *a: None)

    assert [p.name for p in arts] == [f"{_PREFIX}-linux-x86_64.tar.gz"]
    assert sorted(p.name for p in (tmp_path / "dist").iterdir()) == [arts[0].name]
    members = _tar_names(arts[0])
    assert f"{_PREFIX}/python/bin/python3" in members
    # The POSIX shell-wrapper launcher is written into the archived image.
    assert f"{_PREFIX}/helloworld" in members
    assert all(n.startswith(f"{_PREFIX}/") for n in members)


def test_macos_archive_is_targz(tmp_path, sample_config):
    layout = _make_image(tmp_path, "macos-aarch64")
    config = _image_config(sample_config, tmp_path, "macos-aarch64")
    arts = build_archive(config, layout, tmp_path / "dist", log=lambda *a: None)

    assert [p.name for p in arts] == [f"{_PREFIX}-macos-aarch64.tar.gz"]
    members = _tar_names(arts[0])
    assert f"{_PREFIX}/python/bin/python3" in members
    assert f"{_PREFIX}/helloworld" in members


def test_wrapper_in_archive_is_executable(tmp_path, sample_config):
    layout = _make_image(tmp_path, "linux-x86_64")
    config = _image_config(sample_config, tmp_path, "linux-x86_64")
    arts = build_archive(config, layout, tmp_path / "dist", log=lambda *a: None)

    with tarfile.open(arts[0], "r:gz") as tf:
        wrapper = tf.getmember(f"{_PREFIX}/helloworld")
    assert wrapper.mode & 0o111


def test_windows_archive_is_zip_with_top_level_dir(tmp_path, sample_config):
    layout = _make_image(tmp_path, "windows-x86_64")
    config = _image_config(sample_config, tmp_path, "windows-x86_64")
    arts = build_archive(config, layout, tmp_path / "dist", log=lambda *a: None)

    assert [p.name for p in arts] == [f"{_PREFIX}-windows-x86_64.zip"]
    with zipfile.ZipFile(arts[0]) as zf:
        names = zf.namelist()
    assert f"{_PREFIX}/python/marker.txt" in names
    # No shell wrapper on a Windows target — its launchers are the .exe files
    # compiled into the image by build_launchers before archiving.
    assert f"{_PREFIX}/helloworld" not in names
    assert all(n.startswith(f"{_PREFIX}/") for n in names)


def test_no_launcher_omits_wrappers(tmp_path, sample_config):
    layout = _make_image(tmp_path, "linux-x86_64")
    config = _image_config(sample_config, tmp_path, "linux-x86_64", no_launcher=True)
    arts = build_archive(config, layout, tmp_path / "dist", log=lambda *a: None)

    members = _tar_names(arts[0])
    assert f"{_PREFIX}/helloworld" not in members
    assert not (layout.image_dir / "helloworld").exists()


def test_no_launcher_skips_launcher_build(tmp_path, sample_config):
    layout = _make_image(tmp_path, "windows-x86_64")
    config = _image_config(sample_config, tmp_path, "windows-x86_64", no_launcher=True)
    assert build_launchers(config, layout, tmp_path / "work", log=lambda *a: None) == []


def test_targz_preserves_symlinks_and_normalizes_ownership(tmp_path, sample_config):
    layout = _make_image(tmp_path, "linux-x86_64")
    (layout.image_dir / "python" / "bin" / "python").symlink_to("python3")
    config = _image_config(sample_config, tmp_path, "linux-x86_64")
    arts = build_archive(config, layout, tmp_path / "dist", log=lambda *a: None)

    with tarfile.open(arts[0], "r:gz") as tf:
        link = tf.getmember(f"{_PREFIX}/python/bin/python")
        assert link.issym()
        assert link.linkname == "python3"
        for m in tf.getmembers():
            assert (m.uid, m.gid, m.uname, m.gname) == (0, 0, "", "")
