from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from .ble import BLEDeviceMetadata

from .const import DOMAIN, OEPL_CONFIG_URL, ATC_CONFIG_URL
from .tag_types import get_hw_string, get_hw_dimensions

if TYPE_CHECKING:
    from .coordinator import Hub
    from .runtime_data import OpenEPaperLinkConfigEntry


class OpenEPaperLinkAPEntity(Entity):
    """
    Base entity for AP-level entities (switch, select, text, AP sensors).

    Provides:
    - device_info for AP device
    - available property (hub.online)
    - Signal registration for connection status updates
    - Common callbacks for state updates

    Subclasses must set:
    - _attr_unique_id
    - _attr_translation_key
    """
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(self, hub: Hub) -> None:
        self._hub = hub

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the AP."""
        return DeviceInfo(
            identifiers={(DOMAIN, "ap")},
            name="OpenEPaperLink AP",
            model=self._hub.ap_model,
            manufacturer="OpenEPaperLink",
            configuration_url=f"http://{self._hub.host}"
        )

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return self._hub.online

    async def async_added_to_hass(self) -> None:
        """Register the connection status signal handler."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_connection_status",
                self._handle_connection_status,
            )
        )

    @callback
    def _handle_connection_status(self, is_online: bool) -> None:
        """Handle connection status updates."""
        self.async_write_ha_state()

    @callback
    def _handle_update(self) -> None:
        """Handle data updates."""
        self.async_write_ha_state()


class OpenEPaperLinkTagEntity(Entity):
    """
    Base entity for tag-level entities (sensors, buttons, text, image).

    Provides:
    - device_info for tag device
    - available property (hub.online + tag online + not blacklisted)
    - Signal registration for tag updates and connection status
    - Common callbacks for state updates

    Subclasses must set:
    - _attr_unique_id
    - _attr_translation_key
    """
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(self, hub: Hub, tag_mac: str) -> None:
        """Initialize the tag entity."""
        self._hub = hub
        self._tag_mac = tag_mac

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the tag."""
        tag_data = self._hub.get_tag_data(self._tag_mac)
        tag_name = tag_data.get("tag_name", self._tag_mac)
        hw_type = tag_data.get("hw_type", 0)
        hw_string = get_hw_string(hw_type)
        width, height = get_hw_dimensions(hw_type)
        firmware_version = str(tag_data.get("version", ""))

        return DeviceInfo(
            identifiers={(DOMAIN, self._tag_mac)},
            name=tag_name,
            manufacturer="OpenEPaperLink",
            model=hw_string,
            via_device=(DOMAIN, "ap"),
            sw_version=f"0x{int(firmware_version, 16):X}" if firmware_version else "Unknown",
            serial_number=self._tag_mac,
            hw_version=f"{width}x{height}",
        )

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return (
                self._hub.online
                and self._hub.is_tag_online(self._tag_mac)
                and self._tag_mac not in self._hub.get_blacklisted_tags()
        )

    async def async_added_to_hass(self) -> None:
        """Register update signal handlers."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_tag_update_{self._tag_mac}",
                self._handle_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_connection_status",
                self._handle_connection_status,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle tag data updates."""
        self.async_write_ha_state()

    @callback
    def _handle_connection_status(self, is_online: bool) -> None:
        """Handle connection status updates."""
        self.async_write_ha_state()

class OpenEPaperLinkBLEEntity(Entity):
    """
    Base entity for BLE device entities (sensors, light, button, image).

    Provides:
    - device_info for BLE device (using BLEDeviceMetadata)
    - available property (bluetooth.async_address_present)

    Subclasses must set:
    - _attr_unique_id
    - _attr_translation_key
    """
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(
            self,
            mac_address: str,
            name: str,
            entry: OpenEPaperLinkConfigEntry,
    ) -> None:
        """Initialize the BLE entity."""
        self._mac_address = mac_address
        self._name = name
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the BLE device."""

        current_metadata = self._entry.runtime_data.device_metadata
        metadata = BLEDeviceMetadata(current_metadata)

        device_info = {
            "identifiers": {(DOMAIN, f"ble_{self._mac_address}")},
            "name": self._name,
            "manufacturer": "OpenEPaperLink",
            "model": metadata.model_name,
            "sw_version": metadata.formatted_fw_version(),
            "hw_version": f"{metadata.width}x{metadata.height}" if metadata.width and metadata.height else None,
        }

        if metadata.is_oepl:
            device_info["configuration_url"] = OEPL_CONFIG_URL
        else:
            device_info["configuration_url"] = ATC_CONFIG_URL

        return DeviceInfo(**device_info)

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return bluetooth.async_address_present(self.hass, self._mac_address)
