"""Tests for the config flow.

DHCP is the intended way in, so it gets the most coverage; the pre-4.0 flow
had none at all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from oepl import OEPLConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import CONF_AP_MAC, CONF_HOST, DOMAIN

from .conftest import AP_HOST, AP_MAC

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
        instance.get_wifi_config.return_value = AsyncMock(mac=AP_MAC)
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


async def test_dhcp_unreachable(
    hass: HomeAssistant, mock_unreachable_ap: AsyncMock
) -> None:
    """A discovery we cannot probe is abandoned rather than half-added."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


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
