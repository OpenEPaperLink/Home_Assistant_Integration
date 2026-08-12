"""Typed config entry runtime data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from py_atc_ble_oepl import AdvertisingData

    from .ble_coordinator import BLECoordinator
    from .coordinator import APCoordinator


@dataclass(slots=True)
class BLERuntimeData:
    """Runtime data for a BLE tag entry."""

    mac_address: str
    name: str
    coordinator: BLECoordinator
    advertising: AdvertisingData | None = None
    extra: dict[str, object] = field(default_factory=dict)


type OpenEPaperLinkConfigEntry = ConfigEntry[APCoordinator | BLERuntimeData]
