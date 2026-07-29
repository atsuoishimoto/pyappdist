"""Build the POSIX deliverable (Linux and macOS) from the image tree.

Linux and macOS share the same packaging strategy — a relocatable shell-wrapper
launcher plus a self-extracting installer — so the logic lives here and the
``linux``/``macos`` packages are thin ``os_kind`` wrappers over :func:`build_posix`.

One artifact is produced, using the ``compression`` chosen in
``[[tool.pyappdist.targets]]`` (``gzip`` / ``bzip2`` / ``xz``; gzip — the macOS
default — and xz — the Linux default — are compressed through the ``gzip`` / ``xz``
commands when installed on the build host (``xz -T0`` uses every core), falling back
to tarfile's built-in single-threaded codecs otherwise):

* ``<name>-<version>-<target>.run`` — a self-extracting installer: a POSIX shell
  script (``installer.sh``) with a compressed tar of the image tree appended after a
  ``__PYAPPDIST_PAYLOAD__`` marker. The header carries the payload's SHA-256, which the
  installer verifies before extracting. Running it copies the tree into
  ``<prefix>/lib/<name>`` (``$HOME/.local`` by default), symlinks each launcher into
  ``<prefix>/bin``, and — only when ``desktop`` is enabled (Linux) and a launcher has an
  ``icon`` — writes a ``.desktop`` entry. macOS has no freedesktop equivalent, so it
  installs the symlinks only.

The launcher itself is a tiny relocatable shell wrapper (no MSVC, unlike Windows) that
locates the bundled interpreter relative to its own resolved path and runs the entry
point, so it works both from an extracted tarball and from the installed location. Path
resolution uses a POSIX symlink loop rather than ``readlink -f`` (a GNU extension absent
on macOS/BSD), so the same wrapper and installer run on both OSes.
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import lzma
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from ..config import Config, LauncherConfig
from ..errors import BuildError
from ..image.layout import ImageLayout

_PAYLOAD_MARKER = b"__PYAPPDIST_PAYLOAD__\n"

# compression name -> (tarfile mode suffix, installer decompress command)
_COMPRESSION = {
    "gzip": ("gz", "gzip -dc"),
    "bzip2": ("bz2", "bzip2 -dc"),
    "xz": ("xz", "xz -dc"),
}
_INSTALLER_BODY = (Path(__file__).resolve().parent / "installer.sh").read_text(
    encoding="utf-8"
)

# Stand-in for the payload digest while the header is written; patched in place once
# the streamed payload has been hashed. Same length as a real hex SHA-256, so the
# patch never shifts the rest of the file.
_SHA_PLACEHOLDER = "0" * 64


def build_posix(
    config: Config,
    layout: ImageLayout,
    dist_dir: Path,
    *,
    os_kind: str,
    desktop: bool,
    compression: str,
    categories: str = "",
    log=print,
) -> list[Path] | None:
    """Build the .run installer from the image. Returns None for a mismatched target.

    ``os_kind`` is the OS this builder targets (``"linux"`` / ``"macos"``); a target whose
    ``os`` differs is skipped (returns ``None``) so a cross-OS config is a no-op. ``desktop``
    enables freedesktop ``.desktop`` generation and icon staging (Linux only).
    """
    if config.target.os != os_kind:
        log(f"{os_kind}: skipping because the target is not {os_kind}")
        return None

    mode, decompress = _COMPRESSION[compression]

    image_dir = layout.image_dir
    records = write_launchers(config, image_dir, desktop=desktop, log=log)
    launchers_field = " ".join(
        f"{name}:{1 if gui else 0}:{icon}" for (name, gui, icon) in records
    )

    dist_dir.mkdir(parents=True, exist_ok=True)
    base = f"{config.dist_name}-{config.version}-{config.target_name}"

    run = dist_dir / f"{base}.run"
    header = _render_header(
        config,
        launchers_field,
        decompress=decompress,
        desktop=desktop,
        categories=categories,
    ).encode("utf-8")

    with run.open("wb") as fp:
        fp.write(header)
        # The header carries the payload's SHA-256, but the payload is streamed after
        # it (a multi-GB image must not be buffered whole). The digest field is
        # appended right after the rendered header so its offset is known exactly:
        # write a fixed-length placeholder, stream and hash the payload straight into
        # the file, then seek back and overwrite the placeholder with the real digest.
        fp.write(b"PAYLOAD_SHA256='")
        sha_offset = fp.tell()
        fp.write(_SHA_PLACEHOLDER.encode("ascii") + b"'\n")
        fp.write(_INSTALLER_BODY.encode("utf-8"))
        fp.write(_PAYLOAD_MARKER)
        sha256 = write_targz(fp, image_dir, mode=mode, log=log)
        fp.seek(sha_offset)
        fp.write(sha256.encode("ascii"))
    run.chmod(0o755)
    log(f"{os_kind}: installer -> {run} ({compression}, sha256 {sha256[:12]}…)")
    return [run]


def write_launchers(
    config: Config, image_dir: Path, *, desktop: bool, log=print
) -> list[tuple[str, bool, str]]:
    """Write each launcher's shell wrapper (and, on Linux, stage its icon) into the image.

    Public because the ``image`` format reuses the same wrappers (with ``desktop=False``)
    when archiving a Linux/macOS image tree.

    Returns ``(name, gui, icon_filename)`` per launcher; ``icon_filename`` is empty when the
    launcher has no icon or ``desktop`` is disabled (then the installer writes no .desktop).
    """
    records: list[tuple[str, bool, str]] = []
    for spec in config.launchers:
        wrapper = image_dir / spec.name
        wrapper.write_text(_wrapper(spec), encoding="utf-8")
        wrapper.chmod(0o755)

        icon_name = ""
        icon_rel = spec.icon_for("linux")
        if desktop and icon_rel:
            src = (config.project_dir / icon_rel).resolve()
            if not src.is_file():
                raise BuildError(f"launcher icon not found ({spec.name}): {src}")
            icon_name = f"{spec.name}{src.suffix}"
            shutil.copy2(src, image_dir / icon_name)
        records.append((spec.name, spec.gui, icon_name))
        log(f"posix: launcher {spec.name}" + (f" (+ icon {icon_name})" if icon_name else ""))
    return records


def _wrapper(spec: LauncherConfig) -> str:
    """A relocatable POSIX wrapper that runs the entry point via the bundled python."""
    bootstrap = spec.bootstrap
    # Each fixed argument is emitted single-quoted, so the shell neither re-splits it
    # on whitespace nor glob-expands it: the argv the app sees is exactly what
    # ``args`` was split into, matching the Windows and macOS launchers.
    extra = "".join(f" {_sq(arg)}" for arg in spec.argv)
    # Resolve $0 through any symlinks one level at a time (no `readlink -f`, which is a
    # GNU extension missing on macOS/BSD) so the wrapper finds python/ both when run in
    # place and when invoked via a symlink in <prefix>/bin.
    #
    # Isolation mirrors the Windows/macOS C launchers: python's -I (=-E -s) ignores
    # PYTHON* env vars and the user site dir, and we also scrub PYTHON* from the
    # environment (belt-and-suspenders to -I, and so child processes the app spawns
    # don't inherit, say, a stray PYTHONHOME/PYTHONPATH pointing at another install).
    return (
        "#!/bin/sh\n"
        "# Generated by pyappdist. Locates the bundled interpreter relative to itself.\n"
        'for _v in $(env | sed -n '
        "'s/^\\(PYTHON[A-Za-z0-9_]*\\)=.*/\\1/p'); do\n"
        '    unset "$_v"\n'
        'done\n'
        'p=$0\n'
        'while [ -L "$p" ]; do\n'
        '    d=$(CDPATH= cd -- "$(dirname -- "$p")" && pwd -P)\n'
        '    l=$(readlink -- "$p")\n'
        '    case $l in /*) p=$l ;; *) p=$d/$l ;; esac\n'
        'done\n'
        'HERE=$(CDPATH= cd -- "$(dirname -- "$p")" && pwd -P)\n'
        f'exec "$HERE/python/bin/python3" -I -c {_sq(bootstrap)}{extra} "$@"\n'
    )


def _render_header(
    config: Config,
    launchers_field: str,
    *,
    decompress: str,
    desktop: bool,
    categories: str,
) -> str:
    """The generated variable block prepended to the static installer body."""
    # Resolve $0 to a symlink-free absolute path without `readlink -f` (see _wrapper).
    return (
        "#!/bin/sh\n"
        "# Self-extracting installer generated by pyappdist.\n"
        'SELF=$0\n'
        'while [ -L "$SELF" ]; do\n'
        '    _d=$(CDPATH= cd -- "$(dirname -- "$SELF")" && pwd -P)\n'
        '    _l=$(readlink -- "$SELF")\n'
        '    case $_l in /*) SELF=$_l ;; *) SELF=$_d/$_l ;; esac\n'
        'done\n'
        'SELF=$(CDPATH= cd -- "$(dirname -- "$SELF")" && pwd -P)/$(basename -- "$SELF")\n'
        f"APP_NAME={_sq(config.name)}\n"
        f"DIST_NAME={_sq(config.dist_name)}\n"
        f"VERSION={_sq(config.version)}\n"
        f"DESKTOP={_sq('1' if desktop else '0')}\n"
        f"CATEGORIES={_sq(categories)}\n"
        f"LAUNCHERS={_sq(launchers_field)}\n"
        f"DECOMPRESS={_sq(decompress)}\n"
    )


def _sq(s: str) -> str:
    """Quote a string as a single shell word (safe for arbitrary content)."""
    return "'" + s.replace("'", "'\\''") + "'"


# Payload compression levels, chosen for build speed on a typical image: xz preset 6
# (lzma's default) takes several times longer than preset 1 for only a ~15% smaller
# payload, and gzip level 9 (tarfile's default) costs ~6x level 6 for ~1% smaller.
# gzip and xz prefer the external command — ``xz -T0`` compresses on every core, unlike
# Python's single-threaded lzma — and fall back to tarfile's built-in codec (same level,
# same output format) when the command is missing or fails. bzip2 always uses the
# built-in codec.
_XZ_PRESET = 1
_GZIP_LEVEL = 6
# tarfile mode suffix -> (external command, built-in compressor around a writer).
# The fallback compresses through the module directly rather than through
# tarfile's "w:<mode>": the payload is streamed into an already-open output file,
# and tarfile's seekable modes want more than write() from it.
_CODECS = {
    "xz": (
        ["xz", f"-{_XZ_PRESET}", "-T0", "-c"],
        lambda fp: lzma.LZMAFile(fp, "wb", preset=_XZ_PRESET),
    ),
    "gz": (
        ["gzip", f"-{_GZIP_LEVEL}", "-c"],
        lambda fp: gzip.GzipFile(fileobj=fp, mode="wb", compresslevel=_GZIP_LEVEL),
    ),
    "bz2": (None, lambda fp: bz2.BZ2File(fp, "wb")),
}


_CHUNK = 1 << 20  # bytes drained from the compressor at a time


class _HashingWriter:
    """Pass-through writer that hashes everything on its way to ``fp``."""

    def __init__(self, fp, digest) -> None:
        self._fp = fp
        self._digest = digest

    def write(self, data) -> int:
        self._digest.update(data)
        return self._fp.write(data)

    def flush(self) -> None:
        self._fp.flush()


def write_targz(dest, src_dir: Path, *, mode: str, prefix: str = "", log=print) -> str:
    """Stream a compressed tar of ``src_dir`` into ``dest``; return its SHA-256.

    ``dest`` is an open binary file positioned where the payload should start. The
    compressed data is written as it is produced and hashed on the way through, so
    memory stays flat no matter how large the image is — for a multi-GB app, buffering
    the payload (and then concatenating it) cost several GB of RAM.

    Entries are archived under ``prefix/`` when given, else at the archive root (no
    top-level dir — the .run installer's payload layout). Public because the ``image``
    format reuses it for its ``.tar.gz`` deliverable (with a prefix).
    """
    cmd, compressor = _CODECS[mode]
    digest = hashlib.sha256()
    if cmd and shutil.which(cmd[0]):
        start = dest.tell()
        # The uncompressed tar goes to an anonymous temp file, so the compressor reads
        # a real fd; stderr goes to another temp file rather than a pipe, leaving
        # stdout as the only pipe — safe to drain single-threaded (two pipes would
        # deadlock once either buffer fills).
        with tempfile.TemporaryFile() as raw, tempfile.TemporaryFile() as errf:
            with tarfile.open(fileobj=raw, mode="w") as tf:
                _add_tree(tf, src_dir, prefix)
            raw.seek(0)
            proc = subprocess.Popen(cmd, stdin=raw, stdout=subprocess.PIPE, stderr=errf)
            with proc.stdout as out:
                for chunk in iter(lambda: out.read(_CHUNK), b""):
                    digest.update(chunk)
                    dest.write(chunk)
            if proc.wait() == 0:
                return digest.hexdigest()
            errf.seek(0)
            err = errf.read().decode(errors="replace").strip()
        # Discard the partial output before retrying with the built-in codec.
        dest.seek(start)
        dest.truncate()
        digest = hashlib.sha256()
        log(
            f"posix: {cmd[0]} failed (exit {proc.returncode}), "
            f"falling back to the built-in codec:\n{err}"
        )
    # An uncompressed stream tar ("w|") into the compressor, which writes through the
    # hashing wrapper to the output file — every layer needs nothing but write().
    writer = _HashingWriter(dest, digest)
    with compressor(writer) as comp, tarfile.open(fileobj=comp, mode="w|") as tf:
        _add_tree(tf, src_dir, prefix)
    return digest.hexdigest()


def _add_tree(tf: tarfile.TarFile, src_dir: Path, prefix: str = "") -> None:
    for child in sorted(src_dir.iterdir()):
        arcname = f"{prefix}/{child.name}" if prefix else child.name
        tf.add(child, arcname=arcname, filter=_normalize_owner)


def _normalize_owner(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    # Strip the build user's uid/gid: tar running as root restores archive
    # ownership by default, so a root install would hand the tree to whatever
    # local user happens to have the build machine's uid. Root-owned entries
    # also make the payload reproducible across build users.
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    return ti
