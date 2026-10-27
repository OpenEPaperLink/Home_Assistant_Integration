"""How tags and the Access Point's display hang off the Access Point."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
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


# What only a tag on its own battery, radio and sleep cycle has, by platform.
TAG_ONLY = (
    ("sensor", "battery_percentage"),
    ("sensor", "battery_voltage"),
    ("sensor", "temperature"),
    ("sensor", "lqi"),
    ("sensor", "rssi"),
    ("sensor", "next_checkin"),
    ("sensor", "wakeup_reason"),
    ("button", "reboot_tag"),
    ("button", "scan_channels"),
    ("button", "deep_sleep"),
    ("event", "gpio"),
    ("text", "tag_alias"),
)


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, mac: str, key: str
) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{mac}_{key}"
    )


async def test_display_gets_nothing_only_a_tag_has(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The display has no battery, radio or sleep cycle, so nothing about them."""
    mock_client.set_tags(make_tag(TAG_MAC), _ap_display())
    ap_config_entry.add_to_hass(hass)
    await _setup(hass, ap_config_entry)

    for platform, key in TAG_ONLY:
        entity = (platform, key)
        assert (
            _entity_id(hass, ap_config_entry, platform, AP_DISPLAY_MAC, key) is None
        ), entity
        assert _entity_id(hass, ap_config_entry, platform, TAG_MAC, key), entity

    # What the Access Point says about the display still applies.
    for platform, key in (
        ("sensor", "last_seen"),
        ("button", "force_refresh"),
        ("image", "content"),
    ):
        assert _entity_id(hass, ap_config_entry, platform, AP_DISPLAY_MAC, key)


async def test_display_entities_from_earlier_versions_are_removed(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Entities created before the display was recognised do not linger."""
    mock_client.set_tags(make_tag(TAG_MAC), _ap_display())
    ap_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for platform, key in TAG_ONLY:
        registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{ap_config_entry.entry_id}_{AP_DISPLAY_MAC}_{key}",
            config_entry=ap_config_entry,
        )

    await _setup(hass, ap_config_entry)

    for platform, key in TAG_ONLY:
        entity = (platform, key)
        assert (
            _entity_id(hass, ap_config_entry, platform, AP_DISPLAY_MAC, key) is None
        ), entity


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


async def test_tag_devices_carry_their_firmware_and_hardware_type(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """As the tag's firmware images and the AP's tag type files name them.

    The 3.0 integration wrote the firmware as "0x41" for version 41, which
    is 0x29, and put the panel resolution in the hardware version.
    """
    mock_client.set_tags(make_tag(TAG_MAC, ver=41, hw_type=0x01))
    ap_config_entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=ap_config_entry.entry_id,
        identifiers={_identifier(ap_config_entry, TAG_MAC)},
        sw_version="0x41",
        hw_version="296x128",
    )
    registry.async_config_entry_unloaded(ap_config_entry.entry_id)
    await _setup(hass, ap_config_entry)

    def device() -> dr.DeviceEntry:
        found = registry.async_get_device_by_identifier(
            _identifier(ap_config_entry, TAG_MAC), ap_config_entry.entry_id
        )
        assert found is not None
        return found

    assert (device().sw_version, device().hw_version) == ("0029", "01")

    # An update reports the new version, which the device follows.
    ap_config_entry.runtime_data._handle_tag_update(make_tag(TAG_MAC, ver=0x2B))
    await hass.async_block_till_done()
    assert device().sw_version == "002B"
