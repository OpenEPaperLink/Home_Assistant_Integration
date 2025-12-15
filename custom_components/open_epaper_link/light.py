from __future__ import annotations

PARALLEL_UPDATES = 1

import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .entity import OpenEPaperLinkBLEEntity
from .runtime_data import OpenEPaperLinkConfigEntry, OpenEPaperLinkBLERuntimeData

from .const import DOMAIN
from .ble import turn_led_on, turn_led_off, get_protocol_by_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: OpenEPaperLinkConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BLE light entities."""
    # Only create light entity for BLE devices
    entry_data = entry.runtime_data
    if not isinstance(entry_data, OpenEPaperLinkBLERuntimeData):
        return

    mac_address = entry_data.mac_address
    name = entry_data.name
    device_metadata = entry_data.device_metadata
    protocol_type = entry_data.protocol_type  # Default to ATC for backward compatibility

    # Skip LED entity for OEPL devices - LED config not yet implemented
    if protocol_type == "oepl":
        return

    light = OpenEPaperLinkBLELight(
        hass=hass,
        mac_address=mac_address,
        name=name,
        device_metadata=device_metadata,
        protocol_type=protocol_type,
        entry=entry,
    )

    async_add_entities([light])


class OpenEPaperLinkBLELight(OpenEPaperLinkBLEEntity, LightEntity):
    """BLE Light entity for OpenEPaperLink tags."""

    _attr_entity_registry_enabled_default = True

    def __init__(
            self,
            hass: HomeAssistant,
            mac_address: str,
            name: str,
            device_metadata: dict,
            protocol_type: str,
            entry: OpenEPaperLinkConfigEntry,
    ) -> None:
        """Initialize the BLE light entity."""
        super().__init__(mac_address, name, entry)
        self._hass = hass
        self._device_metadata = device_metadata
        self._is_on = False
        self._auto_off_task = None
        self._protocol = get_protocol_by_name(protocol_type)
        self._service_uuid = self._protocol.service_uuid
        self._attr_translation_key = "led"

    @property
    def unique_id(self) -> str:
        """Return unique ID for this entity."""
        return f"oepl_ble_{self._mac_address}_light"

    @property
    def is_on(self) -> bool:
        """Return true if the light is on."""
        return self._is_on

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
        return LightEntityFeature(0)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        try:
            success = await turn_led_on(self.hass, self._mac_address, self._service_uuid, self._protocol)
            if success:
                self._is_on = True
                self.async_write_ha_state()
                if self._auto_off_task and not self._auto_off_task.done():
                    self._auto_off_task.cancel()
                self._auto_off_task = asyncio.create_task(self._auto_off_timer())
            else:
                self.async_write_ha_state()
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="led_on_failed"
                )
        except Exception as e:
            self.async_write_ha_state()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="led_on_error",
                translation_placeholders={"error": str(e)}
            ) from e

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            if self._auto_off_task and not self._auto_off_task.done():
                self._auto_off_task.cancel()
            success = await turn_led_off(self.hass, self._mac_address, self._service_uuid, self._protocol)
            if success:
                self._is_on = False
                self.async_write_ha_state()
            else:
                self.async_write_ha_state()
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="led_off_failed",
                )
        except Exception as e:
            self.async_write_ha_state()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="led_off_error",
                translation_placeholders= {"error": str(e)}
            ) from e

    async def async_update(self) -> None:
        """Update the light state."""
        pass

    async def _auto_off_timer(self) -> None:
        """Auto-off timer that turns LED off after BLE connection closes."""
        try:
            await asyncio.sleep(8)
            if self._is_on:
                self._is_on = False
                self.async_write_ha_state()
                _LOGGER.debug("LED auto-turned off for %s after connection closed", self._mac_address)
        except asyncio.CancelledError:
            _LOGGER.debug("Auto-off timer cancelled for %s", self._mac_address)
        except Exception as e:
            _LOGGER.error("Error in auto-off timer for %s: %s", self._mac_address, e)
