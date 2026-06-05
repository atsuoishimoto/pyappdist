"""Generate a ``.icns`` icon from a single source PNG via ``sips`` + ``iconutil``.

A source PNG (ideally >=1024x1024) is resized into the canonically-named members of an
``.iconset`` directory, then ``iconutil`` packs them into a ``.icns``. When no icon is
configured a solid-colour placeholder PNG is synthesized so the build always succeeds.
"""

from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from ..errors import BuildError

# (pixel size, iconset member name). The names are fixed by iconutil.
_ICONSET: tuple[tuple[int, str], ...] = (
    (16, "16x16"),
    (32, "16x16@2x"),
    (32, "32x32"),
    (64, "32x32@2x"),
    (128, "128x128"),
    (256, "128x128@2x"),
    (256, "256x256"),
    (512, "256x256@2x"),
    (512, "512x512"),
    (1024, "512x512@2x"),
)


def make_icns(source_png: Path | None, dest_icns: Path, *, log=print) -> Path:
    """Build ``dest_icns`` from ``source_png`` (or a placeholder when None)."""
    dest_icns.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if source_png is not None:
            if not source_png.is_file():
                raise BuildError(f"icon not found (launcher icon[\"macos\"]): {source_png}")
            src = source_png
        else:
            src = tmp_path / "placeholder.png"
            src.write_bytes(_solid_png(1024, 1024, (0, 120, 212)))
            log("macos: no icon set; using a generated placeholder (supply 'icon' for real art)")

        iconset = tmp_path / "AppIcon.iconset"
        iconset.mkdir()
        for px, name in _ICONSET:
            out = iconset / f"icon_{name}.png"
            # sips -z takes HEIGHT then WIDTH (equal here).
            _run(["sips", "-z", str(px), str(px), str(src), "--out", str(out)])

        log(f"macos: iconutil -> {dest_icns}")
        _run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest_icns)])
    return dest_icns


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise BuildError(f"{cmd[0]} failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")


def _solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Minimal solid-colour RGB PNG encoder (avoids a Pillow dependency)."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit, colour type 2 (RGB)
    row = b"\x00" + bytes(rgb) * width  # filter byte 0 + pixels
    idat = zlib.compress(row * height, 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )
