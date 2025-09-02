"""BLE Light platform for OpenEPaperLink integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .ble_utils import turn_led_on, turn_led_off

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BLE light entities."""
    # Only create light entity for BLE devices
    entry_data = hass.data[DOMAIN][entry.entry_id]
    if entry_data.get("type") != "ble":
        return

    mac_address = entry_data["mac_address"]
    name = entry_data["name"]
    device_metadata = entry_data.get("device_metadata", {})

    light = OpenEPaperLinkBLELight(
        mac_address=mac_address,
        name=name,
        device_metadata=device_metadata,
        entry_id=entry.entry_id,
    )

    async_add_entities([light])


class OpenEPaperLinkBLELight(LightEntity):
    """BLE Light entity for OpenEPaperLink tags.
    
    Provides LED control functionality for BLE tags using the proven
    LED commands from the POC analysis.
    """

    def __init__(
        self,
        mac_address: str,
        name: str,
        device_metadata: dict,
        entry_id: str,
    ) -> None:
        """Initialize the BLE light entity."""
        self._mac_address = mac_address
        self._name = name
        self._device_metadata = device_metadata
        self._entry_id = entry_id
        self._is_on = False
        self._available = True
        self._auto_off_task = None
        
        # Set translation key for proper localization
        self._attr_has_entity_name = True
        self._attr_translation_key = "led"

        # Device info for entity registry
        model_string = device_metadata.get('model_name', 'Unknown')
        height = device_metadata.get('height', 0)
        width = device_metadata.get('width', 0)
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ble_{mac_address}")},
            "name": name,
            "manufacturer": "OpenEPaperLink",
            "model": model_string,
            "sw_version": f"0x{device_metadata.get('fw_version', 0):04x}",
            "hw_version": f"{width}x{height}" if width and height else None,
        }

    @property
    def unique_id(self) -> str:
        """Return unique ID for this entity."""
        return f"oepl_ble_{self._mac_address}_light"


    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._is_on

    @property
    def available(self) -> bool:
        """Return true if light is available."""
        return self._available

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return supported color modes."""
        return {ColorMode.ONOFF}

    @property
    def color_mode(self) -> ColorMode:
        """Return current color mode."""
        return ColorMode.ONOFF

    @property
    def supported_features(self) -> LightEntityFeature:
        """Return supported features."""
        return LightEntityFeature(0)  # Basic on/off only

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        try:
            success = await turn_led_on(self.hass, self._mac_address)
            if success:
                self._is_on = True
                self._available = True
                self.async_write_ha_state()
                
                # Cancel any existing auto-off timer
                if self._auto_off_task and not self._auto_off_task.done():
                    self._auto_off_task.cancel()
                
                # Start auto-off timer since LED turns off when BLE connection closes
                self._auto_off_task = asyncio.create_task(self._auto_off_timer())
            else:
                self._available = False
                self.async_write_ha_state()
                raise HomeAssistantError("Failed to turn on LED")
        except Exception as e:
            self._available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Error turning on LED: {e}") from e

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            # Cancel auto-off timer since manual turn-off is requested
            if self._auto_off_task and not self._auto_off_task.done():
                self._auto_off_task.cancel()
                
            success = await turn_led_off(self.hass, self._mac_address)
            if success:
                self._is_on = False
                self._available = True
                self.async_write_ha_state()
            else:
                self._available = False
                self.async_write_ha_state()
                raise HomeAssistantError("Failed to turn off LED")
        except Exception as e:
            self._available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Error turning off LED: {e}") from e

    async def async_update(self) -> None:
        """Update the light state."""
        # For BLE lights, state is not actively polled since LED status cannot be read
        # State is maintained based on last successful command
        # Availability is updated during command execution
        pass

    async def _auto_off_timer(self) -> None:
        """Auto-off timer that turns LED off after BLE connection closes."""
        try:
            # Wait for BLE connection to close and LED to physically turn off
            await asyncio.sleep(8)  # Allow time for connection to close
            
            # Update UI state to reflect that LED is now off
            if self._is_on:  # Only update if still showing as on
                self._is_on = False
                self.async_write_ha_state()
                _LOGGER.debug("LED auto-turned off for %s after connection closed", self._mac_address)
                
        except asyncio.CancelledError:
            # Timer was cancelled (manual turn off or new turn on)
            _LOGGER.debug("Auto-off timer cancelled for %s", self._mac_address)
        except Exception as e:
            _LOGGER.error("Error in auto-off timer for %s: %s", self._mac_address, e)