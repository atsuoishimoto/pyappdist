"""Minimal PNG writing, shared by the packagers that need placeholder art.

Both the MSIX logos and the macOS ``.icns`` source fall back to a generated solid
image when the project configures no artwork, so the encoder and the placeholder
colour live here rather than being duplicated per packager. Writing the few bytes
of a solid-colour PNG by hand keeps Pillow out of the dependency list.
"""

from __future__ import annotations

import struct
import zlib

# The placeholder fill, shared so every generated stand-in looks the same
# (Windows' accent blue).
PLACEHOLDER_RGB = (0, 120, 212)


def solid_png(width: int, height: int, rgb: tuple[int, int, int] = PLACEHOLDER_RGB) -> bytes:
    """Encode a solid-colour RGB PNG."""

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
