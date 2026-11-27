"""Tag type definitions are fetched whenever one is missing.

The pre-4.0 refresh_tag_types action existed because a definition missing at
setup stayed missing until it was called. Nothing should need it now.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from oepl import OEPLError, TagType
from pytest_homeassistant.common import MockConfigEntry

from custom_components.open_epaper_link.const import DOMAIN

from .conftest import TAG_MAC, make_tag, make_tag_type

NEW_MAC = "00000335042F3E99"
NEW_TYPE = 0x42


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _draw(hass: HomeAssistant, entry: MockConfigEntry, mac: str) -> None:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_{mac}"), entry.entry_id
    )
    assert device is not None
    await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {
            "device_id": [device.id],
            "background": "white",
            "payload": [{"type": "text", "value": "Hi", "x": 0, "y": 0}],
        },
        blocking=True,
    )


async def test_a_tag_of_a_new_type_waits_for_its_definition(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A tag first seen after setup is not let in without its tag type.

    Its device is built from the definition, so letting it in first would
    leave the device without a hardware name or maker.
    """
    await _setup(hass, ap_config_entry)
    coordinator = ap_config_entry.runtime_data
    answer = asyncio.Event()

    async def get_tag_type(hw_type: int) -> TagType:
        await answer.wait()
        return make_tag_type(name='TLSR BWR 2.13"')

    mock_client.get_tag_type.reset_mock()
    mock_client.get_tag_type.side_effect = get_tag_type

    coordinator._handle_tag_update(make_tag(NEW_MAC, hw_type=NEW_TYPE))
    # Updates while the definition is on its way are kept, not refetched.
    coordinator._handle_tag_update(make_tag(NEW_MAC, hw_type=NEW_TYPE, LQI=99))
    await hass.async_block_till_done()
    assert NEW_MAC not in coordinator.data

    answer.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    mock_client.get_tag_type.assert_awaited_once_with(NEW_TYPE)
    assert coordinator.data[NEW_MAC].lqi == 99
    tag_type = coordinator.tag_type(NEW_MAC)
    assert tag_type is not None
    assert tag_type.name == 'TLSR BWR 2.13"'


async def test_a_tag_of_a_known_type_is_let_in_at_once(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """No fetch, and no wait, for a type already in hand."""
    await _setup(hass, ap_config_entry)
    coordinator = ap_config_entry.runtime_data
    mock_client.get_tag_type.reset_mock()

    coordinator._handle_tag_update(make_tag(NEW_MAC))

    assert NEW_MAC in coordinator.data
    mock_client.get_tag_type.assert_not_awaited()


async def test_a_tag_is_let_in_even_if_its_definition_cannot_be_fetched(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """It still reports battery, signal and the rest without one."""
    await _setup(hass, ap_config_entry)
    coordinator = ap_config_entry.runtime_data
    mock_client.get_tag_type.side_effect = OEPLError("timed out")

    coordinator._handle_tag_update(make_tag(NEW_MAC, hw_type=NEW_TYPE))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert NEW_MAC in coordinator.data
    assert coordinator.tag_type(NEW_MAC) is None


async def test_drawing_asks_again_after_a_failed_fetch(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """An Access Point slow to answer at setup does not break drawing."""
    mock_client.get_tag_type.side_effect = OEPLError("timed out")
    await _setup(hass, ap_config_entry)
    assert ap_config_entry.runtime_data.tag_type(TAG_MAC) is None

    mock_client.get_tag_type.side_effect = None
    await _draw(hass, ap_config_entry, TAG_MAC)

    mock_client.upload_image.assert_awaited_once()


async def test_a_missing_definition_is_not_remembered(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The AP can obtain a definition later, and that is picked up."""
    mock_client.get_tag_type.return_value = None
    await _setup(hass, ap_config_entry)

    mock_client.get_tag_type.return_value = make_tag_type()
    await _draw(hass, ap_config_entry, TAG_MAC)

    mock_client.upload_image.assert_awaited_once()


async def test_refresh_tag_types_does_nothing_but_say_so(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Kept only so that pre-4.0 automations calling it do not fail."""
    await _setup(hass, ap_config_entry)
    mock_client.get_tag_type.reset_mock()

    await hass.services.async_call(
        DOMAIN,
        "refresh_tag_types",
        {"device_id": []},
        blocking=True,
    )

    mock_client.get_tag_type.assert_not_awaited()
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, "deprecated_action_refresh_tag_types"
    )
    assert issue is not None
    assert issue.translation_key == "deprecated_refresh_tag_types"
