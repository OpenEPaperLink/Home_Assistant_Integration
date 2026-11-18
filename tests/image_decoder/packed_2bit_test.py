"""Tests for decoding AP raw images of tag types with bpp 5 (packed 2-bit)."""
import io
import sys
from unittest.mock import MagicMock

import pytest
from PIL import Image

sys.modules['serial'] = MagicMock()
sys.modules['serial.tools'] = MagicMock()
sys.modules['serial.tools.list_ports'] = MagicMock()
sys.modules['homeassistant.components.bluetooth'] = MagicMock()

from custom_components.open_epaper_link.image_decompressor import to_image  # noqa: E402
from custom_components.open_epaper_link.tag_types import TagType  # noqa: E402

# Tag type 0xBB as served by the AP (resources/tagtypes/BB.json)
BWRY_29 = {
    "version": 2,
    "name": "Gicisky BLE EPD BWRY 2.9\"",
    "width": 296,
    "height": 128,
    "rotatebuffer": 1,
    "bpp": 5,  # BPP_PACKED_2BIT
    "colortable": {
        "black": [0, 0, 0],
        "white": [255, 255, 255],
        "yellow": [255, 255, 0],
        "red": [255, 0, 0],
    },
}

# Four vertical bands on the displayed image, one per colour table index
BANDS = [1, 0, 3, 2]  # white, black, red, yellow


def _expected_index(x: int, width: int) -> int:
    return BANDS[x * len(BANDS) // width]


def _make_raw(tag: dict) -> bytes:
    """Pack a banded image like the AP: rotated buffer, 2 bits/pixel, MSB first."""
    width, height = tag["width"], tag["height"]
    shown = Image.new("P", (width, height))
    shown.putdata(
        [_expected_index(x, width) for y in range(height) for x in range(width)]
    )
    # rotatebuffer 1: buffer = displayed image turned 90° counter-clockwise
    buffer = shown.transpose(Image.Transpose.ROTATE_90)
    indices = list(buffer.getdata())
    out = bytearray()
    for i in range(0, len(indices), 4):
        a, b, c, d = indices[i:i + 4]
        out.append(a << 6 | b << 4 | c << 2 | d)
    return bytes(out)


def test_packed_2bit_raw_size():
    raw = _make_raw(BWRY_29)
    assert len(raw) == 296 * 128 * 2 // 8


@pytest.mark.parametrize("x", [10, 100, 180, 280])
def test_packed_2bit_decodes_bwry(x):
    tag_type = TagType(0xBB, BWRY_29)
    jpeg = to_image(_make_raw(BWRY_29), tag_type)
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    assert img.size == (296, 128)

    colours = list(BWRY_29["colortable"].values())
    want = colours[_expected_index(x, 296)]
    for y in (5, 64, 120):
        got = img.getpixel((x, y))
        assert all(abs(g - w) < 40 for g, w in zip(got, want)), (x, y, got, want)
