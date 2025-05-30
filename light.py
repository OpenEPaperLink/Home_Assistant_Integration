"""Light platform for OpenEPaperLink."""
from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .hub import Hub

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BLE light entity."""
    hub = hass.data[DOMAIN][entry.entry_id]
    
    # Only create BLE light if this is a BLE device
    if "mac" in entry.data and hub._ble_hub:
        device = await hub._ble_hub.add_device(entry.data["mac"])
        # Update device state before creating entity
        await device.update()
        async_add_entities([BLELight(device, entry.data["name"], entry.entry_id)])

class BLELight(LightEntity):
    """Representation of a BLE light."""

    def __init__(self, device, name: str, entry_id: str) -> None:
        """Initialize the BLE light."""
        self._device = device
        self._entry_id = entry_id
        self._attr_name = name
        self._attr_unique_id = f"ble_{self._device.mac}"
        self._attr_has_entity_name = True
        self._attr_supported_color_modes = {ColorMode.HS}
        self._attr_color_mode = ColorMode.HS
        self._device.local_callback = self.light_local_callback

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._device.is_on is not None

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if light is on."""
        return self._device.is_on

    @property
    def hs_color(self) -> tuple[float, float]:
        """Return the hs color value."""
        return self._device.hs_color

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return self._device.brightness

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"ble_{self._device.mac}")},
            name=self.name,
            connections={(format_mac(self._device.mac), self._device.mac)},
            manufacturer="OpenEPaperLink",
            model=f"HW: 0x{self._device._adv_data.hw_type:04x}" if self._device._adv_data else "Unknown",
            sw_version=f"FW: 0x{self._device._adv_data.fw_version:04x}" if self._device._adv_data else "Unknown",
            hw_version=f"0x{self._device._adv_data.hw_type:04x}" if self._device._adv_data else "Unknown"
        )

    @property
    def should_poll(self) -> bool:
        """Return False as this device should never be polled."""
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        if not self.is_on:
            await self._device.turn_on()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._device.turn_off()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the light state."""
        await self._device.update()
        self.async_write_ha_state()

    def light_local_callback(self) -> None:
        """Handle local updates from the device."""
        self.async_write_ha_state()

    async def update_ha_state(self) -> None:
        """Update Home Assistant state."""
        await self._device.update()
        self.async_write_ha_state() 