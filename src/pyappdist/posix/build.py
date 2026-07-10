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

import hashlib
import io
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
    records = _write_launchers(config, image_dir, desktop=desktop, log=log)
    launchers_field = " ".join(
        f"{name}:{1 if gui else 0}:{icon}" for (name, gui, icon) in records
    )

    dist_dir.mkdir(parents=True, exist_ok=True)
    base = f"{config.dist_name}-{config.version}-{config.target_name}"

    run = dist_dir / f"{base}.run"
    payload = _targz_bytes(image_dir, mode=mode, log=log)
    sha256 = hashlib.sha256(payload).hexdigest()
    header = _render_header(
        config,
        launchers_field,
        decompress=decompress,
        sha256=sha256,
        desktop=desktop,
        categories=categories,
    )
    run.write_bytes(
        header.encode("utf-8")
        + _INSTALLER_BODY.encode("utf-8")
        + _PAYLOAD_MARKER
        + payload
    )
    run.chmod(0o755)
    log(f"{os_kind}: installer -> {run} ({compression}, sha256 {sha256[:12]}…)")
    return [run]


def _write_launchers(
    config: Config, image_dir: Path, *, desktop: bool, log
) -> list[tuple[str, bool, str]]:
    """Write each launcher's shell wrapper (and, on Linux, stage its icon) into the image.

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
    args = spec.args.strip()
    extra = f" {args}" if args else ""  # appended verbatim (subject to word splitting)
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
    sha256: str,
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
        f"PAYLOAD_SHA256={_sq(sha256)}\n"
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
# tarfile mode suffix -> (external command, tarfile.open fallback kwargs)
_CODECS = {
    "xz": (["xz", f"-{_XZ_PRESET}", "-T0", "-c"], {"preset": _XZ_PRESET}),
    "gz": (["gzip", f"-{_GZIP_LEVEL}", "-c"], {"compresslevel": _GZIP_LEVEL}),
    "bz2": (None, {}),
}


def _targz_bytes(src_dir: Path, *, mode: str, log=print) -> bytes:
    """Compressed tar of the directory contents (no top-level dir), preserving symlinks."""
    cmd, fallback_kw = _CODECS[mode]
    if cmd and shutil.which(cmd[0]):
        # The uncompressed tar goes to an anonymous temp file, so the compressor reads
        # a real fd and its stdout is the only pipe — safe to drain single-threaded
        # (stdin and stdout both as pipes would deadlock once either buffer fills).
        with tempfile.TemporaryFile() as raw:
            with tarfile.open(fileobj=raw, mode="w") as tf:
                _add_tree(tf, src_dir)
            raw.seek(0)
            proc = subprocess.run(cmd, stdin=raw, capture_output=True)
        if proc.returncode == 0:
            return proc.stdout
        err = proc.stderr.decode(errors="replace").strip()
        log(
            f"posix: {cmd[0]} failed (exit {proc.returncode}), "
            f"falling back to the built-in codec:\n{err}"
        )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=f"w:{mode}", **fallback_kw) as tf:
        _add_tree(tf, src_dir)
    return buf.getvalue()


def _add_tree(tf: tarfile.TarFile, src_dir: Path) -> None:
    for child in sorted(src_dir.iterdir()):
        tf.add(child, arcname=child.name, filter=_normalize_owner)


def _normalize_owner(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    # Strip the build user's uid/gid: tar running as root restores archive
    # ownership by default, so a root install would hand the tree to whatever
    # local user happens to have the build machine's uid. Root-owned entries
    # also make the payload reproducible across build users.
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    return ti
