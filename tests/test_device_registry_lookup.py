"""Device registry lookups must not use APIs Home Assistant has deprecated.

Home Assistant logs "Detected that custom integration 'open_epaper_link' ..."
for ``device_registry.async_get_device`` and for iterating
``device_registry.devices`` (issue #352). These tests exercise the lookups
against a real device registry and fail if that warning is logged.
"""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import DOMAIN
from custom_components.open_epaper_link.util import (
    get_device_by_identifier,
    is_ble_device,
)

DEPRECATION = "Detected that custom integration 'open_epaper_link'"


def _add_device(hass: HomeAssistant, identifier: str) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, identifier)},
        name=identifier,
    )
    return entry


async def test_get_device_by_identifier_finds_device_of_the_given_entry(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    entry = _add_device(hass, "00000A2818C93D1B")
    registry = dr.async_get(hass)

    caplog.clear()
    device = get_device_by_identifier(
        registry, entry.entry_id, (DOMAIN, "00000A2818C93D1B")
    )

    assert device is not None
    assert (DOMAIN, "00000A2818C93D1B") in device.identifiers
    assert get_device_by_identifier(registry, entry.entry_id, (DOMAIN, "missing")) is None
    assert DEPRECATION not in caplog.text


async def test_get_device_by_identifier_ignores_other_entries(
    hass: HomeAssistant,
) -> None:
    _add_device(hass, "00000A2818C93D1B")
    other = MockConfigEntry(domain=DOMAIN, data={})
    other.add_to_hass(hass)

    assert (
        get_device_by_identifier(
            dr.async_get(hass), other.entry_id, (DOMAIN, "00000A2818C93D1B")
        )
        is None
    )


async def test_is_ble_device_without_deprecated_registry_access(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    _add_device(hass, "ble_AABBCCDDEEFF")
    _add_device(hass, "00000A2818C93D1B")

    caplog.clear()
    assert is_ble_device(hass, f"{DOMAIN}.aabbccddeeff") is True
    assert is_ble_device(hass, f"{DOMAIN}.00000a2818c93d1b") is False
    assert is_ble_device(hass, f"{DOMAIN}.unknown") is False
    assert DEPRECATION not in caplog.text
