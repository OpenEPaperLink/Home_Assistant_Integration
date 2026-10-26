"""Tests for the config flow.

DHCP is the intended way in, so it gets the most coverage; the pre-4.0 flow
had none at all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_DHCP, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from oepl import OEPLConnectionError
from py_atc_ble_oepl import MANUFACTURER_ID
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import (
    CONF_AP_MAC,
    CONF_HOST,
    CONF_MAC_ADDRESS,
    DOMAIN,
)

from .conftest import AP_HOST, AP_MAC

ATC_ADDRESS = "AA:BB:CC:DD:EE:01"

DHCP_INFO = DhcpServiceInfo(
    ip=AP_HOST,
    hostname="openepaperlink-abc",
    macaddress=AP_MAC.replace(":", ""),
)


@pytest.fixture
def mock_ap() -> AsyncMock:
    """A reachable AP reporting its MAC and alias."""
    with patch(
        "custom_components.open_epaper_link.config_flow.OEPLClient",
        autospec=True,
    ) as client:
        instance = client.return_value
        instance.get_sysinfo.return_value = AsyncMock(alias="Kitchen AP")
        instance.get_ap_mac = AsyncMock(return_value=AP_MAC)
        yield instance


@pytest.fixture
def mock_unreachable_ap() -> AsyncMock:
    """An AP that cannot be reached."""
    with patch(
        "custom_components.open_epaper_link.config_flow.OEPLClient",
        autospec=True,
    ) as client:
        client.return_value.get_sysinfo.side_effect = OEPLConnectionError("nope")
        yield client.return_value


# ---------------------------------------------------------------------------
# DHCP -- the primary path
# ---------------------------------------------------------------------------


async def test_dhcp_discovery(
    hass: HomeAssistant, mock_ap: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A discovered AP is added with two clicks and no typing."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_HOST: AP_HOST,
        CONF_AP_MAC: dr.format_mac(AP_MAC),
    }
    assert result["result"].unique_id == dr.format_mac(AP_MAC)


async def test_dhcp_updates_moved_ap(hass: HomeAssistant, mock_ap: AsyncMock) -> None:
    """An AP that changed address updates its entry instead of being ignored.

    Keying on the host string is what used to break this: the same AP at a new
    address looked like a different device.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=dr.format_mac(AP_MAC),
        data={CONF_HOST: "192.0.2.99", CONF_AP_MAC: dr.format_mac(AP_MAC)},
        version=5,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == AP_HOST


async def test_dhcp_offers_a_busy_ap_and_verifies_on_confirm(
    hass: HomeAssistant, mock_unreachable_ap: AsyncMock
) -> None:
    """Discovery does not probe, so a briefly busy AP is still offered.

    Reachability is checked when the user commits, which is also where an
    error can actually be shown to them.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Manual entry -- the fallback
# ---------------------------------------------------------------------------


async def test_user_flow(
    hass: HomeAssistant, mock_ap: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """Manual entry still works for setups discovery cannot reach."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: AP_HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AP_MAC] == dr.format_mac(AP_MAC)


@pytest.mark.parametrize(
    "entered", [f"http://{AP_HOST}", f"https://{AP_HOST}/", f"  {AP_HOST}/  "]
)
async def test_user_flow_normalises_host(
    hass: HomeAssistant, mock_ap: AsyncMock, mock_setup_entry: AsyncMock, entered: str
) -> None:
    """A pasted URL is accepted and reduced to a bare host."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: entered}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == AP_HOST


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, mock_unreachable_ap: AsyncMock
) -> None:
    """An unreachable host shows a resolvable error, not a raw key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: AP_HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_rejects_duplicate(
    hass: HomeAssistant, mock_ap: AsyncMock
) -> None:
    """The same physical AP cannot be added twice, even at a new address."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=dr.format_mac(AP_MAC),
        data={CONF_HOST: "192.0.2.99"},
        version=5,
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: AP_HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Mesh discovery
# ---------------------------------------------------------------------------


async def test_integration_discovery_of_peer_ap(
    hass: HomeAssistant, mock_ap: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A peer AP announced by a configured AP is offered for adding."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={CONF_HOST: AP_HOST, "alias": "Garage"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


# ---------------------------------------------------------------------------
# Bluetooth (ATC tags)
# ---------------------------------------------------------------------------


def _atc_service_info(name: str = "") -> BluetoothServiceInfoBleak:
    """A discovery for a tag running ATC firmware."""
    return BluetoothServiceInfoBleak(
        name=name or ATC_ADDRESS,
        address=ATC_ADDRESS,
        rssi=-60,
        manufacturer_data={
            # Version 2 advertisement: hw_type 0x11, fw 0x1234, 2828 mV, -8 C.
            MANUFACTURER_ID: bytes(
                [2, 0x11, 0x00, 0x34, 0x12, 0, 0, 0x0C, 0x0B, 0xF8, 0]
            )
        },
        service_data={},
        service_uuids=[],
        source="local",
        device=None,
        advertisement=None,
        connectable=True,
        time=0,
        tx_power=None,
    )


async def test_bluetooth_discovery(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_atc_reachable: AsyncMock
) -> None:
    """A discovered ATC tag is added without connecting to it."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_atc_service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MAC_ADDRESS: ATC_ADDRESS}


async def test_bluetooth_discovery_names_unnamed_tags(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Tags advertising no name get something better than a bare address.

    Home Assistant reports the address as the name in that case.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_atc_service_info()
    )
    assert result["description_placeholders"]["name"] == "ATC 11 (EE01)"


async def test_bluetooth_discovery_prefers_the_advertised_name(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """A tag that does advertise a name keeps it."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=_atc_service_info(name="Kitchen Label"),
    )
    assert result["description_placeholders"]["name"] == "Kitchen Label"


async def test_bluetooth_discovery_drops_the_name_terminator(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """ATC firmware sends its name with the C string terminator attached.

    Seen on real tags as "ATC_05D611\\x00", which then showed up in the
    discovery card.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=_atc_service_info(name="ATC_05D611\x00"),
    )
    assert result["description_placeholders"]["name"] == "ATC_05D611"


async def test_bluetooth_discovery_names_a_tag_whose_name_is_only_padding(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """A name with nothing left after the terminator falls back like no name."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=_atc_service_info(name="\x00"),
    )
    assert result["description_placeholders"]["name"].startswith("ATC ")


async def test_bluetooth_rejects_non_atc_devices(hass: HomeAssistant) -> None:
    """Another manufacturer's device is not one of ours."""
    info = _atc_service_info()
    info.manufacturer_data.clear()
    info.manufacturer_data[0x1234] = b"\x00"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_bluetooth_confirm_rejects_an_unreachable_tag(
    hass: HomeAssistant, mock_atc_unreachable: None
) -> None:
    """A tag that cannot be reached is not added.

    Discovery deliberately does not connect, so this is the first and only
    point at which the tag is proven to answer; without it an unreachable tag
    would be added silently and only fail at the first upload.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_atc_service_info()
    )
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_bluetooth_confirm_recovers_after_a_retry(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """A tag that wakes up on the second attempt can still be added."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_atc_service_info()
    )

    module = "custom_components.open_epaper_link.config_flow"
    with patch(f"{module}.bluetooth.async_ble_device_from_address", return_value=None):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "cannot_connect"}

    device = MagicMock()
    device.__aenter__ = AsyncMock(return_value=device)
    device.__aexit__ = AsyncMock(return_value=False)
    with (
        patch(
            f"{module}.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(f"{module}.ATCDevice", return_value=device),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MAC_ADDRESS: ATC_ADDRESS}


async def test_dhcp_adopts_a_pre_4_0_entry_instead_of_duplicating_it(
    hass: HomeAssistant, mock_ap: AsyncMock
) -> None:
    """A discovery must not add a second entry for an already configured AP.

    Pre-4.0 entries were keyed on the host, whichever way they were set up.
    Migration swaps that for the MAC, but it needs the MAC from the Access
    Point and so only runs once setup succeeds -- and an unreachable Access
    Point retries indefinitely, leaving the old key in place meanwhile. A
    discovery arriving in that window used to match nothing.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        # The pre-4.0 shape: keyed on the host, with no MAC stored.
        unique_id=AP_HOST,
        data={CONF_HOST: AP_HOST},
        version=4,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    # Adopted rather than abandoned: it now carries the identity it will keep.
    assert entry.unique_id == dr.format_mac(AP_MAC)
    assert entry.data[CONF_AP_MAC] == dr.format_mac(AP_MAC)


async def test_dhcp_leaves_a_different_ap_alone(
    hass: HomeAssistant, mock_ap: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """Adoption matches on the host, so a second Access Point still gets added."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.0.2.99",
        data={CONF_HOST: "192.0.2.99"},
        version=4,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.unique_id == "192.0.2.99"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2
