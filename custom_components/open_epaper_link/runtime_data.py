from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import Hub

@dataclass
class OpenEPaperLinkBLERuntimeData:
    """Runtime data for BLE device entries"""

    mac_address: str
    name: str
    device_metadata: dict
    protocol_type: str
    sensors: dict[str, Any] = field(default_factory=dict)

type OpenEPaperLinkConfigEntry = ConfigEntry[Hub | OpenEPaperLinkBLERuntimeData]