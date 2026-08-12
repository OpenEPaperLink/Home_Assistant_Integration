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
from typing import override

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
from py_atc_ble_oepl import MANUFACTURER_ID, AdvertisingData, ATCProtocol

_LOGGER = logging.getLogger(__package__)

type ATCConfigEntry = ConfigEntry[ATCRuntimeData]


@dataclass
class ATCRuntimeData:
    """Runtime data for an ATC tag entry."""

    coordinator: ATCCoordinator
    # Uploads take tens of seconds over Bluetooth; a newer one supersedes an
    # older rather than queueing behind it.
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
