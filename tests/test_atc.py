"""Setup and state for tags running ATC firmware."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from py_atc_ble_oepl import MANUFACTURER_ID
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import CONF_MAC_ADDRESS, DOMAIN

from .conftest import ATC_ADDRESS, atc_service_info


async def test_setup_interrogates_the_tag(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """Panel geometry is read once at setup and kept in runtime data.

    It cannot change for a tag, so every draw reads it from there rather than
    paying for a Bluetooth connection.
    """
    atc_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()

    assert atc_config_entry.state is ConfigEntryState.LOADED
    caps = atc_config_entry.runtime_data.capabilities
    assert (caps.width, caps.height, caps.color_scheme) == (152, 200, 2)
    mock_atc_tag.interrogate.assert_awaited_once()


async def test_unreachable_tag_leaves_the_entry_not_ready(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag_absent: None
) -> None:
    """A tag nobody can reach has nothing usable to offer.

    These tags sleep only briefly between advertisements, so retrying costs
    seconds rather than leaving an entry stuck.
    """
    atc_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()

    assert atc_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_advertisement_populates_state(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """State comes from advertisements, which cost the tag nothing."""
    atc_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = atc_config_entry.runtime_data.coordinator
    coordinator._async_handle_bluetooth_event(
        atc_service_info(), BluetoothChange.ADVERTISEMENT
    )
    await hass.async_block_till_done()

    advertisement = coordinator.data.advertisement
    assert advertisement.battery_mv == 2828
    assert advertisement.temperature == -8
    assert advertisement.hw_type == 0x11


async def test_malformed_advertisement_is_ignored(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """A truncated advertisement must not take the entry down."""
    atc_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = atc_config_entry.runtime_data.coordinator
    info = atc_service_info()
    info.manufacturer_data[MANUFACTURER_ID] = b"\x02\x00"  # too short for version 2

    coordinator._async_handle_bluetooth_event(info, BluetoothChange.ADVERTISEMENT)
    await hass.async_block_till_done()

    assert coordinator.data is None
    assert atc_config_entry.state is ConfigEntryState.LOADED


async def test_unload(hass: HomeAssistant, atc_config_entry: MockConfigEntry) -> None:
    """An ATC entry unloads cleanly."""
    atc_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(atc_config_entry.entry_id)
    await hass.async_block_till_done()
    assert atc_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_ap_and_atc_entries_coexist(
    hass: HomeAssistant,
    ap_config_entry: MockConfigEntry,
    atc_config_entry: MockConfigEntry,
    mock_client,
    mock_atc_tag: MagicMock,
) -> None:
    """The two transports are separate entry shapes under one domain."""
    ap_config_entry.add_to_hass(hass)
    atc_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    assert ap_config_entry.state is ConfigEntryState.LOADED
    assert atc_config_entry.state is ConfigEntryState.LOADED
    assert atc_config_entry.data[CONF_MAC_ADDRESS] == ATC_ADDRESS


async def test_image_entity_is_empty_until_something_is_drawn(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """An ATC tag cannot be read back, so there is nothing to show at first.

    An Access Point serves the tag's current framebuffer; Bluetooth offers no
    equivalent, so the only picture available is one we drew ourselves.
    """
    atc_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "image", DOMAIN, f"{atc_config_entry.entry_id}_content"
    )
    assert entity_id is not None
    assert atc_config_entry.runtime_data.coordinator.rendered is None


async def test_image_entity_shows_what_was_drawn(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """Once an image is drawn it becomes the entity's content."""
    atc_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = atc_config_entry.runtime_data.coordinator
    coordinator.async_set_rendered(b"\x89PNG-pretend")
    await hass.async_block_till_done()

    assert coordinator.rendered == b"\x89PNG-pretend"
