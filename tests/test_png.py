"""Tests for the shared placeholder PNG encoder."""

from __future__ import annotations

import struct
import zlib

from pyappdist._png import PLACEHOLDER_RGB, solid_png


def test_solid_png_is_valid_png():
    data = solid_png(16, 16, (0, 120, 212))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in data[:32] and data.rstrip().endswith(b"\xaeB`\x82")  # IEND CRC


def test_solid_png_header_carries_the_size():
    width, height, depth, colour_type = struct.unpack(">IIBB", solid_png(32, 24)[16:26])
    assert (width, height) == (32, 24)
    assert (depth, colour_type) == (8, 2)  # 8-bit RGB


def test_solid_png_pixels_are_the_requested_colour():
    rgb = (1, 2, 3)
    data = solid_png(4, 2, rgb)
    start = data.index(b"IDAT") + 4
    length = struct.unpack(">I", data[start - 8 : start - 4])[0]
    raw = zlib.decompress(data[start : start + length])
    assert raw == (b"\x00" + bytes(rgb) * 4) * 2  # filter byte + pixels, per row


def test_solid_png_defaults_to_the_placeholder_colour():
    assert solid_png(2, 2) == solid_png(2, 2, PLACEHOLDER_RGB)
