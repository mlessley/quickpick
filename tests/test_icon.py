import struct

from quickpick.icon import ICON_PATH, SIZES, ico, png, render


def test_render_is_clear_at_the_corners_blue_around_and_white_in_the_bolt():
    rows = render(32)

    assert rows[0][0][3] == 0  # outside the rounded corner
    assert rows[4][4] == (0x00, 0x67, 0xC0, 255)
    assert rows[16][16] == (255, 255, 255, 255)  # the middle of the bolt


def test_png_has_the_signature_and_size():
    data = png(render(16))

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", data[16:24]) == (16, 16)


def test_ico_lists_each_size_with_its_image():
    images = {size: png(render(size)) for size in (16, 32)}

    data = ico(images)

    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, 2)
    width, _height, _colors, _reserved, _planes, _bits, length, offset = struct.unpack(
        "<BBBBHHII", data[6:22]
    )
    assert width == 16
    assert data[offset : offset + length] == images[16]


def test_the_committed_icon_holds_every_size():
    data = ICON_PATH.read_bytes()

    assert struct.unpack("<H", data[4:6])[0] == len(SIZES)
