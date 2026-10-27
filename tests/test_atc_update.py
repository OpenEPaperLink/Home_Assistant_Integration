"""Firmware updates for tags running ATC firmware, over Bluetooth."""

from __future__ import annotations

import asyncio
import struct
import zlib
from unittest.mock import MagicMock

import pytest
from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.components.update import (
    ATTR_IN_PROGRESS,
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_UPDATE_PERCENTAGE,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from py_atc_ble_oepl import FIRMWARE_URL, MANUFACTURER_ID, ATCError, ATCFirmware
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.open_epaper_link.const import DOMAIN

from .conftest import atc_service_info

# The code ATC firmware loads its version from, as atc1441's 2026 builds have
# it, with the version left out.
_VERSION_SITE = "5b4b1bf213032321{:02x}a363210d90"


def _image(version: int) -> bytes:
    """An ATC firmware image carrying *version*, built as Telink's check_fw does."""
    body = bytearray(1024)
    body[8:12] = b"KNLT"
    site = bytes.fromhex(_VERSION_SITE.format(version))
    body[600 : 600 + len(site)] = site
    body += b"\xff" * (-len(body) % 16)
    struct.pack_into("<I", body, 24, len(body) + 4)
    return bytes(body) + struct.pack("<I", zlib.crc32(bytes(body)) ^ 0xFFFFFFFF)


def _advertising(fw_version: int):
    """An advertisement from the tag reporting *fw_version*."""
    info = atc_service_info()
    info.manufacturer_data[MANUFACTURER_ID] = bytes(
        [2, 0x54, 0x00, fw_version & 0xFF, fw_version >> 8, 0, 0, 0x0C, 0x0B, 0x15, 0]
    )
    return info


async def _setup(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    published: int | None = 0x7D,
    installed: int = 0x6B,
) -> str:
    if published is None:
        aioclient_mock.get(FIRMWARE_URL, status=404)
    else:
        aioclient_mock.get(FIRMWARE_URL, content=_image(published))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    _advertise(entry, installed)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "update", DOMAIN, f"{entry.entry_id}_firmware"
    )
    assert entity_id is not None
    return entity_id


def _advertise(entry: MockConfigEntry, fw_version: int) -> None:
    entry.runtime_data.coordinator._async_handle_bluetooth_event(
        _advertising(fw_version), BluetoothChange.ADVERTISEMENT
    )


def test_the_test_image_is_one_a_tag_would_install() -> None:
    assert ATCFirmware.from_bytes(_image(0x7D)).version == 0x7D


async def test_a_newer_published_firmware_is_offered(
    hass: HomeAssistant,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Seen on real tags: 0x6B against the published 0x7D."""
    entity_id = await _setup(hass, atc_config_entry, aioclient_mock)

    state = hass.states.get(entity_id)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_INSTALLED_VERSION] == "006B"
    assert state.attributes[ATTR_LATEST_VERSION] == "007D"
    assert state.attributes["title"] == "ATC_BLE_OEPL"


async def test_a_current_tag_is_up_to_date(
    hass: HomeAssistant,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    entity_id = await _setup(hass, atc_config_entry, aioclient_mock, installed=0x7D)

    assert hass.states.get(entity_id).state == STATE_OFF


async def test_an_unreachable_image_leaves_the_latest_version_unknown(
    hass: HomeAssistant,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The tag still sets up; only the check failed."""
    entity_id = await _setup(hass, atc_config_entry, aioclient_mock, published=None)

    assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_install_sends_it_and_waits_for_the_new_version(
    hass: HomeAssistant,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Done only once the tag advertises the version it was sent."""
    entity_id = await _setup(hass, atc_config_entry, aioclient_mock)
    seen: list[int | None] = []

    async def update_firmware(firmware, progress_callback) -> None:
        assert firmware.version == 0x7D
        progress_callback(58594, 117188)
        seen.append(hass.states.get(entity_id).attributes[ATTR_UPDATE_PERCENTAGE])
        # The tag restarts into it shortly after storing it.
        asyncio.get_running_loop().call_later(0.01, _advertise, atc_config_entry, 0x7D)

    mock_atc_tag.update_firmware.side_effect = update_firmware
    await hass.services.async_call(
        "update", "install", {"entity_id": entity_id}, blocking=True
    )

    assert seen == [50]
    mock_atc_tag.update_firmware.assert_awaited_once()
    state = hass.states.get(entity_id)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_INSTALLED_VERSION] == "007D"
    assert not state.attributes[ATTR_IN_PROGRESS]


async def test_a_tag_that_keeps_its_old_firmware_is_a_failure(
    hass: HomeAssistant,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It stores the image, then refuses it and restarts on the old version."""
    monkeypatch.setattr(
        "custom_components.open_epaper_link.update._ATC_RESTART_TIMEOUT", 0.01
    )
    entity_id = await _setup(hass, atc_config_entry, aioclient_mock)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "update", "install", {"entity_id": entity_id}, blocking=True
        )
    assert not hass.states.get(entity_id).attributes[ATTR_IN_PROGRESS]


async def test_a_failed_transfer_says_why(
    hass: HomeAssistant,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    entity_id = await _setup(hass, atc_config_entry, aioclient_mock)
    mock_atc_tag.update_firmware.side_effect = ATCError("Tag stopped answering")

    with pytest.raises(HomeAssistantError, match="stopped answering"):
        await hass.services.async_call(
            "update", "install", {"entity_id": entity_id}, blocking=True
        )
