"""How tags and the Access Point's display hang off the Access Point."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import DOMAIN

from .conftest import TAG_MAC, make_tag

# The tag MAC the test Access Point (aa:bb:cc:dd:ee:ff) gives its own display.
AP_DISPLAY_MAC = "0000FFEEDDCCBBAA"


def _ap_display() -> object:
    return make_tag(AP_DISPLAY_MAC, hw_type=0xE0, alias="Screen")


def _identifier(entry: MockConfigEntry, suffix: str) -> tuple[str, str]:
    return (DOMAIN, f"{entry.entry_id}_{suffix}")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_display_is_part_of_the_access_point(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The display is a child of the Access Point; tags are reached through it."""
    mock_client.set_tags(make_tag(TAG_MAC), _ap_display())
    ap_config_entry.add_to_hass(hass)
    await _setup(hass, ap_config_entry)

    registry = dr.async_get(hass)
    entry_id = ap_config_entry.entry_id
    ap = registry.async_get_device_by_identifier(
        _identifier(ap_config_entry, "ap"), entry_id
    )
    display = registry.async_get_child_device_by_identifier(
        _identifier(ap_config_entry, AP_DISPLAY_MAC), entry_id
    )
    tag = registry.async_get_device_by_identifier(
        _identifier(ap_config_entry, TAG_MAC), entry_id
    )
    assert ap is not None
    assert display is not None
    assert tag is not None

    assert display.parent_device_id == ap.id
    # Named after the part it is, not the alias the Access Point reports.
    assert display.name == "Display"
    assert tag.via_device_id == ap.id


async def test_display_from_an_earlier_version_becomes_a_child_in_place(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The display's device keeps its id, so automations using it still work."""
    mock_client.set_tags(_ap_display())
    ap_config_entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    ap = registry.async_get_or_create(
        config_entry_id=ap_config_entry.entry_id,
        identifiers={_identifier(ap_config_entry, "ap")},
    )
    old = registry.async_get_or_create(
        config_entry_id=ap_config_entry.entry_id,
        identifiers={_identifier(ap_config_entry, AP_DISPLAY_MAC)},
        name=AP_DISPLAY_MAC,
        model="TFT 320x172",
        via_device_id=ap.id,
    )
    # Those were registered by an earlier run, as after upgrading and
    # restarting; within one run Home Assistant refuses the conversion.
    registry.async_config_entry_unloaded(ap_config_entry.entry_id)

    await _setup(hass, ap_config_entry)

    display = registry.async_get_child_device_by_identifier(
        _identifier(ap_config_entry, AP_DISPLAY_MAC), ap_config_entry.entry_id
    )
    assert display is not None
    assert display.id == old.id
    assert display.parent_device_id == ap.id


async def test_reboot_ap_reboots_once_with_its_display_targeted_too(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Targeting the Access Point also targets its display's entities."""
    mock_client.set_tags(make_tag(TAG_MAC), _ap_display())
    ap_config_entry.add_to_hass(hass)
    await _setup(hass, ap_config_entry)
    ap = dr.async_get(hass).async_get_device_by_identifier(
        _identifier(ap_config_entry, "ap"), ap_config_entry.entry_id
    )
    assert ap is not None

    await hass.services.async_call(
        DOMAIN, "reboot_ap", {"device_id": [ap.id]}, blocking=True
    )

    mock_client.reboot_ap.assert_awaited_once()
