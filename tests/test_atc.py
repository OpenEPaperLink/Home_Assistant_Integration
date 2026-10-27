"""Setup and state for tags running ATC firmware."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from epaper_dithering import DitherMode
from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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


# ---------------------------------------------------------------------------
# Drawing on a Bluetooth tag
# ---------------------------------------------------------------------------


async def _draw_on(
    hass: HomeAssistant, entry: MockConfigEntry, **extra: object
) -> None:
    """Call drawcustom against a Bluetooth tag's device."""
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_{entry.data[CONF_MAC_ADDRESS]}"), entry.entry_id
    )
    await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {
            "device_id": [device.id],
            "payload": [
                {
                    "type": "rectangle",
                    "x_start": 0,
                    "y_start": 0,
                    "x_end": 5,
                    "y_end": 5,
                }
            ],
            **extra,
        },
        blocking=True,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_drawcustom_reaches_a_bluetooth_tag(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """A Bluetooth tag is as valid a target as one behind an Access Point.

    Targeting used to keep only Access Point entries, so this failed with
    "no tags were targeted" -- a targeting complaint for a path that was
    simply never wired up.
    """
    await _setup(hass, atc_config_entry)

    await _draw_on(hass, atc_config_entry)
    await hass.async_block_till_done()

    mock_atc_tag.upload_image.assert_awaited_once()
    # The geometry read at setup, in the orientation the panel displays.
    assert mock_atc_tag.upload_image.await_args.args[0].size == (152, 200)


async def test_quarter_turn_still_sends_the_panel_size(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """Rotation is laid out on a transposed canvas and turned back."""
    await _setup(hass, atc_config_entry)

    await _draw_on(hass, atc_config_entry, rotate=90)
    await hass.async_block_till_done()

    assert mock_atc_tag.upload_image.await_args.args[0].size == (152, 200)


async def test_dither_choice_reaches_the_tag(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """Dithering targets what this panel can render."""
    await _setup(hass, atc_config_entry)

    await _draw_on(hass, atc_config_entry, dither="floyd_steinberg")
    await hass.async_block_till_done()

    assert (
        mock_atc_tag.upload_image.await_args.kwargs["dither_mode"]
        is DitherMode.FLOYD_STEINBERG
    )


async def test_dry_run_previews_without_sending(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """Sending costs the tag battery and tens of seconds, so a dry run must not."""
    await _setup(hass, atc_config_entry)

    await _draw_on(hass, atc_config_entry, **{"dry-run": True})
    await hass.async_block_till_done()

    mock_atc_tag.upload_image.assert_not_awaited()
    assert atc_config_entry.runtime_data.coordinator.rendered is not None


async def test_the_action_does_not_wait_for_the_tag(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """Sending takes tens of seconds, which no automation should block on."""
    await _setup(hass, atc_config_entry)

    started, release = asyncio.Event(), asyncio.Event()

    async def _slow(*_args: object, **_kwargs: object) -> bool:
        started.set()
        await release.wait()
        return True

    mock_atc_tag.upload_image = AsyncMock(side_effect=_slow)

    await _draw_on(hass, atc_config_entry)
    await asyncio.wait_for(started.wait(), 1)

    task = atc_config_entry.runtime_data.upload_task
    assert task is not None and not task.done()

    release.set()
    await hass.async_block_till_done()


async def test_a_newer_draw_replaces_one_still_in_flight(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """The older picture is already stale, so it does not get to finish."""
    await _setup(hass, atc_config_entry)

    release = asyncio.Event()

    async def _slow(*_args: object, **_kwargs: object) -> bool:
        await release.wait()
        return True

    mock_atc_tag.upload_image = AsyncMock(side_effect=_slow)

    await _draw_on(hass, atc_config_entry)
    first = atc_config_entry.runtime_data.upload_task
    await _draw_on(hass, atc_config_entry)
    second = atc_config_entry.runtime_data.upload_task

    assert first is not second
    # Cancellation needs a turn of the loop to land, so it is waited for
    # rather than asserted the instant it is requested.
    for _ in range(10):
        if first.done():
            break
        await asyncio.sleep(0)
    assert first.cancelled()

    release.set()
    await hass.async_block_till_done()


async def test_the_device_names_the_hardware(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """From what the tag reported at setup, and the firmware it advertises."""
    atc_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = atc_config_entry.runtime_data.coordinator
    registry = dr.async_get(hass)

    def device() -> dr.DeviceEntry:
        found = registry.async_get_device_by_identifier(
            (DOMAIN, f"{atc_config_entry.entry_id}_{ATC_ADDRESS}"),
            atc_config_entry.entry_id,
        )
        assert found is not None
        return found

    assert device().manufacturer == "Hanshow"
    assert device().model == "200 HS BWY SSD"
    assert device().hw_version == "67"

    # The test advertisement reports firmware 0x1234; an update changes it.
    coordinator._async_handle_bluetooth_event(
        atc_service_info(), BluetoothChange.ADVERTISEMENT
    )
    assert device().sw_version == "1234"
    newer = atc_service_info()
    newer.manufacturer_data[MANUFACTURER_ID] = bytes(
        [2, 0x11, 0x00, 0x35, 0x12, 0, 0, 0x0C, 0x0B, 0xF8, 0]
    )
    coordinator._async_handle_bluetooth_event(newer, BluetoothChange.ADVERTISEMENT)
    assert device().sw_version == "1235"


async def test_a_tag_of_unknown_make_is_credited_to_openepaperlink(
    hass: HomeAssistant, atc_config_entry: MockConfigEntry, mock_atc_tag: MagicMock
) -> None:
    """The WO types and the dynamic one do not name their maker."""
    mock_atc_tag.device_config = MagicMock(screen_type=65535, hw_type=0x33)
    atc_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(atc_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{atc_config_entry.entry_id}_{ATC_ADDRESS}"),
        atc_config_entry.entry_id,
    )
    assert device is not None
    assert (device.manufacturer, device.model) == ("OpenEPaperLink", None)
