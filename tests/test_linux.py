"""Tests for the Linux self-extracting .run build."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import re
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


def test_run_payload_ownership_is_normalized(tmp_path, sample_config):
    """No build-user uid/gid in the payload — root installs must not hand the
    tree to whatever install-machine user shares the build user's uid."""
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    run = next(p for p in arts if p.suffix == ".run")

    _, payload = _split_run(run)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as tf:
        for m in tf.getmembers():
            assert (m.uid, m.gid, m.uname, m.gname) == (0, 0, "", "")


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


@pytest.mark.parametrize(
    "args,expected",
    [
        ("", ""),
        ("--verbose", " '--verbose'"),
        ("--path 'a b'", " '--path' 'a b'"),  # one argument, not two
        ("-x *", " '-x' '*'"),                # quoted, so the shell never globs it
    ],
)
def test_wrapper_quotes_each_fixed_arg(args, expected):
    # The wrapper used to append args verbatim, leaving them to the shell's word
    # splitting and glob expansion — a different meaning from the other launchers.
    spec = LauncherConfig(name="app", entry="pkg.mod:main", args=args)
    w = _wrapper(spec)
    exec_line = next(ln for ln in w.splitlines() if ln.startswith("exec "))
    assert exec_line.endswith(f'{expected} "$@"')


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


def test_write_targz_digests_exactly_what_it_wrote(tmp_path):
    """The payload is hashed as it streams out, from wherever the file is positioned."""
    from pyappdist.posix.build import write_targz

    layout = _make_image(tmp_path)
    out = tmp_path / "payload"
    with out.open("wb") as fp:
        fp.write(b"header bytes")  # the .run writes the payload after its header
        digest = write_targz(fp, layout.image_dir, mode="gz", log=lambda *a: None)

    payload = out.read_bytes()[len(b"header bytes"):]
    assert hashlib.sha256(payload).hexdigest() == digest
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
        assert "python/bin/python3" in tf.getnames()


def test_run_header_digest_placeholder_is_patched(tmp_path, sample_config):
    """The digest is written last, over its placeholder — none may survive."""
    from pyappdist.posix.build import _SHA_PLACEHOLDER

    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)
    script, payload = _split_run(next(p for p in arts if p.suffix == ".run"))

    assert _SHA_PLACEHOLDER not in script
    assert f"PAYLOAD_SHA256='{hashlib.sha256(payload).hexdigest()}'" in script


@pytest.mark.parametrize("compression", ["gzip", "xz"])
def test_falls_back_to_tarfile_codec_without_the_command(
    tmp_path, sample_config, monkeypatch, compression
):
    """With no gzip/xz command on the build host, the payload is still built (tarfile)."""
    import pyappdist.posix.build as posix_build

    monkeypatch.setattr(posix_build.shutil, "which", lambda cmd: None)
    magic, read_mode = _COMPRESSION[compression]
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path, compression=compression)
    arts = build_linux(config, layout, tmp_path / "dist", log=lambda *a: None)

    run = next(p for p in arts if p.suffix == ".run")
    script, payload = _split_run(run)
    assert payload[: len(magic)] == magic
    with tarfile.open(fileobj=io.BytesIO(payload), mode=read_mode) as tf:
        assert tf.getnames()
    assert f"PAYLOAD_SHA256='{hashlib.sha256(payload).hexdigest()}'" in script


@pytest.mark.parametrize("compression", ["gzip", "xz"])
def test_falls_back_when_the_command_fails(tmp_path, sample_config, monkeypatch, compression):
    """A failing gzip/xz command logs its stderr and falls back to the built-in codec."""
    import pyappdist.posix.build as posix_build

    tool = _DECOMP_TOOL[compression]

    class _FailingPopen:
        """A compressor that emits some output, then fails partway through."""

        returncode = 1

        def __init__(self, cmd, stdin=None, stdout=None, stderr=None, **kwargs):
            # Partial output the caller must discard before falling back.
            self.stdout = io.BytesIO(b"truncated garbage")
            stderr.write(b"out of memory")

        def wait(self):
            return self.returncode

    monkeypatch.setattr(posix_build.subprocess, "Popen", _FailingPopen)
    magic, read_mode = _COMPRESSION[compression]
    layout = _make_image(tmp_path)
    config = _linux_config(sample_config, tmp_path, compression=compression)
    logs: list[str] = []
    arts = build_linux(config, layout, tmp_path / "dist", log=logs.append)

    assert any(f"{tool} failed" in m and "out of memory" in m for m in logs)
    run = next(p for p in arts if p.suffix == ".run")
    script, payload = _split_run(run)
    assert payload[: len(magic)] == magic
    with tarfile.open(fileobj=io.BytesIO(payload), mode=read_mode) as tf:
        assert tf.getnames()
    assert f"PAYLOAD_SHA256='{hashlib.sha256(payload).hexdigest()}'" in script


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


def _build_gui_run(tmp_path, sample_config, workdir, launcher_names, version="1.0"):
    """Build a gzip .run in its own workdir with GUI+icon launchers named as given."""
    workdir.mkdir()
    layout = _make_image(workdir)
    launchers = tuple(
        LauncherConfig(
            name=name, entry="helloworld:main", gui=True, icons=(("linux", "app.png"),)
        )
        for name in launcher_names
    )
    config = dataclasses.replace(
        sample_config,
        project_dir=tmp_path,
        version=version,
        target=get_target("linux-x86_64"),
        target_name="linux-x86_64",
        format="linux",
        launchers=launchers,
        linux=LinuxConfig(compression="gzip"),
    )
    arts = build_linux(config, layout, workdir / "dist", log=lambda *a: None)
    return next(p for p in arts if p.suffix == ".run")


def _desktop_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Installer env with XDG_DATA_HOME pinned; returns (env, applications dir)."""
    appdir = tmp_path / "home" / ".local" / "share" / "applications"
    env = {**_installer_env(tmp_path), "XDG_DATA_HOME": str(appdir.parent)}
    return env, appdir


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
def test_upgrade_removes_renamed_launcher_artifacts(tmp_path, sample_config):
    """Installing v2 over v1 removes v1's launchers even after a rename (#64).

    The previous version's uninstall.sh records the launcher set that was actually
    installed, so the installer runs it before extracting rather than trusting the
    new package's launcher list.
    """
    if shutil.which("gzip") is None:
        pytest.skip("gzip not installed")
    (tmp_path / "app.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    v1 = _build_gui_run(tmp_path, sample_config, tmp_path / "v1", ["foo"], version="1.0")
    v2 = _build_gui_run(tmp_path, sample_config, tmp_path / "v2", ["bar"], version="2.0")

    prefix = tmp_path / "prefix"
    env, appdir = _desktop_env(tmp_path)
    res = subprocess.run(
        ["/bin/sh", str(v1), "--prefix", str(prefix)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    assert (prefix / "bin" / "foo").is_symlink()
    # A single menu entry keeps the plain app name.
    assert "Name=Hello World\n" in (appdir / "helloworld-foo.desktop").read_text()

    res = subprocess.run(
        ["/bin/sh", str(v2), "--prefix", str(prefix)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    # v2's launcher is installed...
    assert (prefix / "bin" / "bar").is_symlink()
    assert (appdir / "helloworld-bar.desktop").exists()
    # ...and v1's renamed launcher left no dangling symlink or dead menu entry.
    assert not (prefix / "bin" / "foo").is_symlink()
    assert not (appdir / "helloworld-foo.desktop").exists()


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
def test_multi_launcher_desktop_names_are_disambiguated(tmp_path, sample_config):
    """With two menu entries, each .desktop Name carries the launcher name."""
    if shutil.which("gzip") is None:
        pytest.skip("gzip not installed")
    (tmp_path / "app.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    run = _build_gui_run(tmp_path, sample_config, tmp_path / "build", ["foo", "bar"])

    prefix = tmp_path / "prefix"
    env, appdir = _desktop_env(tmp_path)
    res = subprocess.run(
        ["/bin/sh", str(run), "--prefix", str(prefix)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    assert "Name=Hello World - foo\n" in (appdir / "helloworld-foo.desktop").read_text()
    assert "Name=Hello World - bar\n" in (appdir / "helloworld-bar.desktop").read_text()


# Desktop Entry escaping, applied when a path is interpolated into an entry.
# A string value only reserves the backslash; an Exec argument additionally
# backslash-escapes ", ` and $ inside the quotes, and that escaping is then
# itself string-escaped — so every added backslash appears doubled.
_STRING_ESCAPES = {"\\": "\\" * 2}
_EXEC_ESCAPES = {
    "\\": "\\" * 4,
    '"': "\\" * 2 + '"',
    "`": "\\" * 2 + "`",
    "$": "\\" * 2 + "$",
}


def _escape(path: str, table: dict[str, str]) -> str:
    return "".join(table.get(c, c) for c in path)


_INSTALLER_SH = (
    Path(__file__).resolve().parents[1]
    / "src" / "pyappdist" / "posix" / "installer.sh"
)


def _shell_escape(func: str, value: str) -> str:
    """Call one of installer.sh's escaping helpers with ``value``.

    The helpers are lifted out of the installer verbatim (they are top-level
    definitions with no nested braces at column 0), so the rules are tested where
    they are written rather than restated here.
    """
    body = _INSTALLER_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{func}\(\) \{{.*?^\}}", body, re.DOTALL | re.MULTILINE)
    assert match, f"{func} not found in installer.sh"
    res = subprocess.run(
        ["/bin/sh", "-c", f'{match.group(0)}\n{func} "$1"', "_", value],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
@pytest.mark.parametrize(
    "value,expected",
    [
        ("/plain/path", "/plain/path"),
        ("/with space/x", "/with space/x"),
        ("/a\\b", "/a" + "\\" * 2 + "b"),     # only the backslash is reserved
        ('/a"b', '/a"b'),
        ("/a$b", "/a$b"),
    ],
)
def test_desktop_string_escaping(value, expected):
    assert _shell_escape("desktop_string", value) == expected


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
@pytest.mark.parametrize(
    "value,expected",
    [
        ("/plain/path", '"/plain/path"'),
        ("/with space/x", '"/with space/x"'),
        ("/a\\b", '"/a' + "\\" * 4 + 'b"'),   # Exec escape, then string escape
        ('/a"b', '"/a' + "\\" * 2 + '"b"'),
        ("/a$b", '"/a' + "\\" * 2 + '$b"'),
        ("/a`b", '"/a' + "\\" * 2 + '`b"'),
    ],
)
def test_desktop_exec_arg_escaping(value, expected):
    assert _shell_escape("desktop_exec_arg", value) == expected


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
def test_desktop_entry_escapes_special_characters(tmp_path, sample_config):
    """A prefix with Desktop-Entry-reserved characters produces a valid entry."""
    if shutil.which("gzip") is None:
        pytest.skip("gzip not installed")
    (tmp_path / "app.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    run = _build_gui_run(tmp_path, sample_config, tmp_path / "build", ["foo"])

    # Reserved characters that survive an install end to end. A backslash is
    # escaped correctly too (see the unit tests above), but GNU tar rejects a
    # -C directory containing one, so it cannot be exercised here.
    prefix = tmp_path / 'we$ird `sub` "q" dir'
    env, appdir = _desktop_env(tmp_path)
    res = subprocess.run(
        ["/bin/sh", str(run), "--prefix", str(prefix)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr

    libdir = prefix / "lib" / "helloworld"
    text = (appdir / "helloworld-foo.desktop").read_text()
    assert f'Exec="{_escape(str(libdir / "foo"), _EXEC_ESCAPES)}" %U\n' in text
    assert f"Icon={_escape(str(libdir / 'foo.png'), _STRING_ESCAPES)}\n" in text
    # Nothing leaked onto extra lines: the entry keeps its fixed shape.
    assert len([ln for ln in text.splitlines() if ln]) == 8  # header + 7 keys


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="POSIX shell required")
def test_desktop_entry_refuses_unrepresentable_prefix(tmp_path, sample_config):
    """A newline in the prefix cannot be written to an entry, so the install stops."""
    if shutil.which("gzip") is None:
        pytest.skip("gzip not installed")
    (tmp_path / "app.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    run = _build_gui_run(tmp_path, sample_config, tmp_path / "build", ["foo"])

    prefix = tmp_path / "two\nlines"
    env, _appdir = _desktop_env(tmp_path)
    res = subprocess.run(
        ["/bin/sh", str(run), "--prefix", str(prefix)],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode != 0
    assert "tab or newline" in res.stderr
    # It fails before extracting, so no half-install is left behind.
    assert not (prefix / "lib" / "helloworld").exists()


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
