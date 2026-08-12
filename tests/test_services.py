"""Action schemas, with the pre-4.0 call shapes still accepted.

drawcustom payloads are large hand-written YAML in people's automations, so
old calls must keep working. These pin the coercion.
"""

from __future__ import annotations

import pytest
import voluptuous as vol
from epaper_dithering import ColorScheme, DitherMode
from oepl import LUT, TagType

from custom_components.open_epaper_link.services import (
    SCHEMA_DRAWCUSTOM,
    _color_scheme,
)

PAYLOAD = [{"type": "text", "value": "Hello", "x": 0, "y": 0}]


def _drawcustom(**overrides: object) -> dict:
    """Validate a drawcustom call, as Home Assistant would."""
    return SCHEMA_DRAWCUSTOM({"payload": PAYLOAD, **overrides})


# ---------------------------------------------------------------------------
# refresh_type
# ---------------------------------------------------------------------------


def test_refresh_type_defaults_to_adaptive() -> None:
    """The default no longer forces a full refresh on every update.

    The pre-4.0 default was "0", labelled Full, which stored the value that
    makes the tag do a full waveform every time and drains its battery.
    """
    assert _drawcustom()["refresh_type"] is LUT.DEFAULT


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("0", LUT.NO_REPEAT),  # was labelled "Full"
        ("1", LUT.FAST),
        ("2", LUT.FAST_NO_REDS),
        ("3", LUT.DEFAULT),
    ],
)
def test_legacy_refresh_type_values_keep_their_meaning(
    legacy: str, expected: LUT
) -> None:
    """An explicit old value must still do what it used to."""
    assert _drawcustom(refresh_type=legacy)["refresh_type"] is expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("adaptive", LUT.DEFAULT),
        ("full", LUT.NO_REPEAT),
        ("fast", LUT.FAST),
        ("fast_no_red", LUT.FAST_NO_REDS),
    ],
)
def test_refresh_type_names(name: str, expected: LUT) -> None:
    """The new names are self-describing."""
    assert _drawcustom(refresh_type=name)["refresh_type"] is expected


def test_refresh_type_rejects_nonsense() -> None:
    """An unrecognised value fails validation rather than silently defaulting."""
    with pytest.raises(vol.Invalid):
        _drawcustom(refresh_type="turbo")


# ---------------------------------------------------------------------------
# dither
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("0", DitherMode.NONE),
        ("1", DitherMode.BURKES),
        ("2", DitherMode.ORDERED),
        (2, DitherMode.ORDERED),
    ],
)
def test_legacy_dither_values(legacy: object, expected: DitherMode) -> None:
    """The old numbers named the Access Point's three options."""
    assert _drawcustom(dither=legacy)["dither"] is expected


def test_dither_accepts_every_library_mode() -> None:
    """Dithering happens here now, so the full algorithm set is available."""
    for mode in DitherMode:
        assert _drawcustom(dither=mode.name.lower())["dither"] is mode


def test_dither_rejects_nonsense() -> None:
    """An unknown algorithm fails rather than silently falling back."""
    with pytest.raises(vol.Invalid):
        _drawcustom(dither="sparkly")


# ---------------------------------------------------------------------------
# Other legacy call shapes
# ---------------------------------------------------------------------------


def test_hyphenated_dry_run_is_accepted() -> None:
    """The pre-4.0 action spelled it with a hyphen."""
    assert _drawcustom(**{"dry-run": True})["dry-run"] is True


def test_obsolete_keys_are_dropped_not_rejected() -> None:
    """A call carrying keys that no longer apply must still work."""
    validated = _drawcustom(preload_type=1, preload_lut=2, some_future_key="x")
    assert "preload_type" not in validated
    assert validated["payload"] == PAYLOAD


def test_ttl_keeps_its_old_default() -> None:
    """Existing automations relied on the 60 second default."""
    assert _drawcustom()["ttl"] == 60


def test_payload_is_required() -> None:
    """There is nothing to draw without one."""
    with pytest.raises(vol.Invalid):
        SCHEMA_DRAWCUSTOM({"background": "white"})


# ---------------------------------------------------------------------------
# Colour scheme
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("colors", "expected"),
    [
        (["white", "black"], ColorScheme.MONO),
        (["white", "black", "red"], ColorScheme.BWR),
        (["white", "black", "yellow"], ColorScheme.BWY),
        (["white", "black", "red", "yellow"], ColorScheme.BWRY),
    ],
)
def test_color_scheme_from_the_tag_type(
    colors: list[str], expected: ColorScheme
) -> None:
    """Dithering targets the palette the tag can actually render."""
    tag_type = TagType.from_dict(
        0x01,
        {
            "width": 296,
            "height": 128,
            "colortable": {name: [0, 0, 0] for name in colors},
        },
    )
    assert _color_scheme(tag_type) is expected
