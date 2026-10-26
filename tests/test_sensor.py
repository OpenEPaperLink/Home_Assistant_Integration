"""Sensors for tags, and which tags get which."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import DOMAIN

from .conftest import TAG_MAC, make_tag

# The tag MAC the test Access Point (aa:bb:cc:dd:ee:ff) gives its own display.
AP_DISPLAY_MAC = "0000FFEEDDCCBBAA"

READINGS = (
    "battery_percentage",
    "battery_voltage",
    "temperature",
    "lqi",
    "rssi",
)


def _ap_display() -> object:
    """The display as the Access Point reports it: zeros where readings go."""
    return make_tag(
        AP_DISPLAY_MAC,
        hw_type=0xE0,
        batteryMv=0,
        temperature=0,
        LQI=0,
        RSSI=-20,
    )


def _sensor(hass: HomeAssistant, entry: MockConfigEntry, mac: str, key: str):
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{mac}_{key}"
    )


async def test_ap_display_gets_no_readings(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The display has no battery or radio, so it gets no readings for them."""
    mock_client.set_tags(make_tag(TAG_MAC), _ap_display())
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    for key in READINGS:
        assert _sensor(hass, ap_config_entry, AP_DISPLAY_MAC, key) is None, key
        assert _sensor(hass, ap_config_entry, TAG_MAC, key) is not None, key

    # What the Access Point says about the display still applies.
    assert _sensor(hass, ap_config_entry, AP_DISPLAY_MAC, "last_seen") is not None


async def test_ap_display_readings_from_earlier_versions_are_removed(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Readings created before the display was recognised do not linger."""
    mock_client.set_tags(make_tag(TAG_MAC), _ap_display())
    ap_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for key in READINGS:
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{ap_config_entry.entry_id}_{AP_DISPLAY_MAC}_{key}",
            config_entry=ap_config_entry,
        )

    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    for key in READINGS:
        assert _sensor(hass, ap_config_entry, AP_DISPLAY_MAC, key) is None, key
