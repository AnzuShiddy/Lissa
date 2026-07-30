#!/usr/bin/env python3
"""Draw Athar's app icons — the mihrab-and-lamp mark its header wears.

Run:  python3 tools/make_athar_icons.py

Pure standard library on purpose. The build machine has no Pillow, no
cairosvg and no rsvg-convert, and adding an image toolchain to a project that
needs exactly two PNGs, once, is a poor trade. The geometry is small enough to
evaluate per pixel, and zlib plus struct is a whole PNG encoder.

Coordinates match bots/athar/avatar.svg: a 120x120 box, arch springing
from y=60, apex at y=12, lamp hanging on the centre line.
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
SIZES = (192, 512)
SS = 3  # supersampling factor per axis — 9 samples a pixel, plenty for this

# Palette, shared with the CSS custom properties.
BG_IN = (0x18, 0x39, 0x2C)
BG_OUT = (0x06, 0x13, 0x0D)
JADE = (0x2F, 0xBF, 0x87)
GOLD = (0xE2, 0xC0, 0x76)
GOLD_DIM = (0xB8, 0x91, 0x2F)
FLAME = (0xFF, 0xE0, 0xA0)


def mix(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def in_arch(x, y, inset):
    """Inside the pointed arch, shrunk by `inset` on every side."""
    left, right, foot = 26 + inset, 94 - inset, 102
    if not (left <= x <= right and y <= foot):
        return False
    if y >= 60:
        return True
    rx, ry = 34 - inset, 48 - inset
    if rx <= 0 or ry <= 0:
        return False
    return ((x - 60) / rx) ** 2 + ((y - 60) / ry) ** 2 <= 1.0


def ring(x, y, inset, width):
    """On the arch outline at `inset`, `width` thick, growing inwards."""
    return in_arch(x, y, inset) and not in_arch(x, y, inset + width)


def in_ellipse(x, y, cx, cy, rx, ry):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def star(x, y):
    """The khatim: an eight-pointed outline from two squares off one centre."""
    dx, dy = x - 60, y - 87
    half, w = 7.0, 1.3
    square = max(abs(dx), abs(dy))
    diamond = max(abs(dx + dy), abs(dx - dy)) / 1.41421356
    on_square = half - w <= square <= half
    on_diamond = half - w <= diamond <= half
    return on_square or on_diamond


def sample(x, y):
    """Colour at one point in the 120x120 design space."""
    # background: a soft radial lift toward the top third
    d = (((x - 60) / 84.0) ** 2 + ((y - 44) / 84.0) ** 2) ** 0.5
    colour = mix(BG_IN, BG_OUT, d)

    if in_arch(x, y, 0):
        colour = mix(colour, JADE, 0.20)          # the arch's own tint
    # the lamp throws light into the niche
    glow = 1.0 - (((x - 60) / 26.0) ** 2 + ((y - 62) / 32.0) ** 2) ** 0.5
    if glow > 0 and in_arch(x, y, 0):
        colour = mix(colour, FLAME, 0.22 * glow)

    if ring(x, y, 0, 2.6):
        colour = mix(GOLD, GOLD_DIM, (y - 12) / 90.0)   # outer outline
    elif ring(x, y, 10, 1.2):
        colour = mix(colour, GOLD_DIM, 0.55)            # inner outline
    if 101 <= y <= 105 and 22 <= x <= 98:
        colour = GOLD_DIM                               # the base bar
    if abs(x - 60) <= 0.8 and 22 <= y <= 45:
        colour = GOLD_DIM                               # the chain
    # lamp body: an outlined bowl
    if in_ellipse(x, y, 60, 59, 8.0, 10.0):
        colour = (0x0A, 0x23, 0x1A)
        if not in_ellipse(x, y, 60, 59, 6.6, 8.6):
            colour = GOLD
    if in_ellipse(x, y, 60, 56, 2.6, 4.4):
        colour = FLAME                                  # the flame itself
    if star(x, y):
        colour = GOLD
    return colour


def render(size):
    scale = 120.0 / size
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) * scale
                    y = (py + (sy + 0.5) / SS) * scale
                    c = sample(x, y)
                    r += c[0]
                    g += c[1]
                    b += c[2]
            n = SS * SS
            row += bytes((r // n, g // n, b // n))
        rows.append(row)
    return rows


def write_png(path: Path, rows):
    height = len(rows)
    width = len(rows[0]) // 3

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    # filter byte 0 (None) on every scanline — the shapes are smooth enough
    # that a cleverer filter would buy a few hundred bytes at most
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    for size in SIZES:
        out = OUT / f"athar-{size}.png"
        write_png(out, render(size))
        print(f"wrote {out} ({out.stat().st_size} bytes)")
