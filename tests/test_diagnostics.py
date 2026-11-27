"""Diagnostics downloads for Access Points and ATC tags."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.core import HomeAssistant
from oepl import APStatus
from py_atc_ble_oepl import DeviceConfig
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.open_epaper_link.const import OPT_BLACKLISTED_TAGS

from .conftest import (
    AP_HOST,
    AP_MAC,
    ATC_ADDRESS,
    TAG_MAC,
    atc_service_info,
    make_tag,
)

OTHER_TAG = "00000335042F3E11"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_access_point(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    ap_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """An Access Point's diagnostics describe it and each tag it shows."""
    mock_client.set_tags(
        make_tag(TAG_MAC, alias="Fridge", modecfgjson='{"url": "http://secret"}'),
        make_tag(OTHER_TAG, ap_ip="192.0.2.99"),
    )
    ap_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        ap_config_entry, options={OPT_BLACKLISTED_TAGS: [OTHER_TAG]}
    )
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = ap_config_entry.runtime_data
    coordinator._handle_ap_status(
        APStatus.from_dict({"heap": 1234, "wifissid": "HomeNet", "rssi": -50})
    )

    diag = await get_diagnostics_for_config_entry(hass, hass_client, ap_config_entry)

    entry = diag["entry"]
    assert entry["title"] == "Kitchen AP"
    assert entry["data"]["host"] == "**REDACTED**"
    assert entry["data"]["ap_mac"] == "**REDACTED**EEFF"
    assert entry["options"][OPT_BLACKLISTED_TAGS] == ["**REDACTED**3E11"]

    device = diag["device"]
    assert device["type"] == "access_point"
    assert device["online"] is True
    assert device["info"]["env"] == "ESP32_S3"
    assert device["config"]["alias"] == "Kitchen AP"
    assert device["status"]["heap"] == 1234
    assert device["status"]["wifi_ssid"] == "**REDACTED**"
    assert device["tags_reported"] == 2
    # The hidden tag is reported by the Access Point but not shown.
    assert device["tags_shown"] == 1
    tag = device["tags"]["**REDACTED**3E10"]
    assert tag["alias"] == "Fridge"
    assert tag["modecfgjson"] == "**REDACTED**"
    assert tag["tag_type"] == 'M2 2.9"'
    assert tag["is_ap_display"] is False
    assert "raw" not in tag

    dumped = json.dumps(diag)
    for secret in (AP_HOST, AP_MAC, TAG_MAC, OTHER_TAG, "HomeNet", "secret"):
        assert secret.lower() not in dumped.lower()


async def test_tag_named_after_its_mac(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    ap_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A tag whose alias is its MAC does not give the MAC away through it."""
    mock_client.set_tags(make_tag(TAG_MAC, alias=TAG_MAC))
    await _setup(hass, ap_config_entry)

    diag = await get_diagnostics_for_config_entry(hass, hass_client, ap_config_entry)

    assert diag["device"]["tags"]["**REDACTED**3E10"]["alias"] == "**REDACTED**3E10"
    assert TAG_MAC not in json.dumps(diag)


async def test_access_point_before_any_status(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    ap_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """An Access Point that has not sent a status yet still downloads."""
    await _setup(hass, ap_config_entry)

    diag = await get_diagnostics_for_config_entry(hass, hass_client, ap_config_entry)

    assert diag["device"]["status"] is None


async def test_atc_tag(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
) -> None:
    """An ATC tag's diagnostics carry its geometry, config and advertisement."""
    mock_atc_tag.device_config = DeviceConfig(
        screen_type=5,
        hw_type=0x67,
        screen_functions=0,
        wh_inverted_ble=False,
        wh_inverted=False,
        screen_h=200,
        screen_w=152,
        screen_h_offset=0,
        screen_w_offset=0,
        screen_colors=3,
        black_invert=False,
        second_color_invert=False,
        epd_enabled=True,
        led_enabled=False,
        nfc_enabled=False,
        flash_enabled=False,
        adc_pinout=0,
        uart_pinout=0,
    )
    await _setup(hass, atc_config_entry)
    atc_config_entry.runtime_data.coordinator._async_handle_bluetooth_event(
        atc_service_info(), BluetoothChange.ADVERTISEMENT
    )

    diag = await get_diagnostics_for_config_entry(hass, hass_client, atc_config_entry)

    assert diag["entry"]["data"]["mac_address"] == "**REDACTED**EE01"
    device = diag["device"]
    assert device["type"] == "atc"
    assert device["capabilities"] == {"width": 152, "height": 200, "color_scheme": 2}
    assert device["device_config"]["screen_type"] == 5
    assert device["advertisement"]["battery_mv"] == 2828
    assert device["has_rendered_image"] is False
    assert device["upload_in_progress"] is False
    assert ATC_ADDRESS.lower() not in json.dumps(diag).lower()


async def test_atc_tag_before_any_advertisement(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    atc_config_entry: MockConfigEntry,
    mock_atc_tag: MagicMock,
) -> None:
    """A tag that has not advertised since setup still downloads."""
    await _setup(hass, atc_config_entry)

    diag = await get_diagnostics_for_config_entry(hass, hass_client, atc_config_entry)

    assert diag["device"]["advertisement"] is None
    assert diag["device"]["device_config"] is None
