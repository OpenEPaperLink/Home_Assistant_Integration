"""End-to-end setup, unload and mesh ownership."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import DOMAIN

from .conftest import AP_HOST, PEER_HOST, TAG_MAC, make_ap_config, make_tag

EXTERNAL_TAG = "00000335042F3E11"


async def test_setup_creates_entities(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A configured Access Point produces entities for itself and its tags."""
    ap_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    assert ap_config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entry_id = ap_config_entry.entry_id

    ap_state = registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_ap_state")
    temperature = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry_id}_{TAG_MAC}_temperature"
    )
    assert ap_state is not None
    assert temperature is not None
    assert hass.states.get(temperature).state == "21"


async def test_setup_retries_when_ap_unreachable(
    hass: HomeAssistant,
    ap_config_entry: MockConfigEntry,
    mock_unreachable_client: AsyncMock,
) -> None:
    """An unreachable Access Point leaves the entry retrying, not broken."""
    ap_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    assert ap_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Unloading disconnects the client and releases the entry."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    assert ap_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.disconnect.assert_awaited()


async def test_devices_are_entry_scoped(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Device identifiers include the entry id, so two APs cannot collide."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = dr.async_get(hass)
    entry_id = ap_config_entry.entry_id

    ap_device = registry.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_ap"), entry_id
    )
    assert ap_device is not None
    tag_device = registry.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_{TAG_MAC}"), entry_id
    )
    assert tag_device is not None
    # Tags hang off their own Access Point, not merely off something. Asserting
    # the identity is what catches a link resolved to the wrong device, which
    # is the failure via_device was deprecated for.
    assert tag_device.via_device_id == ap_device.id


# ---------------------------------------------------------------------------
# Mesh ownership
# ---------------------------------------------------------------------------


async def test_lone_ap_shows_external_tags(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """With one Access Point configured, a mesh peer's tags are still shown.

    Filtering every external tag would hide them from someone who only added
    one Access Point of several.
    """
    ap_config_entry.add_to_hass(hass)
    mock_client.set_tags(
        make_tag(TAG_MAC),
        make_tag(EXTERNAL_TAG, is_external=True, ap_ip=PEER_HOST),
    )

    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    assert set(ap_config_entry.runtime_data.data) == {TAG_MAC, EXTERNAL_TAG}


async def test_peer_ap_claims_its_own_tags(
    hass: HomeAssistant,
    ap_config_entry: MockConfigEntry,
    peer_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Once the owning Access Point is added, the other stops claiming its tags."""
    ap_config_entry.add_to_hass(hass)
    mock_client.set_tags(
        make_tag(TAG_MAC),
        make_tag(EXTERNAL_TAG, is_external=True, ap_ip=PEER_HOST),
    )

    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = ap_config_entry.runtime_data
    assert EXTERNAL_TAG in coordinator.data

    # Added only now: an entry present before the first setup would be loaded
    # along with the component rather than on its own.
    peer_config_entry.add_to_hass(hass)
    # The peer natively owns the tag the first Access Point was only relaying.
    mock_client.for_host(PEER_HOST)
    mock_client.set_tags(make_tag(EXTERNAL_TAG), host=PEER_HOST)

    await hass.config_entries.async_setup(peer_config_entry.entry_id)
    await hass.async_block_till_done()

    assert EXTERNAL_TAG not in coordinator.data


async def test_all_platforms_create_entities(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Every platform contributes entities for the Access Point or its tags."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    by_platform: dict[str, int] = {}
    for record in er.async_entries_for_config_entry(registry, ap_config_entry.entry_id):
        by_platform[record.domain] = by_platform.get(record.domain, 0) + 1

    assert set(by_platform) == {
        "button",
        "event",
        "image",
        "select",
        "sensor",
        "switch",
        "text",
    }


async def test_subghz_select_absent_without_the_radio(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A sub-GHz channel select would configure hardware that is not there."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entry_id = ap_config_entry.entry_id
    assert (
        registry.async_get_entity_id("select", DOMAIN, f"{entry_id}_subghzchannel")
        is None
    )
    assert registry.async_get_entity_id("select", DOMAIN, f"{entry_id}_channel")


async def test_button_event_is_created_disabled(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A tag type declaring button support describes the model, not the unit.

    So the entity exists but stays disabled until a real press proves it.
    """
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "event", DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}_button"
    )
    assert entity_id is not None
    assert registry.async_get(entity_id).disabled_by is (
        er.RegistryEntryDisabler.INTEGRATION
    )


async def test_nfc_event_absent_without_the_capability(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """NFC is reported by the capability bits, which this tag does not set."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "event", DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}_nfc"
        )
        is None
    )


async def test_nfc_event_created_when_capability_present(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A tag reporting the NFC bits gets an NFC event entity, enabled."""
    ap_config_entry.add_to_hass(hass)
    # 0xC0 = NFC | NFC_WAKE, as real tags report.
    mock_client.set_tags(make_tag(TAG_MAC, capabilities=0xC0))

    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "event", DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}_nfc"
    )
    assert entity_id is not None
    assert registry.async_get(entity_id).disabled_by is None


async def test_button_event_enables_itself_on_a_real_press(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A press proves the button exists, so the entity stops being disabled."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "event", DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}_button"
    )
    assert registry.async_get(entity_id).disabled_by is not None

    # wakeupReason 4 is BUTTON1.
    coordinator = ap_config_entry.runtime_data
    coordinator._handle_tag_update(make_tag(TAG_MAC, wakeupReason=4))
    await hass.async_block_till_done()

    assert registry.async_get(entity_id).disabled_by is None


async def test_user_disabled_event_is_not_re_enabled(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Auto-enabling must never override a deliberate choice."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "event", DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}_button"
    )
    registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)

    coordinator = ap_config_entry.runtime_data
    coordinator._handle_tag_update(make_tag(TAG_MAC, wakeupReason=4))
    await hass.async_block_till_done()

    assert registry.async_get(entity_id).disabled_by is (er.RegistryEntryDisabler.USER)


async def test_each_tag_links_to_its_own_access_point(
    hass: HomeAssistant,
    ap_config_entry: MockConfigEntry,
    peer_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Two Access Points, and neither one's tags hang off the other.

    This is the case via_device was deprecated for: an identifier is only
    unique within a config entry, so resolving a parent by identifier alone
    could attach a tag to whichever Access Point happened to match first.
    """
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    peer_config_entry.add_to_hass(hass)
    mock_client.for_host(PEER_HOST)
    mock_client.set_tags(make_tag(EXTERNAL_TAG), host=PEER_HOST)
    await hass.config_entries.async_setup(peer_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = dr.async_get(hass)
    for entry, mac in (
        (ap_config_entry, TAG_MAC),
        (peer_config_entry, EXTERNAL_TAG),
    ):
        ap_device = registry.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_ap"), entry.entry_id
        )
        tag_device = registry.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_{mac}"), entry.entry_id
        )
        assert ap_device is not None
        assert tag_device is not None
        assert tag_device.via_device_id == ap_device.id


async def test_access_point_is_named_after_itself_not_its_address(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The device takes the Access Point's alias when it has one."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_ap"), ap_config_entry.entry_id
    )
    assert device.name == "Kitchen AP"


async def test_unnamed_access_point_uses_the_name_it_gives_itself(
    hass: HomeAssistant, ap_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Without an alias, the derived hostname stands in for one.

    Never the address: that changes under DHCP, and a device named after one
    would be wrong the moment it moved.
    """
    mock_client.get_ap_config.return_value = make_ap_config(alias="")
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_ap"), ap_config_entry.entry_id
    )
    # py-oepl derives this from the MAC the way the firmware does.
    assert device.name == "OpenEpaperLink-EEFF"
    assert AP_HOST not in device.name
