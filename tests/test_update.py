"""Firmware update entities for the Access Point and its radio."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.update import (
    ATTR_IN_PROGRESS,
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_RELEASE_URL,
    ATTR_UPDATE_PERCENTAGE,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from oepl import APInfo, OEPLConnectionError, OEPLUpdateError, Release, TagFirmware
from oepl.update import UpdateProgress, UpdateStage
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import TAG_MAC, make_tag
from .test_entity import AP_DISPLAY_MAC

FIRMWARE = "update.kitchen_ap_firmware"
RADIO = "update.kitchen_ap_radio_firmware"


def _release(tag: str = "3.00") -> Release:
    return Release.from_github(
        {
            "tag_name": tag,
            "published_at": "2026-10-21T21:31:24Z",
            "html_url": f"https://github.com/OpenEPaperLink/OpenEPaperLink/releases/tag/{tag}",
            "body": "What changed",
            "assets": [],
        }
    )


def _sysinfo(**overrides: object) -> APInfo:
    # As a real Access Point reports it, built shortly before release 3.00.
    data = {
        "alias": "Kitchen AP",
        "env": "ESP32_S3",
        "buildversion": "2.98",
        "buildtime": "1792000000",
        **overrides,
    }
    return APInfo.from_dict(data)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_newer_release_is_offered(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The release the Access Point's own page would offer is offered here."""
    mock_client.get_sysinfo.return_value = _sysinfo()
    mock_client.updates.latest_release.return_value = _release()
    await _setup(hass, ap_config_entry)

    state = hass.states.get(FIRMWARE)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_INSTALLED_VERSION] == "2.98"
    assert state.attributes[ATTR_LATEST_VERSION] == "3.00"
    assert state.attributes[ATTR_RELEASE_URL].endswith("/releases/tag/3.00")
    mock_client.updates.latest_release.assert_awaited_with(
        "ESP32_S3", "OpenEPaperLink/OpenEPaperLink"
    )


async def test_the_installed_release_is_no_update(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The Access Point reports 3.0 for the release tagged 3.00."""
    mock_client.get_sysinfo.return_value = _sysinfo(
        buildversion="3.0", buildtime="1792617637"
    )
    mock_client.updates.latest_release.return_value = _release("3.00")
    await _setup(hass, ap_config_entry)

    state = hass.states.get(FIRMWARE)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_LATEST_VERSION] == "3.0"


async def test_no_release_found_is_up_to_date(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A repository with no release for this build has nothing to offer."""
    mock_client.get_sysinfo.return_value = _sysinfo()
    await _setup(hass, ap_config_entry)

    assert hass.states.get(FIRMWARE).state == STATE_OFF


async def test_github_unreachable_leaves_the_latest_version_unknown(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The Access Point still sets up; only the release check failed."""
    mock_client.get_sysinfo.return_value = _sysinfo()
    mock_client.updates.latest_release.side_effect = OEPLConnectionError("offline")
    await _setup(hass, ap_config_entry)

    assert hass.states.get(FIRMWARE).state == STATE_UNKNOWN


async def test_install_shows_progress_across_the_stages(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Files, tag types and the flash fill one progress bar between them."""
    mock_client.get_sysinfo.return_value = _sysinfo()
    release = _release()
    mock_client.updates.latest_release.return_value = release
    await _setup(hass, ap_config_entry)
    seen: list[int | None] = []

    async def install(*_args: object, on_progress, **_kwargs: object) -> None:
        for stage, percent in (
            (UpdateStage.FILESYSTEM, 50),
            (UpdateStage.TAG_TYPES, 100),
            (UpdateStage.FIRMWARE, 50),
        ):
            on_progress(UpdateProgress(stage, percent))
            state = hass.states.get(FIRMWARE)
            assert state.attributes[ATTR_IN_PROGRESS]
            seen.append(state.attributes[ATTR_UPDATE_PERCENTAGE])

    mock_client.updates.install.side_effect = install
    await hass.services.async_call(
        "update", "install", {"entity_id": FIRMWARE}, blocking=True
    )

    assert seen == [20, 50, 75]
    mock_client.updates.install.assert_awaited_once()
    args, kwargs = mock_client.updates.install.call_args
    assert args == (release, "ESP32_S3")
    assert kwargs["repo"] == "OpenEPaperLink/OpenEPaperLink"
    assert not hass.states.get(FIRMWARE).attributes[ATTR_IN_PROGRESS]


async def test_a_failed_install_says_why(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """What the Access Point reported reaches the user."""
    mock_client.get_sysinfo.return_value = _sysinfo()
    mock_client.updates.latest_release.return_value = _release()
    mock_client.updates.install.side_effect = OEPLUpdateError("Failed to download")
    await _setup(hass, ap_config_entry)

    with pytest.raises(HomeAssistantError, match="Failed to download"):
        await hass.services.async_call(
            "update", "install", {"entity_id": FIRMWARE}, blocking=True
        )
    assert not hass.states.get(FIRMWARE).attributes[ATTR_IN_PROGRESS]


async def test_reconnecting_reads_the_new_firmware_version(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """An update reboots the Access Point into the version it installed."""
    mock_client.get_sysinfo.return_value = _sysinfo()
    mock_client.updates.latest_release.return_value = _release()
    await _setup(hass, ap_config_entry)
    (on_connection_change,), _ = mock_client.on_connection_change.call_args

    on_connection_change(False)
    mock_client.get_sysinfo.return_value = _sysinfo(
        buildversion="3.0", buildtime="1792617637"
    )
    on_connection_change(True)
    await hass.async_block_till_done()

    state = hass.states.get(FIRMWARE)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_INSTALLED_VERSION] == "3.0"


async def test_the_radio_version_is_read_once_the_radio_reports_in(
    hass: HomeAssistant,
    ap_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seen on a real Access Point: straight after a boot the radio reads 0."""
    monkeypatch.setattr(
        "custom_components.open_epaper_link.coordinator.RADIO_REPORT_INTERVAL", 0
    )
    mock_client.get_sysinfo.return_value = _sysinfo(hasC6=1, ap_version=0x22)
    await _setup(hass, ap_config_entry)
    (on_connection_change,), _ = mock_client.on_connection_change.call_args

    on_connection_change(False)
    mock_client.get_sysinfo.side_effect = [
        _sysinfo(hasC6=1, ap_version=0),
        _sysinfo(hasC6=1, ap_version=0x24),
    ]
    on_connection_change(True)
    await hass.async_block_till_done()

    assert hass.states.get(RADIO).attributes[ATTR_INSTALLED_VERSION] == "0024"


async def test_no_radio_update_without_a_radio(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Many Access Points have no radio co-processor to update."""
    mock_client.get_sysinfo.return_value = _sysinfo()
    await _setup(hass, ap_config_entry)

    assert hass.states.get(RADIO) is None


async def test_radio_update(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The radio's firmware is offered and flashed on its own."""
    mock_client.get_sysinfo.return_value = _sysinfo(hasC6=1, ap_version=0x24)
    release = _release()
    mock_client.updates.latest_release.return_value = release
    mock_client.updates.radio_version.return_value = 0x25
    await _setup(hass, ap_config_entry)

    state = hass.states.get(RADIO)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_INSTALLED_VERSION] == "0024"
    assert state.attributes[ATTR_LATEST_VERSION] == "0025"
    mock_client.updates.radio_version.assert_awaited_with(release, "C6")

    # Flashing the radio does not reboot the Access Point, so it is asked.
    mock_client.get_sysinfo.return_value = _sysinfo(hasC6=1, ap_version=0x25)
    await hass.services.async_call(
        "update", "install", {"entity_id": RADIO}, blocking=True
    )

    mock_client.updates.update_radio.assert_awaited_once()
    assert mock_client.updates.update_radio.call_args.args == (release, "C6")
    state = hass.states.get(RADIO)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_INSTALLED_VERSION] == "0025"


async def test_radio_already_current_is_no_update(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Seen on a real Access Point: radio 0024, release radio 0024."""
    mock_client.get_sysinfo.return_value = _sysinfo(hasC6=1, ap_version=0x24)
    mock_client.updates.latest_release.return_value = _release()
    mock_client.updates.radio_version.return_value = 0x24
    await _setup(hass, ap_config_entry)

    assert hass.states.get(RADIO).state == STATE_OFF


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

OTHER_TAG = "0000026C3C223B1E"
TAG_UPDATE = f"update.{TAG_MAC.lower()}_firmware"
OTHER_UPDATE = f"update.{OTHER_TAG.lower()}_firmware"
TAG_FIRMWARE = TagFirmware("SOL_M2_26_SSD", "0029", "md5")


async def test_a_tag_with_newer_firmware_offers_it(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The newest image the repository has for the tag's type."""
    mock_client.set_tags(make_tag(TAG_MAC, ver=0x27))
    mock_client.updates.tag_firmware.return_value = TAG_FIRMWARE
    await _setup(hass, ap_config_entry)

    state = hass.states.get(TAG_UPDATE)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_INSTALLED_VERSION] == "0027"
    assert state.attributes[ATTR_LATEST_VERSION] == "0029"
    assert state.attributes["title"] == "SOL_M2_26_SSD"


async def test_a_current_tag_is_up_to_date(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Seen on real tags: most report 0029, the newest there is."""
    mock_client.set_tags(make_tag(TAG_MAC, ver=0x29))
    mock_client.updates.tag_firmware.return_value = TAG_FIRMWARE
    await _setup(hass, ap_config_entry)

    assert hass.states.get(TAG_UPDATE).state == STATE_OFF


async def test_no_update_entity_where_there_is_no_firmware(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Tags the repository has nothing for, and the AP's own display, get none."""
    mock_client.set_tags(make_tag(TAG_MAC), make_tag(AP_DISPLAY_MAC, hw_type=0xE0))
    await _setup(hass, ap_config_entry)

    assert hass.states.get(TAG_UPDATE) is None
    assert hass.states.get(f"update.{AP_DISPLAY_MAC.lower()}_firmware") is None
    looked_up = {c.args[0].mac for c in mock_client.updates.tag_firmware.call_args_list}
    assert looked_up == {TAG_MAC}


async def test_tag_install_waits_for_the_tag_then_follows_it(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """No progress until the tag checks in, then its blocks."""
    mock_client.set_tags(make_tag(TAG_MAC, ver=0x27))
    mock_client.updates.tag_firmware.return_value = TAG_FIRMWARE
    await _setup(hass, ap_config_entry)
    seen: list[int | None] = []

    async def update_tag(mac, firmware, *, repo, on_progress) -> None:
        for percent in (None, 50, 100):
            on_progress(UpdateProgress(UpdateStage.TAG, percent))
            state = hass.states.get(TAG_UPDATE)
            assert state.attributes[ATTR_IN_PROGRESS]
            seen.append(state.attributes[ATTR_UPDATE_PERCENTAGE])

    mock_client.updates.update_tag.side_effect = update_tag
    await hass.services.async_call(
        "update", "install", {"entity_id": TAG_UPDATE}, blocking=True
    )

    assert seen == [None, 50, 100]
    args, kwargs = mock_client.updates.update_tag.call_args
    assert args == (TAG_MAC, TAG_FIRMWARE)
    assert kwargs["repo"] == "OpenEPaperLink/OpenEPaperLink"
    assert not hass.states.get(TAG_UPDATE).attributes[ATTR_IN_PROGRESS]


async def test_a_tag_refusing_its_firmware_says_so(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """What py-oepl reported reaches the user."""
    mock_client.set_tags(make_tag(TAG_MAC, ver=0x27))
    mock_client.updates.tag_firmware.return_value = TAG_FIRMWARE
    mock_client.updates.update_tag.side_effect = OEPLUpdateError("refused")
    await _setup(hass, ap_config_entry)

    with pytest.raises(HomeAssistantError, match="refused"):
        await hass.services.async_call(
            "update", "install", {"entity_id": TAG_UPDATE}, blocking=True
        )


async def test_tags_update_one_at_a_time(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Across every Access Point; a second install waits its turn."""
    mock_client.set_tags(make_tag(TAG_MAC, ver=0x27), make_tag(OTHER_TAG, ver=0x27))
    mock_client.updates.tag_firmware.return_value = TAG_FIRMWARE
    await _setup(hass, ap_config_entry)
    order: list[str] = []

    async def update_tag(mac, *_args: object, **_kwargs: object) -> None:
        order.append(f"start {mac}")
        await asyncio.sleep(0.01)
        order.append(f"done {mac}")

    mock_client.updates.update_tag.side_effect = update_tag
    await asyncio.gather(
        *(
            hass.services.async_call(
                "update", "install", {"entity_id": entity_id}, blocking=True
            )
            for entity_id in (TAG_UPDATE, OTHER_UPDATE)
        )
    )

    first, second = order[0].split()[1], order[2].split()[1]
    assert order == [
        f"start {first}",
        f"done {first}",
        f"start {second}",
        f"done {second}",
    ]
