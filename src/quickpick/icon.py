"""Quickpick's icon: a white lightning bolt on a blue rounded square, drawn in plain Python
and saved as quickpick.ico beside this file for the Start menu shortcut.

Run `uv run python -m quickpick.icon` to draw it again after changing it here."""

import struct
import zlib
from pathlib import Path

ICON_PATH = Path(__file__).with_name("quickpick.ico")
SIZES = (16, 24, 32, 48, 64, 128, 256)
BACKGROUND = (0x00, 0x67, 0xC0)  # the light theme's accent
BOLT = (0xFF, 0xFF, 0xFF)
CORNER_RADIUS = 0.22  # of the side
# The bolt, as (x, y) fractions of the side, clockwise from its top
BOLT_POINTS = [
    (0.60, 0.12),
    (0.66, 0.12),
    (0.55, 0.43),
    (0.74, 0.43),
    (0.40, 0.89),
    (0.47, 0.57),
    (0.27, 0.57),
]
# Samples per pixel along each side, for smooth edges
SUPERSAMPLE = 4

Pixel = tuple[int, int, int, int]


def _in_rounded_square(x: float, y: float) -> bool:
    r = CORNER_RADIUS
    cx = min(max(x, r), 1 - r)
    cy = min(max(y, r), 1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _in_bolt(x: float, y: float) -> bool:
    """Even-odd ray casting against BOLT_POINTS."""
    inside = False
    edges = zip(BOLT_POINTS, BOLT_POINTS[1:] + BOLT_POINTS[:1], strict=True)
    for (x1, y1), (x2, y2) in edges:
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def render(size: int) -> list[list[Pixel]]:
    """The icon at size x size, as rows of RGBA pixels."""
    rows = []
    step = 1 / (size * SUPERSAMPLE)
    for py in range(size):
        row = []
        for px in range(size):
            square = bolt = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    x = (px * SUPERSAMPLE + sx + 0.5) * step
                    y = (py * SUPERSAMPLE + sy + 0.5) * step
                    if _in_rounded_square(x, y):
                        square += 1
                        bolt += _in_bolt(x, y)
            samples = SUPERSAMPLE * SUPERSAMPLE
            if not square:
                row.append((0, 0, 0, 0))
                continue
            share = bolt / square
            color = tuple(
                round(b * (1 - share) + w * share) for b, w in zip(BACKGROUND, BOLT, strict=True)
            )
            row.append((*color, round(255 * square / samples)))
        rows.append(row)
    return rows


def png(rows: list[list[Pixel]]) -> bytes:
    """rows of RGBA pixels as a PNG file."""
    height, width = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def ico(images: dict[int, bytes]) -> bytes:
    """An .ico holding a PNG per size (Windows Vista and later read PNG entries)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = data = b""
    for size, image in images.items():
        side = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(image), offset)
        data += image
        offset += len(image)
    return header + entries + data


def main() -> None:
    ICON_PATH.write_bytes(ico({size: png(render(size)) for size in SIZES}))
    print(f"Wrote {ICON_PATH}")


if __name__ == "__main__":
    main()
