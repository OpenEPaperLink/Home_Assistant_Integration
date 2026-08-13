"""Selects must describe exactly the values the Access Point accepts."""

from __future__ import annotations

import pytest

from custom_components.open_epaper_link.select import (
    _KEYS,
    AP_SELECTS,
    LIBRARY_VALUES,
)


@pytest.mark.parametrize("setting", sorted(_KEYS))
def test_keys_cover_the_library(setting: str) -> None:
    """Every value py-oepl knows about must have an option name here.

    py-oepl owns which values exist, taken from the firmware; this module
    owns what each is called, because the option is the entity state and
    deriving it from a display label would rewrite recorder history whenever
    the label was reworded. A value added upstream fails here until named.
    """
    assert set(_KEYS[setting]) == set(LIBRARY_VALUES[setting])


@pytest.mark.parametrize("setting", sorted(_KEYS))
def test_option_names_are_unique(setting: str) -> None:
    """Two values sharing a name would make the state ambiguous."""
    names = list(_KEYS[setting].values())
    assert len(names) == len(set(names))


def test_led_and_tft_brightness_differ() -> None:
    """They look alike but use different steps; conflating them was a bug.

    A TFT set to 20 resolved to nothing when both used the LED steps.
    """
    led = dict(LIBRARY_VALUES["led"])
    tft = dict(LIBRARY_VALUES["tft"])
    assert led != tft
    assert 15 in led and 15 not in tft
    assert 20 in tft and 20 not in led


def test_lock_has_three_modes() -> None:
    """Learning is a distinct mode, not a shade of locked."""
    assert len(LIBRARY_VALUES["lock"]) == 3
    assert set(_KEYS["lock"].values()) == {"open", "locked", "learning"}


def test_every_select_has_choices() -> None:
    """A select with no options cannot be set at all."""
    for description in AP_SELECTS:
        assert description.choices, f"{description.key} has no choices"


def test_battery_sentinel_is_not_a_flat_battery() -> None:
    """A tag with no usable reading must not report 0%.

    The firmware and the Access Point's web interface both exclude 1337 mV
    wherever they touch battery values.
    """
    from custom_components.open_epaper_link.sensor import _battery_percentage

    from .conftest import make_tag

    assert _battery_percentage(make_tag("AA", batteryMv=1337)) is None
    assert _battery_percentage(make_tag("AA", batteryMv=0)) is None
    assert _battery_percentage(make_tag("AA", batteryMv=2600)) == 50.0
