"""Passive Bluetooth coordinator for tags running ATC firmware.

These are battery devices that spend nearly all their time asleep, so state
comes from advertisements, which cost the tag nothing. Connections happen only
when something is being written, and live with the code doing the writing
rather than here.

This follows the shape of Home Assistant's own opendisplay integration, which
solves the same problem for the same class of hardware.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import override

import aiohttp
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.hass_dict import HassKey
from py_atc_ble_oepl import (
    FIRMWARE_URL,
    MANUFACTURER_ID,
    AdvertisingData,
    ATCDevice,
    ATCFirmware,
    ATCProtocol,
    DeviceCapabilities,
    FirmwareError,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__package__)

type ATCConfigEntry = ConfigEntry[ATCRuntimeData]


@dataclass
class ATCRuntimeData:
    """Runtime data for an ATC tag entry."""

    coordinator: ATCCoordinator
    # One per tag: ATCDevice serialises connections on its own lock, so a
    # second instance would not be serialised against this one.
    device: ATCDevice
    capabilities: DeviceCapabilities
    # A newer upload supersedes an older rather than queueing behind it.
    upload_task: asyncio.Task[None] | None = None


@dataclass
class ATCUpdate:
    """The state carried in one advertisement."""

    address: str
    advertisement: AdvertisingData


class ATCCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """Tracks one ATC tag through its advertisements."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            address,
            BluetoothScanningMode.PASSIVE,
            connectable=True,
        )
        self.data: ATCUpdate | None = None
        # ATC tags cannot be read back the way an Access Point serves
        # /current/<mac>.raw, so the only picture we can show is the one we
        # last drew.
        self.rendered: bytes | None = None

    @callback
    def async_set_rendered(self, image: bytes) -> None:
        """Remember the image last drawn for this tag."""
        self.rendered = image
        self.async_update_listeners()

    @callback
    @override
    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Parse an advertisement, if it is one of ours."""
        if (raw := service_info.manufacturer_data.get(MANUFACTURER_ID)) is not None:
            try:
                advertisement = ATCProtocol.parse_advertising_data(raw)
            except ValueError as err:
                _LOGGER.debug(
                    "%s: could not parse advertisement: %s",
                    service_info.address,
                    err,
                    exc_info=True,
                )
            else:
                self.data = ATCUpdate(
                    address=service_info.address, advertisement=advertisement
                )

        super()._async_handle_bluetooth_event(service_info, change)


# atc1441 publishes new builds every few weeks; the image is about 120 KB.
ATC_FIRMWARE_CHECK_INTERVAL = timedelta(hours=6)
ATC_FIRMWARE: HassKey[ATCFirmwareCoordinator] = HassKey(f"{DOMAIN}_atc_firmware")


class ATCFirmwareCoordinator(DataUpdateCoordinator[ATCFirmware]):
    """Fetches the ATC firmware atc1441 publishes, for every ATC tag.

    One image serves every tag running the firmware, so one check serves
    every entry. Its version is read from the image; py-atc-ble-oepl checks
    the image is one a tag would install.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Set up the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ATC firmware",
            config_entry=None,
            update_interval=ATC_FIRMWARE_CHECK_INTERVAL,
        )

    async def _async_update_data(self) -> ATCFirmware:
        """Download the image and check it."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(FIRMWARE_URL, raise_for_status=True) as response:
                data = await response.read()
            return ATCFirmware.from_bytes(data)
        except (aiohttp.ClientError, TimeoutError, FirmwareError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="release_check_failed",
                translation_placeholders={"error": str(err)},
            ) from err


async def async_get_atc_firmware(hass: HomeAssistant) -> ATCFirmwareCoordinator:
    """Return the shared ATC firmware check, starting it on first use."""
    if (coordinator := hass.data.get(ATC_FIRMWARE)) is None:
        coordinator = hass.data[ATC_FIRMWARE] = ATCFirmwareCoordinator(hass)
        # Not a first refresh: an unreachable GitHub must not keep a tag from
        # setting up, only leave the latest version unknown.
        await coordinator.async_refresh()
    return coordinator
