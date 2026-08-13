"""Action schemas, with the pre-4.0 call shapes still accepted.

drawcustom payloads are large hand-written YAML in people's automations, so
old calls must keep working. These pin the coercion.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import voluptuous as vol
import yaml
from epaper_dithering import ColorScheme, DitherMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from oepl import LUT, LEDPattern, TagType

from custom_components.open_epaper_link.const import DOMAIN
from custom_components.open_epaper_link.services import (
    SCHEMA_DRAWCUSTOM,
    SCHEMA_SETLED,
    _color_scheme,
    _led_pattern,
    async_register_services,
)

from .conftest import TAG_MAC

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


# ---------------------------------------------------------------------------
# setled, which has three colour groups
# ---------------------------------------------------------------------------


def _setled(**overrides: object) -> dict:
    """Validate a setled call, as Home Assistant would."""
    return SCHEMA_SETLED(dict(overrides))


def test_all_three_led_groups_survive() -> None:
    """A three-colour call must not lose groups two and three.

    They were silently dropped at one point, which is worse than failing.
    """
    pattern = _led_pattern(
        _setled(
            color1=[255, 0, 0],
            color2=[0, 255, 0],
            color3=[0, 0, 255],
        )
    )
    assert len(pattern.segments) == 3
    assert [(s.color.r, s.color.g, s.color.b) for s in pattern.segments] == [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
    ]


def test_a_group_with_no_flashes_is_skipped() -> None:
    """That is how the pre-4.0 action documented turning a group off."""
    pattern = _led_pattern(_setled(flash_count2=0, flash_count3=0))
    assert len(pattern.segments) == 1


def test_setled_off_mode() -> None:
    """Off stops the pattern rather than flashing anything."""
    assert _led_pattern(_setled(mode="off")).encode() == LEDPattern.off().encode()


def test_setled_rejects_an_empty_pattern() -> None:
    """Silently sending nothing would look like the action failed."""
    with pytest.raises(ServiceValidationError):
        _led_pattern(_setled(flash_count1=0, flash_count2=0, flash_count3=0))


def test_led_delays_are_carried_through() -> None:
    """Delay between groups is part of the pattern, not decoration."""
    pattern = _led_pattern(_setled(delay1=1.5))
    assert pattern.segments[0].delay == 1.5


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_every_declared_service_is_registered(hass: HomeAssistant) -> None:
    """services.yaml and the registered actions must not drift apart.

    They did: the file declared eight actions while only two were registered,
    so six of them appeared in the UI and failed when called.
    """
    async_register_services(hass)
    await hass.async_block_till_done()

    declared = yaml.safe_load(
        (Path("custom_components/open_epaper_link/services.yaml")).read_text()
    )
    registered = set(hass.services.async_services_for_domain(DOMAIN))
    assert set(declared) == registered


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------


async def test_targeting_a_tag_device(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Actions target tags as devices, which is how a tag is picked in the UI.

    Restricting the target to entities would make you choose one of a tag's
    sensors to redraw the whole display.
    """
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    assert device is not None

    await hass.services.async_call(
        DOMAIN, "clear_pending", {"device_id": [device.id]}, blocking=True
    )

    mock_client.send_tag_cmd.assert_awaited_once()
    assert mock_client.send_tag_cmd.await_args.args[0] == TAG_MAC


async def test_targeting_an_entity_resolves_to_its_tag(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Targeting an entity still works, and resolves to the tag behind it."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}_temperature"
    )

    await hass.services.async_call(
        DOMAIN, "force_refresh", {"entity_id": [entity_id]}, blocking=True
    )

    mock_client.send_tag_cmd.assert_awaited_once()
    assert mock_client.send_tag_cmd.await_args.args[0] == TAG_MAC


async def test_targeting_the_access_point_device(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Access Point actions target the Access Point's own device."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_ap")}
    )

    await hass.services.async_call(
        DOMAIN, "reboot_ap", {"device_id": [device.id]}, blocking=True
    )

    mock_client.reboot_ap.assert_awaited_once()


async def test_targeting_nothing_is_an_error(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """A call that resolves to no tags should say so, not silently do nothing."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "clear_pending", {"device_id": ["nonexistent"]}, blocking=True
        )
