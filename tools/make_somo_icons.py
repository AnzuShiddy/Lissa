#!/usr/bin/env python3
"""Draw Somo's app icons — the open book with a question rising from it.

Run:  python3 tools/make_somo_icons.py

Pure standard library, for the same reason as make_athar_icons.py: the build
machine has no Pillow or cairosvg, and adding an image toolchain for two PNGs
generated once is a poor trade. zlib plus struct is a whole PNG encoder.

Coordinates match bots/somo/avatar.svg: a 120x120 box, the book's spine on
the centre line from y=58 down, the question mark centred at y=34.
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
SIZES = (192, 512)
SS = 3  # supersampling per axis — 9 samples a pixel

# Palette, shared with the CSS custom properties in bots/somo/config.py.
BG_IN = (0x1B, 0x25, 0x45)
BG_OUT = (0x08, 0x0D, 0x1C)
PAGE_HI = (0xDC, 0xE6, 0xFB)
PAGE_LO = (0x93, 0xAE, 0xE2)
PAGE2_HI = (0xC3, 0xD4, 0xF5)
PAGE2_LO = (0x77, 0x94, 0xCF)
SPINE = (0x3A, 0x62, 0xC4)
RULE = (0x41, 0x60, 0x9E)
AMBER = (0xFF, 0xD9, 0x89)
AMBER_LO = (0xE0, 0x99, 0x2A)


def mix(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def page(x, y, side):
    """Inside one leaf of the open book.

    The top edge sweeps up towards the outer corner, which is what reads as a
    page lying open rather than a rectangle: at the spine it starts at y=58,
    and it rises as it travels out.
    """
    inner, outer = (60.0, 32.0) if side < 0 else (60.0, 88.0)
    lo, hi = (min(inner, outer), max(inner, outer))
    if not (lo <= x <= hi):
        return False
    t = abs(x - inner) / abs(outer - inner)          # 0 at spine, 1 at edge
    top = 58.0 - 5.5 * t                             # the sweep
    bottom = 94.0 - 3.0 * t
    return top <= y <= bottom


def on_rule(x, y, side):
    """One of the three suggested lines of text on a leaf."""
    if not page(x, y, side):
        return False
    for cy, half in ((64.5, 6.5), (71.5, 7.5), (78.5, 5.5)):
        if abs(y - cy) <= 1.0:
            centre = 46.5 if side < 0 else 73.5
            if abs(x - centre) <= half:
                return True
    return False


def question(x, y):
    """The hook and the dot, drawn as distance to a circular arc.

    An arc plus a short tail is enough at this size — a glyph outline would
    be finer detail than 192 pixels can hold anyway.
    """
    cx, cy, r = 60.3, 27.8, 6.6
    dx, dy = x - cx, y - cy
    d = (dx * dx + dy * dy) ** 0.5
    on_ring = abs(d - r) <= 1.75
    # keep the upper ~2/3 of the ring: open at the bottom left, like a '?'
    if on_ring and not (dy > 0 and dx < 0):
        return True
    # the tail dropping from the ring's lower right to the dot
    if abs(x - (cx + 0.4)) <= 1.75 and cy + r - 1.0 <= y <= 39.0:
        return True
    return (x - 60.6) ** 2 + (y - 43.6) ** 2 <= 2.4 ** 2   # the dot


def sample(x, y):
    """Colour at one point in the 120x120 design space."""
    d = (((x - 60) / 84.0) ** 2 + ((y - 43) / 84.0) ** 2) ** 0.5
    colour = mix(BG_IN, BG_OUT, d)

    # the question glows over the page
    glow = 1.0 - (((x - 60) / 24.0) ** 2 + ((y - 34) / 24.0) ** 2) ** 0.5
    if glow > 0:
        colour = mix(colour, AMBER, 0.16 * glow)

    if page(x, y, -1):
        colour = mix(PAGE_HI, PAGE_LO, (y - 55.0) / 40.0)
    elif page(x, y, 1):
        colour = mix(PAGE2_HI, PAGE2_LO, (y - 55.0) / 40.0)

    if on_rule(x, y, -1) or on_rule(x, y, 1):
        colour = mix(colour, RULE, 0.55)

    if abs(x - 60) <= 1.9 and 57.0 <= y <= 94.5:
        colour = SPINE

    if question(x, y):
        colour = mix(AMBER, AMBER_LO, (y - 20.0) / 26.0)
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

    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        out = OUT / f"somo-{size}.png"
        write_png(out, render(size))
        print(f"wrote {out} ({out.stat().st_size} bytes)")
