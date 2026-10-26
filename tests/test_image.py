"""The image entities showing what is on each tag."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.open_epaper_link.const import DOMAIN

from .conftest import TAG_MAC, atc_service_info, make_tag


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _tag_image(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "image", DOMAIN, f"{entry.entry_id}_{TAG_MAC}_content"
    )
    assert entity_id is not None
    return entity_id


def _atc_image(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "image", DOMAIN, f"{entry.entry_id}_content"
    )
    assert entity_id is not None
    return entity_id


async def test_tag_check_ins_do_not_touch_the_image(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A tag checking in with the same picture leaves the state alone.

    The state is the image's timestamp, and the Access Point pushes updates
    every few seconds, so moving it on each one wrote a recorder row every few
    seconds for every tag, whether or not anyone ever looked at the image.
    """
    await _setup(hass, ap_config_entry)
    entity_id = _tag_image(hass, ap_config_entry)
    before = hass.states.get(entity_id).state

    coordinator = ap_config_entry.runtime_data
    for _ in range(3):
        coordinator._handle_tag_update(make_tag(TAG_MAC))
        await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == before


async def test_a_new_picture_moves_the_timestamp(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A different hash means the tag shows something new."""
    await _setup(hass, ap_config_entry)
    entity_id = _tag_image(hass, ap_config_entry)
    before = hass.states.get(entity_id).state

    ap_config_entry.runtime_data._handle_tag_update(make_tag(TAG_MAC, hash="def"))
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state != before


async def test_a_preview_moves_the_timestamp(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A rendered preview is shown before the tag reports a new hash."""
    await _setup(hass, ap_config_entry)
    entity_id = _tag_image(hass, ap_config_entry)
    before = hass.states.get(entity_id).state

    ap_config_entry.runtime_data.async_set_preview(TAG_MAC, b"\x89PNG-pretend")
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state != before


async def test_advertisements_do_not_touch_a_drawn_atc_image(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """Once something is drawn, advertisements leave its timestamp alone."""
    await _setup(hass, atc_config_entry)
    entity_id = _atc_image(hass, atc_config_entry)
    coordinator = atc_config_entry.runtime_data.coordinator
    coordinator.async_set_rendered(b"\x89PNG-pretend")
    await hass.async_block_till_done()
    drawn = hass.states.get(entity_id).state

    for _ in range(3):
        coordinator._async_handle_bluetooth_event(
            atc_service_info(), BluetoothChange.ADVERTISEMENT
        )
        await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == drawn


async def test_tag_image_is_served_as_png(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    ap_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """The entity encodes PNG, so it must not be labelled JPEG."""
    await _setup(hass, ap_config_entry)
    ap_config_entry.runtime_data.async_set_preview(TAG_MAC, b"\x89PNG-pretend")
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(f"/api/image_proxy/{_tag_image(hass, ap_config_entry)}")

    assert response.status == 200
    assert response.content_type == "image/png"


async def test_atc_image_is_served_as_png(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
) -> None:
    """What is drawn on an ATC tag is kept as PNG too."""
    await _setup(hass, atc_config_entry)
    atc_config_entry.runtime_data.coordinator.async_set_rendered(b"\x89PNG-pretend")
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(
        f"/api/image_proxy/{_atc_image(hass, atc_config_entry)}"
    )

    assert response.status == 200
    assert response.content_type == "image/png"
