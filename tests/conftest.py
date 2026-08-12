"""Shared fixtures for the OpenEPaperLink test suite."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from oepl import APConfig, APInfo, OEPLConnectionError, Tag, TagType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import (
    CONF_AP_MAC,
    CONF_HOST,
    DOMAIN,
)

AP_HOST = "192.0.2.10"
AP_MAC = "aa:bb:cc:dd:ee:ff"
TAG_MAC = "00000335042F3E10"
PEER_HOST = "192.0.2.20"
PEER_MAC = "aa:bb:cc:dd:ee:aa"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Load custom_components/ in every test.

    Without this the integration is invisible to the test hass instance.
    """
    return


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Stop a created entry from actually setting the integration up.

    Without this, finishing a config flow builds a real coordinator and tries
    to open a socket to an AP that is not there.
    """
    with patch(
        "custom_components.open_epaper_link.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def ap_config_entry() -> MockConfigEntry:
    """A configured AP entry, keyed on the AP's MAC rather than its address."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen AP",
        unique_id=AP_MAC,
        data={CONF_HOST: AP_HOST, CONF_AP_MAC: AP_MAC},
        version=5,
    )


def make_tag(mac: str, **overrides: object) -> Tag:
    """Build a tag the way the Access Point reports one."""
    data = {
        "mac": mac,
        "alias": "",
        "hwType": 0x01,
        "lastseen": 1786547776,
        "nextupdate": 1786551376,
        "nextcheckin": 1786549576,
        "pending": 0,
        "contentMode": 25,
        "LQI": 120,
        "RSSI": -60,
        "temperature": 21,
        "batteryMv": 2800,
        "wakeupReason": 0,
        "capabilities": 0x04,
        "updatecount": 90,
        "isexternal": False,
        "apip": "",
        "ver": 1,
        "hash": "abc",
    }
    data.update({_WIRE_KEYS.get(k, k): v for k, v in overrides.items()})
    return Tag.from_dict(data)


_WIRE_KEYS = {"is_external": "isexternal", "ap_ip": "apip", "hw_type": "hwType"}


def make_ap_config(**extra: object) -> APConfig:
    """Build an Access Point configuration as served by /get_ap_config."""
    return APConfig.from_dict(
        {
            "alias": "Kitchen AP",
            "channel": 11,
            "led": 127,
            "tft": 128,
            "language": 0,
            "maxsleep": 60,
            "nightlyreboot": 0,
            "preview": 1,
            "lock": 0,
            "ble": 1,
            "showtimestamp": 0,
            "discovery": 1,
            "wifipower": 3,
            "sleeptime1": 0,
            "sleeptime2": 0,
            "subghzchannel": 0,
            "repo": "",
            "timezone": "UTC",
            "apstate": 1,
        }
        | extra
    )


def make_tag_type(width: int = 296, height: int = 128, **extra: object) -> TagType:
    """Build a tag type definition as served by the Access Point."""
    return TagType.from_dict(
        0x01,
        {"width": width, "height": height, "name": 'M2 2.9"', "options": ["button"]}
        | extra,
    )


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """A reachable Access Point, patched at the coordinator.

    Entry setup therefore runs for real against a fake transport rather than
    being stubbed out. Call ``mock_client.set_tags(...)`` to change what the
    Access Point reports; it defaults to a single local tag.
    """
    instances: dict[str, AsyncMock] = {}

    def build(host: str, **_: object) -> AsyncMock:
        """Return the fake Access Point at *host*, creating it on first use.

        One per host, because a mesh runs a client per Access Point and a
        shared mock would let one Access Point's tags leak into another's.
        """
        if host not in instances:
            # MagicMock rather than AsyncMock: only some of the client is
            # awaitable, and the callback registrations are plainly synchronous
            # and return an unsubscribe callable.
            instance = MagicMock()
            for name in (
                "connect",
                "disconnect",
                "get_sysinfo",
                "get_tags",
                "get_tag_type",
                "get_wifi_config",
                "get_ap_config",
                "set_ap_config_item",
                "send_tag_cmd",
                "reboot_ap",
            ):
                setattr(instance, name, AsyncMock())
            instance.get_sysinfo.return_value = APInfo.from_dict(
                {"alias": "Kitchen AP", "env": "ESP32_S3", "buildversion": "31"}
            )
            instance.get_tag_type.return_value = make_tag_type()
            instance.get_ap_config.return_value = make_ap_config()
            for name in (
                "on_tag_update",
                "on_ap_status",
                "on_connection_change",
                "on_ap_item",
            ):
                getattr(instance, name).return_value = lambda: None
            instances[host] = instance
            set_tags(make_tag(TAG_MAC), host=host)
        return instances[host]

    def set_tags(*tags: Tag, host: str = AP_HOST) -> None:
        """Point the Access Point at *host* at *tags*."""
        instance = instances[host]
        instance.get_tags.return_value = list(tags)
        instance.tags = {tag.mac: tag for tag in tags}

    with patch(
        "custom_components.open_epaper_link.coordinator.OEPLClient", side_effect=build
    ):
        default = build(AP_HOST)
        default.set_tags = set_tags
        default.for_host = build
        yield default


@pytest.fixture
def mock_unreachable_client() -> Generator[AsyncMock]:
    """An Access Point that cannot be reached, patched at the coordinator."""
    instance = MagicMock()
    instance.get_sysinfo = AsyncMock(side_effect=OEPLConnectionError("down"))
    instance.disconnect = AsyncMock()
    with patch(
        "custom_components.open_epaper_link.coordinator.OEPLClient",
        return_value=instance,
    ):
        yield instance


@pytest.fixture
def peer_config_entry() -> MockConfigEntry:
    """A second Access Point, for mesh ownership tests."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Garage AP",
        unique_id=PEER_MAC,
        data={CONF_HOST: PEER_HOST, CONF_AP_MAC: PEER_MAC},
        version=5,
    )
